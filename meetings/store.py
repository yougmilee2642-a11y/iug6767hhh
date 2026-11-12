"""SQLite storage for CallWise Meetings with server-side access checks."""
import contextvars
import hashlib
import json
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from meetings import migrations

ROOT = Path(__file__).resolve().parents[1]
_init_lock = threading.Lock()
_initialized: set[str] = set()


def db_path() -> Path:
    return Path(os.getenv('MEETINGS_DB_PATH') or ROOT / 'data' / 'meetings.db')


def now() -> str:
    """Aware UTC timestamp. Never the OS zone (ОТ-07)."""
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


# ---------- time ----------
DISPLAY_ZONE = 'Europe/Minsk'


class TimeError(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code, self.detail = code, detail


def zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or DISPLAY_ZONE)
    except (ZoneInfoNotFoundError, ValueError):
        raise TimeError('invalid_timezone', f'Неизвестный часовой пояс: {str(name)[:60]}.') from None


def parse_aware(value: str, tz_name: str | None = None) -> datetime:
    """ISO 8601 → aware UTC datetime. A value without offset is accepted ONLY when an explicit IANA timezone
    is passed; otherwise it is rejected (no guessing from the server zone)."""
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace('Z', '+00:00'))
    except ValueError:
        # Details are shown to people; the API format (ISO 8601 with offset, or `timezone`) is in the handoff.
        raise TimeError('invalid_datetime', 'Дата и время указаны в неверном формате. Ничего не сохранено.') from None
    if parsed.tzinfo is None:
        if not tz_name:
            raise TimeError('naive_datetime', 'Не указан часовой пояс, поэтому время нельзя понять однозначно. '
                            'Ничего не сохранено.')
        parsed = parsed.replace(tzinfo=zone(tz_name))
    return parsed.astimezone(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec='seconds')


def stored_utc(value: str | None) -> str | None:
    """Read side for stored timestamps. Legacy naive demo values are read as Europe/Minsk (documented rule),
    exactly as migration 003 converts them."""
    return migrations.legacy_to_utc(value) if value else None


def local_date(value: str | None, tz_name: str = DISPLAY_ZONE):
    utc = stored_utc(value)
    return datetime.fromisoformat(utc).astimezone(zone(tz_name)).date() if utc else None


# ---------- request context ----------
request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar('meet_request_id', default=None)


def safe_text(text: str, limit: int = 120) -> dict:
    """Minimised representation of user free text for the audit log: e-mails and digits are masked, length is
    capped, plus a short hash to correlate repeats. The original text is not stored."""
    raw = str(text or '')
    masked = re.sub(r'[\w.+-]+@[\w-]+\.[\w.]+', '[email]', raw)
    masked = re.sub(r'\d', '#', masked)
    masked = ' '.join(masked.split())
    return {'masked': masked[:limit] + ('…' if len(masked) > limit else ''), 'length': len(raw),
            'sha256': hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}


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
                migrations.apply(connection)
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


@contextmanager
def write_tx():
    """Serialised write transaction (BEGIN IMMEDIATE): check-then-write sequences such as confirm are atomic
    across threads and processes. Commits on success, rolls back on any exception."""
    connection = _connect()
    connection.isolation_level = None
    try:
        connection.execute('BEGIN IMMEDIATE')
        try:
            yield connection
        except BaseException:
            connection.execute('ROLLBACK')
            raise
        connection.execute('COMMIT')
    finally:
        connection.close()


def reset_cache():
    _initialized.clear()


AUDIT_FIELDS = ('object_type', 'object_id', 'result', 'source_ids', 'confirmation_id', 'model', 'error_code', 'department_id')


def audit(connection, user_id, action, **details):
    """Backward compatible: audit(connection, user_id, action, key=value...). The structured keys
    object_type, object_id, result ('ok'|'denied'|'error'|'cancelled'|...), source_ids (['F12','U3',...]),
    confirmation_id, model, error_code go to their own columns; everything else stays in `details`.
    The current HTTP request id is attached automatically. Never put titles, full prompts or tokens here."""
    columns = {k: details.pop(k) for k in AUDIT_FIELDS if k in details}
    sources = columns.get('source_ids') or []
    department = columns.get('department_id')
    if department is None and user_id is not None:
        actor = connection.execute('SELECT department_id FROM users WHERE id=?', (user_id,)).fetchone()
        department = actor[0] if actor else None
    connection.execute(
        'INSERT INTO audit(at,user_id,action,details,request_id,object_type,object_id,result,source_ids,confirmation_id,'
        'model,error_code,department_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (now(), user_id, action, json.dumps(details, ensure_ascii=False, default=str), request_id_var.get(),
         columns.get('object_type'), None if columns.get('object_id') is None else str(columns['object_id']),
         columns.get('result') or 'ok', json.dumps([str(s) for s in sources]), columns.get('confirmation_id'),
         columns.get('model'), columns.get('error_code'), department))


def audit_independent(user_id, action, **details):
    """Audit row in its own connection and transaction, so it survives a rollback of the caller's work.
    Call it while this thread holds no open write transaction (e.g. from the error handler)."""
    connection = _connect()
    try:
        with connection:
            audit(connection, user_id, action, **details)
    finally:
        connection.close()


def audit_out(row) -> dict:
    return {'id': row['id'], 'at': row['at'], 'user_id': row['user_id'], 'action': row['action'],
            'request_id': row['request_id'], 'object_type': row['object_type'], 'object_id': row['object_id'],
            'result': row['result'], 'source_ids': json.loads(row['source_ids'] or '[]'),
            'confirmation_id': row['confirmation_id'], 'model': row['model'], 'error_code': row['error_code'],
            'department_id': row['department_id'], 'details': json.loads(row['details'] or '{}')}


