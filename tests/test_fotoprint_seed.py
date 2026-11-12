"""V2 fixtures, safe CLI, append-only migration and document source fidelity."""
import hashlib
import io
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from meetings import documents, migrations, store
from meetings.api import install
from scripts.track3.evaluate import frozen_check
from scripts.track3.seed_fotoprint import seed

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    monkeypatch.setenv('MEETINGS_DB_PATH', str(tmp_path / 'demo.db'))
    monkeypatch.setenv('MEETINGS_SECRET', 'v2-test-not-a-production-secret')
    ids = seed(str(tmp_path / 'demo.db'))
    yield ids
    store.reset_cache()


def test_seed_counts_passwords_and_no_duplicate_sources(seeded, tmp_path):
    tables = ['users', 'departments', 'documents', 'fragments', 'meetings', 'utterances', 'tasks', 'erp_orders',
              'crm_customers', 'support_interactions', 'production_plan', 'work_shifts', 'finance_aggregates']
    with store.db() as c:
        before = {t: c.execute('SELECT COUNT(*) FROM ' + t).fetchone()[0] for t in tables}
        assert before['users'] == 18 and before['departments'] == 12
        assert before['documents'] == 54 and before['meetings'] >= 5
        assert before['erp_orders'] == 600 and before['crm_customers'] == 250 and before['support_interactions'] == 400
        assert c.execute('SELECT COUNT(*) FROM tasks WHERE status!=\'done\' AND due < ?', ('2026-11-11',)).fetchone()[0] == 3
        assert c.execute('SELECT COUNT(*) FROM tasks WHERE due IS NULL').fetchone()[0] == 1
        assert c.execute('SELECT supersedes_id FROM documents WHERE id=?', (seeded['documents']['v2_quality'],)).fetchone()[0] == seeded['documents']['v2_old_instruction']
        assert c.execute('SELECT COUNT(*) FROM calendar_busy').fetchone()[0] > 0
        assert c.execute('PRAGMA foreign_key_check').fetchall() == []
        for t in ['crm_customers', 'erp_orders', 'support_interactions']:
            for row in c.execute('SELECT * FROM ' + t):
                text = json.dumps(dict(row), ensure_ascii=False)
                assert not re.search(r'\+\d[\d ()-]{8,}\d|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', text)
    app = FastAPI(); install(app)
    client = TestClient(app)
    manifest = json.loads((ROOT / 'demo/track3/v2/manifest.json').read_text())
    for u in manifest['users']:
        response = client.post('/api/meet/login', json={'login': u['login'], 'password': u['login'] + '-demo'})
        assert response.status_code == 200
        assert response.json()['user']['level'] == u['level']
    assert seed(str(tmp_path / 'demo.db')) == seeded
    with store.db() as c:
        assert before == {t: c.execute('SELECT COUNT(*) FROM ' + t).fetchone()[0] for t in tables}
    assert frozen_check()


def test_generator_is_byte_reproducible_and_keeps_v1(tmp_path):
    from scripts.track3.gen_fotoprint_data import build
    for folder in ['demo/track3', 'evaluation/track3']:
        shutil.copytree(ROOT / folder, tmp_path / folder)
    before = {p.relative_to(tmp_path): p.read_bytes() for p in (tmp_path / 'demo/track3/documents').glob('fp_*')}
    build(tmp_path)
    first = {p.relative_to(tmp_path): hashlib.sha256(p.read_bytes()).hexdigest() for p in (tmp_path / 'demo/track3').rglob('*') if p.is_file()}
    build(tmp_path)
    assert first == {p.relative_to(tmp_path): hashlib.sha256(p.read_bytes()).hexdigest() for p in (tmp_path / 'demo/track3').rglob('*') if p.is_file()}
    assert all((tmp_path / p).read_bytes() == data for p, data in before.items())
    gold = json.loads((tmp_path / 'demo/track3/v2/task-gold.json').read_text())
    assert len(gold['transcripts']) == 5 and sum(len(t['tasks']) for t in gold['transcripts']) == 30


