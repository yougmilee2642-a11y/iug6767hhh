"""Seed the CallWise Meetings demo (idempotent). Usage:
    .venv\\Scripts\\python scripts\\seed_meetings_demo.py [--reset] [--with-transcript]
--reset            only an explicit marked test --db, also requires --confirm-delete
--with-transcript  also load demo/meetings/transcript.txt into the launch meeting
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from meetings import documents as docs  # noqa: E402
from meetings import store  # noqa: E402
from meetings.api import parse_transcript  # noqa: E402
from meetings.auth import ensure_demo_users  # noqa: E402

DEMO = ROOT / 'demo' / 'meetings'
LAUNCH = 'Запуск «Орбиты»: готовность к 1 декабря'
DESIGN = 'Синк по дизайну кампании'


def add_document(connection, owner, filename, title, share=()):
    row = connection.execute('SELECT id FROM documents WHERE filename=? AND owner_id=?', (filename, owner)).fetchone()
    if row:
        return row['id']
    data = (DEMO / filename).read_bytes()
    kind, fragments = docs.fragments(filename, data)
    cursor = connection.execute('INSERT INTO documents(owner_id,title,filename,kind,content,sha256,created_at) VALUES (?,?,?,?,?,?,?)',
                                (owner, title, filename, kind, data, hashlib.sha256(data).hexdigest(), store.now()))
    connection.executemany('INSERT INTO fragments(document_id,idx,location,text) VALUES (?,?,?,?)',
                           [(cursor.lastrowid, f['idx'], f['location'], f['text']) for f in fragments])
    for user_id in share:
        connection.execute('INSERT OR IGNORE INTO document_access VALUES (?,?)', (cursor.lastrowid, user_id))
    return cursor.lastrowid


def add_meeting(connection, owner, title, topic, when, participants, access=()):
    row = connection.execute('SELECT id FROM meetings WHERE title=? AND owner_id=?', (title, owner)).fetchone()
    if row:
        return row['id']
    cursor = connection.execute('INSERT INTO meetings(owner_id,title,topic,scheduled_at,participants,created_at) VALUES (?,?,?,?,?,?)',
                                (owner, title, topic, when, json.dumps(participants, ensure_ascii=False), store.now()))
    for user_id in access:
        connection.execute('INSERT OR IGNORE INTO meeting_access VALUES (?,?)', (cursor.lastrowid, user_id))
    return cursor.lastrowid


def seed(with_transcript=False):
    ensure_demo_users()
    with store.db() as connection:
        users = {r['login']: r['id'] for r in connection.execute('SELECT id,login FROM users')}
        irina, petr = users['irina'], users['petr']
        plan = add_document(connection, irina, 'launch_plan.docx', 'План запуска «Орбиты»')
        risks = add_document(connection, irina, 'risk_register.pdf', 'Реестр рисков «Орбиты»')
        budget = add_document(connection, irina, 'budget.txt', 'Бюджет маркетинговой кампании')
        brand = add_document(connection, petr, 'brand_guide.txt', 'Гайд по бренду', share=(irina,))
        launch = add_meeting(connection, irina, LAUNCH,
                             'Укладываемся ли в дату запуска 1 декабря с учётом отставания интеграции платёжного шлюза',
                             '2026-11-12T10:00', ['Ирина Власова', 'Анна Ковалёва', 'Дмитрий Орлов'])
        for document_id in (plan, risks, budget):
            connection.execute('INSERT OR IGNORE INTO meeting_documents VALUES (?,?)', (launch, document_id))
        design = add_meeting(connection, petr, DESIGN, 'Баннеры и сроки сдачи макетов', '2026-11-13T15:00',
                             ['Пётр Смирнов', 'Ирина Власова'], access=(irina,))
        connection.execute('INSERT OR IGNORE INTO meeting_documents VALUES (?,?)', (design, brand))
        if with_transcript and not connection.execute('SELECT 1 FROM utterances WHERE meeting_id=? AND deleted=0', (launch,)).fetchone():
            for i, u in enumerate(parse_transcript((DEMO / 'transcript.txt').read_text(encoding='utf-8')), 1):
                connection.execute('INSERT INTO utterances(meeting_id,idx,speaker_label,text,original_text,source,start_ms) '
                                   'VALUES (?,?,?,?,?,?,?)', (launch, i, u['speaker_label'], u['text'], u['text'], 'manual', u['start_ms']))
    return {'launch_meeting': launch, 'design_meeting': design}


if __name__ == '__main__':
    import argparse
    import os
    from scripts.track3.paths import explicit_db
    from scripts.track3.cleanup import cleanup
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', help='Absolute isolated test DB; default retained only for non-destructive legacy seed')
    parser.add_argument('--reset', action='store_true')
    parser.add_argument('--confirm-delete', action='store_true')
    parser.add_argument('--with-transcript', action='store_true')
    args = parser.parse_args()
    if args.db:
        test_path = explicit_db(args.db)
        marker = Path(str(test_path)+'.track3.json')
        if marker.is_symlink() or (test_path.exists() and not marker.is_file()):
            parser.error('Existing test DB needs a regular Track 3 marker')
        if marker.is_file() and json.loads(marker.read_text(encoding='utf-8')).get('db') != str(test_path):
            parser.error('Test marker path mismatch')
        os.environ['MEETINGS_DB_PATH'] = str(test_path)
    if args.reset:
        if not args.db or not args.confirm_delete:
            parser.error('--reset requires an explicit marked test --db and --confirm-delete; working data/ is protected')
        cleanup(args.db, confirm=True)
        store.reset_cache()
    print(seed(args.with_transcript))
    if args.db and not marker.exists():
        marker.write_text(json.dumps({'version':1,'db':str(test_path),'dataset':'orbita-demo'}), encoding='utf-8')
