"""SQLite storage for CallWise Meetings with server-side access checks."""
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_init_lock = threading.Lock()
_initialized: set[str] = set()


def db_path() -> Path:
    return Path(os.getenv('MEETINGS_DB_PATH') or ROOT / 'data' / 'meetings.db')


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, login TEXT UNIQUE NOT NULL, name TEXT NOT NULL, role TEXT NOT NULL DEFAULT '',
  password_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL REFERENCES users(id), title TEXT NOT NULL, filename TEXT NOT NULL,
  kind TEXT NOT NULL, content BLOB NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS document_access (
  document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id),
  PRIMARY KEY (document_id, user_id));
CREATE TABLE IF NOT EXISTS fragments (
  id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE, idx INTEGER NOT NULL,
  location TEXT NOT NULL, text TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS meetings (
  id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL REFERENCES users(id), title TEXT NOT NULL, topic TEXT NOT NULL DEFAULT '',
  scheduled_at TEXT, participants TEXT NOT NULL DEFAULT '[]', speaker_map TEXT NOT NULL DEFAULT '{}',
  followup_of INTEGER, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS meeting_access (
  meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id),
  PRIMARY KEY (meeting_id, user_id));
CREATE TABLE IF NOT EXISTS meeting_documents (
  meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
  document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE, PRIMARY KEY (meeting_id, document_id));
CREATE TABLE IF NOT EXISTS utterances (
  id INTEGER PRIMARY KEY, meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE, idx INTEGER NOT NULL,
  speaker_label TEXT NOT NULL, text TEXT NOT NULL, original_text TEXT NOT NULL, edited INTEGER NOT NULL DEFAULT 0,
  source TEXT NOT NULL DEFAULT 'manual', start_ms INTEGER, deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS preps (
  meeting_id INTEGER PRIMARY KEY REFERENCES meetings(id) ON DELETE CASCADE, data TEXT NOT NULL, generated_by INTEGER,
  created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS protocols (
  meeting_id INTEGER PRIMARY KEY REFERENCES meetings(id) ON DELETE CASCADE, warnings TEXT NOT NULL DEFAULT '[]',
  generated_at TEXT, model TEXT);
CREATE TABLE IF NOT EXISTS protocol_items (
  id INTEGER PRIMARY KEY, meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE, position INTEGER NOT NULL,
  kind TEXT NOT NULL, text TEXT NOT NULL, outcome TEXT, assignee TEXT, assignee_status TEXT NOT NULL DEFAULT 'unknown',
  due TEXT, due_text TEXT, due_status TEXT NOT NULL DEFAULT 'unknown', quotes TEXT NOT NULL DEFAULT '[]',
  confirmed_by INTEGER, confirmed_at TEXT, task_id INTEGER, edited INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY, meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
  protocol_item_id INTEGER UNIQUE NOT NULL, text TEXT NOT NULL, assignee TEXT, assignee_status TEXT NOT NULL,
  due TEXT, due_text TEXT, due_status TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', source_quote TEXT NOT NULL,
  confirmed_by INTEGER NOT NULL, confirmed_at TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY, at TEXT NOT NULL, user_id INTEGER, action TEXT NOT NULL, details TEXT NOT NULL DEFAULT '{}');
"""


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys=ON')
    key = str(path.resolve())
    if key not in _initialized:
        with _init_lock:
            if key not in _initialized:
                connection.executescript(SCHEMA)
                _initialized.add(key)
    return connection


@contextmanager
def db():
    connection = _connect()
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def reset_cache():
    _initialized.clear()


def audit(connection, user_id, action, **details):
    connection.execute('INSERT INTO audit(at,user_id,action,details) VALUES (?,?,?,?)',
                       (now(), user_id, action, json.dumps(details, ensure_ascii=False)))


# ---------- access ----------

def can_read_meeting(connection, user_id: int, meeting_id: int) -> bool:
    row = connection.execute(
        'SELECT 1 FROM meetings m WHERE m.id=? AND (m.owner_id=? OR EXISTS '
        '(SELECT 1 FROM meeting_access a WHERE a.meeting_id=m.id AND a.user_id=?))',
        (meeting_id, user_id, user_id)).fetchone()
    return row is not None


def can_read_document(connection, user_id: int, document_id: int) -> bool:
    row = connection.execute(
        'SELECT 1 FROM documents d WHERE d.id=? AND (d.owner_id=? OR EXISTS '
        '(SELECT 1 FROM document_access a WHERE a.document_id=d.id AND a.user_id=?))',
        (document_id, user_id, user_id)).fetchone()
    return row is not None


def accessible_document_ids(connection, user_id: int) -> list[int]:
    return [r[0] for r in connection.execute(
        'SELECT d.id FROM documents d WHERE d.owner_id=? OR EXISTS '
        '(SELECT 1 FROM document_access a WHERE a.document_id=d.id AND a.user_id=?) ORDER BY d.id', (user_id, user_id))]


def accessible_meeting_ids(connection, user_id: int) -> list[int]:
    return [r[0] for r in connection.execute(
        'SELECT m.id FROM meetings m WHERE m.owner_id=? OR EXISTS '
        '(SELECT 1 FROM meeting_access a WHERE a.meeting_id=m.id AND a.user_id=?) ORDER BY m.id', (user_id, user_id))]


# ---------- serializers ----------

def user_name(connection, user_id):
    if user_id is None:
        return None
    row = connection.execute('SELECT name FROM users WHERE id=?', (user_id,)).fetchone()
    return row['name'] if row else None


def document_out(connection, row) -> dict:
    count = connection.execute('SELECT COUNT(*) FROM fragments WHERE document_id=?', (row['id'],)).fetchone()[0]
    shared = [r[0] for r in connection.execute('SELECT user_id FROM document_access WHERE document_id=?', (row['id'],))]
    return {'id': row['id'], 'title': row['title'], 'filename': row['filename'], 'kind': row['kind'],
            'owner_id': row['owner_id'], 'owner_name': user_name(connection, row['owner_id']),
            'shared_with': shared, 'fragments_count': count, 'created_at': row['created_at']}


def fragment_out(row, title=None) -> dict:
    return {'id': f"F{row['id']}", 'document_id': row['document_id'], 'document_title': title or row['title'],
            'idx': row['idx'], 'location': row['location'], 'text': row['text']}


def meeting_out(connection, row) -> dict:
    access = [r[0] for r in connection.execute('SELECT user_id FROM meeting_access WHERE meeting_id=?', (row['id'],))]
    return {'id': row['id'], 'title': row['title'], 'topic': row['topic'], 'scheduled_at': row['scheduled_at'],
            'participants': json.loads(row['participants']), 'owner_id': row['owner_id'],
            'owner_name': user_name(connection, row['owner_id']), 'access_user_ids': access,
            'speaker_map': json.loads(row['speaker_map']), 'followup_of': row['followup_of'],
            'created_at': row['created_at']}


def utterance_out(row, speaker_map: dict) -> dict:
    label = row['speaker_label']
    return {'id': f"U{row['id']}", 'meeting_id': row['meeting_id'], 'idx': row['idx'], 'speaker_label': label,
            'speaker': speaker_map.get(label) or label, 'text': row['text'], 'original_text': row['original_text'],
            'edited': bool(row['edited']), 'source': row['source'], 'start_ms': row['start_ms']}


def item_out(connection, row) -> dict:
    return {'id': row['id'], 'kind': row['kind'], 'text': row['text'], 'outcome': row['outcome'],
            'assignee': row['assignee'], 'assignee_status': row['assignee_status'], 'due': row['due'],
            'due_text': row['due_text'], 'due_status': row['due_status'], 'quotes': json.loads(row['quotes']),
            'confirmed': row['confirmed_at'] is not None, 'confirmed_by': user_name(connection, row['confirmed_by']),
            'confirmed_at': row['confirmed_at'], 'task_id': row['task_id'], 'edited': bool(row['edited'])}


def task_out(connection, row) -> dict:
    meeting = connection.execute('SELECT title FROM meetings WHERE id=?', (row['meeting_id'],)).fetchone()
    return {'id': row['id'], 'text': row['text'], 'assignee': row['assignee'], 'assignee_status': row['assignee_status'],
            'due': row['due'], 'due_text': row['due_text'], 'due_status': row['due_status'], 'status': row['status'],
            'meeting_id': row['meeting_id'], 'meeting_title': meeting['title'] if meeting else None,
            'protocol_item_id': row['protocol_item_id'], 'source_quote': json.loads(row['source_quote']),
            'confirmed_by': user_name(connection, row['confirmed_by']), 'confirmed_at': row['confirmed_at'],
            'created_at': row['created_at'], 'updated_at': row['updated_at']}


def speaker_map(connection, meeting_id) -> dict:
    row = connection.execute('SELECT speaker_map FROM meetings WHERE id=?', (meeting_id,)).fetchone()
    return json.loads(row['speaker_map']) if row else {}


def utterances(connection, meeting_id) -> list[dict]:
    mapping = speaker_map(connection, meeting_id)
    rows = connection.execute('SELECT * FROM utterances WHERE meeting_id=? AND deleted=0 ORDER BY idx, id', (meeting_id,))
    return [utterance_out(r, mapping) for r in rows]


def protocol(connection, meeting_id) -> dict | None:
    head = connection.execute('SELECT * FROM protocols WHERE meeting_id=?', (meeting_id,)).fetchone()
    if not head:
        return None
    items = [item_out(connection, r) for r in connection.execute(
        'SELECT * FROM protocol_items WHERE meeting_id=? ORDER BY position, id', (meeting_id,))]
    confirmed = any(i['confirmed'] for i in items)
    return {'meeting_id': meeting_id, 'status': 'partially_confirmed' if confirmed else 'draft', 'items': items,
            'warnings': json.loads(head['warnings']), 'generated_at': head['generated_at'], 'model': head['model']}


def prep(connection, meeting_id) -> dict | None:
    row = connection.execute('SELECT data FROM preps WHERE meeting_id=?', (meeting_id,)).fetchone()
    return json.loads(row['data']) if row else None