# ---------- access ----------

def can_read_meeting(connection, user_id: int, meeting_id: int, *, model=False) -> bool:
    from meetings.access import object_decision
    return object_decision(connection, user_id, 'meeting', meeting_id, 'model.read' if model else None).allowed


def can_read_document(connection, user_id: int, document_id: int, *, model=False) -> bool:
    from meetings.access import object_decision
    return object_decision(connection, user_id, 'document', document_id, 'model.read' if model else None).allowed


def accessible_document_ids(connection, user_id: int, *, model=False) -> list[int]:
    from meetings.access import predicate
    sql, params = predicate(connection, user_id, 'document', 'd', model=model)
    return [r[0] for r in connection.execute('SELECT d.id FROM documents d WHERE ' + sql + ' ORDER BY d.id', params)]


def accessible_meeting_ids(connection, user_id: int, *, model=False) -> list[int]:
    from meetings.access import predicate
    sql, params = predicate(connection, user_id, 'meeting', 'm', model=model)
    return [r[0] for r in connection.execute('SELECT m.id FROM meetings m WHERE ' + sql + ' ORDER BY m.id', params)]


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
            'shared_with': shared, 'fragments_count': count, 'created_at': row['created_at'],
            'department_id': row['department_id'], 'confidentiality': row['confidentiality'], 'doc_type': row['doc_type'],
            'authored_at': row['authored_at'], 'version': row['version'], 'valid_until': row['valid_until'], 'supersedes_id': row['supersedes_id']}


def fragment_out(row, title=None) -> dict:
    return {'id': f"F{row['id']}", 'document_id': row['document_id'], 'document_title': title or row['title'],
            'idx': row['idx'], 'location': row['location'], 'text': row['text']}


def meeting_out(connection, row) -> dict:
    access = [r[0] for r in connection.execute('SELECT user_id FROM meeting_access WHERE meeting_id=?', (row['id'],))]
    return {'id': row['id'], 'title': row['title'], 'topic': row['topic'], 'scheduled_at': stored_utc(row['scheduled_at']),
            'timezone': DISPLAY_ZONE, 'participants': json.loads(row['participants']), 'owner_id': row['owner_id'],
            'owner_name': user_name(connection, row['owner_id']), 'access_user_ids': access,
            'speaker_map': json.loads(row['speaker_map']), 'followup_of': row['followup_of'],
            'created_at': row['created_at'], 'version': row['version'],
            'department_id': row['department_id'], 'confidentiality': row['confidentiality']}


def utterance_out(row, speaker_map: dict) -> dict:
    label = row['speaker_label']
    return {'id': f"U{row['id']}", 'meeting_id': row['meeting_id'], 'idx': row['idx'], 'speaker_label': label,
            'speaker': speaker_map.get(label) or label, 'text': row['text'], 'original_text': row['original_text'],
            'edited': bool(row['edited']), 'source': row['source'], 'start_ms': row['start_ms']}


def item_out(connection, row) -> dict:
    from meetings.connectors.entities import mentions
    return {'id': row['id'], 'kind': row['kind'], 'text': row['text'], 'outcome': row['outcome'],
            'assignee': row['assignee'], 'assignee_status': row['assignee_status'], 'due': row['due'],
            'due_text': row['due_text'], 'due_status': row['due_status'], 'quotes': json.loads(row['quotes']),
            'confirmed': row['confirmed_at'] is not None, 'confirmed_by': user_name(connection, row['confirmed_by']),
            'confirmed_at': row['confirmed_at'], 'task_id': row['task_id'], 'edited': bool(row['edited']),
            'linked_entities':mentions(row['text']+' '+row['quotes'])}


def task_out(connection, row) -> dict:
    meeting = connection.execute('SELECT title FROM meetings WHERE id=?', (row['meeting_id'],)).fetchone()
    crm = connection.execute("SELECT status FROM integration_outbox WHERE connector='bitrix24-mock' AND action='task.create' AND object_type='task' AND object_id=?",(row['id'],)).fetchone()
    return {'id': row['id'], 'text': row['text'], 'assignee': row['assignee'], 'assignee_status': row['assignee_status'],
            'due': row['due'], 'due_text': row['due_text'], 'due_status': row['due_status'], 'status': row['status'],
            'meeting_id': row['meeting_id'], 'meeting_title': meeting['title'] if meeting else None,
            'protocol_item_id': row['protocol_item_id'], 'source_quote': json.loads(row['source_quote']),
            'confirmed_by': user_name(connection, row['confirmed_by']), 'confirmed_at': row['confirmed_at'],
            'created_at': row['created_at'], 'updated_at': row['updated_at'], 'version': row['version'],
            'priority':row['priority'], 'assignee_user_id':row['assignee_user_id'], 'department_id':row['department_id'],
            'linked_entities':json.loads(row['linked_entities']), 'external_ref':row['external_ref'],
            'crm_status':crm['status'] if crm else None}


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
            'summary': json.loads(head['summary'] or '[]'), 'warnings': json.loads(head['warnings']), 'generated_at': head['generated_at'], 'model': head['model']}


def prep(connection, meeting_id) -> dict | None:
    row = connection.execute('SELECT data FROM preps WHERE meeting_id=?', (meeting_id,)).fetchone()
    return json.loads(row['data']) if row else None
