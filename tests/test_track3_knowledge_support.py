"""Isolated test-only schema mirrors the migration request; never touches live DB."""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from meetings import llm, store
from meetings.api import install
from meetings.knowledge.api import router as knowledge_router
from meetings.management.api import router as management_router


SCHEMA = '''
CREATE TABLE IF NOT EXISTS qa_answers(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),
 meeting_id INTEGER,question_masked TEXT NOT NULL,question_sha256 TEXT NOT NULL,status TEXT NOT NULL,
 answer TEXT NOT NULL DEFAULT '',claims TEXT NOT NULL DEFAULT '[]',source_ids TEXT NOT NULL DEFAULT '[]',
 model TEXT,request_id TEXT,generated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS production_metrics(id INTEGER PRIMARY KEY,source_id TEXT UNIQUE NOT NULL,
 owner_id INTEGER REFERENCES users(id),scope TEXT NOT NULL,period_start TEXT NOT NULL,period_end TEXT NOT NULL,as_of TEXT NOT NULL,
 completed_orders INTEGER,on_time_orders INTEGER,produced_units INTEGER,defective_units INTEGER,
 available_capacity REAL,occupied_capacity REAL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS production_metric_access(metric_id INTEGER REFERENCES production_metrics(id) ON DELETE CASCADE,
 user_id INTEGER REFERENCES users(id),PRIMARY KEY(metric_id,user_id));
'''


class Model:
    model = 'scripted-test-double'

    def __init__(self):
        self.calls = []
        self.reply = None
        self.during = None

    def json(self, system, user, schema, predict=1500):
        self.calls.append((system, json.loads(user)))
        if self.during:
            self.during()
        if isinstance(self.reply, Exception):
            raise self.reply
        if self.reply is not None:
            return self.reply
        row = json.loads(user)['untrusted_documents'][0]
        return {'claims': [{'text': row['text'], 'quote': row['text'], 'fragment_id': row['fragment_id']}]}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('MEETINGS_DB_PATH', str(tmp_path / 'isolated.db'))
    monkeypatch.setenv('MEETINGS_SECRET', 'track3-tests-only')
    monkeypatch.setenv('MEETINGS_DEMO_USERS', 'true')
    store.reset_cache()
    model = Model()
    llm.set_llm(model)
    app = FastAPI()
    install(app)
    if '/api/meet/qa' not in app.openapi()['paths']:
        app.include_router(knowledge_router())
        app.include_router(management_router())
        app.openapi_schema = None
    with store.db() as connection:
        connection.executescript(SCHEMA)
    clients = {}
    for name in ('irina', 'petr'):
        client = TestClient(app)
        assert client.post('/api/meet/login', json={'login': name, 'password': name + '-demo'}).status_code == 200
        clients[name] = client
    env = {'app': app, 'model': model, **clients}
    yield env
    llm.set_llm(None)
    store.reset_cache()


def document(client, text, title='План запуска', shared=''):
    response = client.post('/api/meet/documents', files={'file': ('plan.txt', text.encode('utf-8'))},
                           data={'title': title, 'share_with': shared})
    assert response.status_code == 200, response.text
    doc = response.json()['document']
    fragment = client.get(f"/api/meet/documents/{doc['id']}").json()['fragments'][0]['id']
    return doc['id'], fragment


def meeting(client, docs=(), shared=()):
    response = client.post('/api/meet/meetings', json={'title': 'Запуск', 'access_user_ids': list(shared)})
    assert response.status_code == 200, response.text
    mid = response.json()['meeting']['id']
    for doc_id in docs:
        assert client.post(f'/api/meet/meetings/{mid}/documents', json={'document_id': doc_id}).status_code == 200
    return mid


def task(mid, *, text='Подготовить отчёт', status='open', due='2026-11-10', due_status='stated'):
    stamp = '2026-11-11T08:00:00+00:00'
    with store.db() as connection:
        return connection.execute('INSERT INTO tasks(meeting_id,protocol_item_id,text,assignee_status,due,due_status,'
            'status,source_quote,confirmed_by,confirmed_at,created_at,updated_at) '
            'VALUES (?,?,?, ?,?,?, ?,?,?, ?,?,?)',
            (mid, connection.execute('SELECT COALESCE(MAX(id),0)+1 FROM tasks').fetchone()[0], text,
             'unknown', due, due_status, status, '{}', 1, stamp, stamp, stamp)).lastrowid


def snapshot(source_id='print-1', owner=1, scope='print', at='2026-11-11T09:00:00+00:00',
             values=(90, 100, 20, 1000, 60, 80), shared=(),
             start='2026-11-01T00:00:00+03:00', end='2026-12-01T00:00:00+03:00'):
    with store.db() as connection:
        on_time, completed, defective, produced, occupied, available = values
        cursor = connection.execute('INSERT INTO production_metrics(source_id,owner_id,scope,as_of,period_start,period_end,'
            'on_time_orders,completed_orders,defective_units,produced_units,occupied_capacity,available_capacity,created_at) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (source_id, owner, scope, at, start, end, on_time, completed, defective, produced, occupied, available, at))
        connection.executemany('INSERT INTO production_metric_access VALUES (?,?)', [(cursor.lastrowid, uid) for uid in shared])


def audit_rows(action):
    with store.db() as connection:
        result = []
        for row in connection.execute('SELECT * FROM audit WHERE action=? ORDER BY id', (action,)):
            data = json.loads(row['details'])
            for key in ('request_id', 'object_id', 'result', 'model', 'error_code', 'source_ids'):
                if key in row.keys() and row[key] is not None:
                    data[key] = json.loads(row[key]) if key == 'source_ids' else row[key]
            result.append(data)
        return result