def test_migrate_populated_v8_preserves_content_and_acl(tmp_path, monkeypatch):
    path = tmp_path / 'old.db'
    c = sqlite3.connect(path)
    c.executescript(store.SCHEMA)
    original = migrations.MIGRATIONS
    monkeypatch.setattr(migrations, 'MIGRATIONS', original[:8])
    migrations.apply(c)
    assert c.execute('PRAGMA user_version').fetchone()[0] == 8
    c.execute("INSERT INTO users(id,login,name,password_hash) VALUES (55,'old','Прежний','no-login')")
    c.execute("INSERT INTO documents(id,owner_id,title,filename,kind,content,sha256,created_at) VALUES (66,55,'Старый','old.txt','txt',?,'abc','2026-01-01T00:00:00+00:00')", (b'keep original',))
    c.execute('INSERT INTO document_access VALUES (66,55)'); c.commit()
    monkeypatch.setattr(migrations, 'MIGRATIONS', original)
    assert migrations.apply(c) == [9]
    assert migrations.apply(c) == []
    assert c.execute('SELECT content FROM documents WHERE id=66').fetchone()[0] == b'keep original'
    assert c.execute('SELECT * FROM document_access').fetchall() == [(66, 55)]
    assert c.execute('SELECT level FROM users WHERE id=55').fetchone()[0] is None
    assert c.execute('PRAGMA foreign_key_check').fetchall() == []
    c.close()


def test_cli_defaults_to_photoprint_and_reset_stays_in_marked_path(tmp_path):
    import os
    target = tmp_path / 'explicit.db'
    env = {**os.environ, 'MEETINGS_DB_PATH': str(target), 'MEETINGS_SECRET': 'cli-test'}
    command = [sys.executable, str(ROOT / 'scripts/seed_meetings_demo.py')]
    r = subprocess.run(command, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)['dataset'] == 'photoprint-v2'
    r = subprocess.run([*command, '--reset'], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    for unsafe in [str(ROOT / 'data/meetings.db'), 'relative.db']:
        r = subprocess.run(command, env={**env, 'MEETINGS_DB_PATH': unsafe}, capture_output=True, text=True)
        assert r.returncode != 0
    foreign = tmp_path / 'foreign.db'; foreign.write_bytes(b'never delete')
    r = subprocess.run([*command, '--reset'], env={**env, 'MEETINGS_DB_PATH': str(foreign)}, capture_output=True, text=True)
    assert r.returncode != 0 and foreign.read_bytes() == b'never delete'


def test_extended_readers_keep_conditions_headers_and_locations():
    manifest = json.loads((ROOT / 'demo/track3/v2/manifest.json').read_text())
    types = set()
    for doc in manifest['documents']:
        kind, fragments = documents.fragments(doc['filename'], (ROOT / 'demo/track3' / doc['path']).read_bytes())
        types.add(kind)
        if 'sha256' in doc:
            assert hashlib.sha256((ROOT / 'demo/track3' / doc['path']).read_bytes()).hexdigest() == doc['sha256']
        assert fragments and all(f['text'] and f['location'] for f in fragments)
        if kind == 'xlsx':
            assert all('!' in f['location'] and 'Факт:' in f['text'] for f in fragments)
    assert {'txt', 'docx', 'pdf', 'csv', 'xlsx', 'md', 'eml'} <= types
    _, fragments = documents.fragments('check.csv', 'Товар;Условие\nPremium;Не печатать, если макет не утверждён\n'.encode())
    assert fragments[0]['text'] == 'Товар: Premium; Условие: Не печатать, если макет не утверждён'
    with pytest.raises(documents.DocumentError):
        documents.fragments('bad.csv', ('A;B\n1;' + 'x' * 21000).encode())
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as z:
        z.writestr('ppt/slides/slide1.xml', '<p:sld xmlns:p="p" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:p><a:r><a:t>Не менять срок без подтверждения.</a:t></a:r></a:p></p:sld>')
    assert documents.fragments('check.pptx', output.getvalue())[1][0]['text'] == 'Не менять срок без подтверждения.'
    assert documents.fragments('check.html', b'<p>Visible condition.</p><script>steal()</script>')[1][0]['text'] == 'Visible condition.'
    with pytest.raises(documents.DocumentError):
        documents.fragments('check.xlsx', b'not a ZIP')


@pytest.mark.parametrize('name,data', [('wrong.txt', b'\x89PNG\r\nimage'), ('wrong.csv', b'PK\x03\x04binary'),
                                      ('wrong.pdf', b'plain text'), ('wrong.docx', b'plain text')])
def test_disguised_binary_is_rejected(name, data):
    with pytest.raises(documents.DocumentError):
        documents.fragments(name, data)
