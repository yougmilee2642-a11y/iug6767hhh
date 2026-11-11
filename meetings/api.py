"""HTTP API for CallWise Meetings. Access is checked on the server for every read, search, download
and before building any model context. Inaccessible resources answer 404 (existence is not revealed)."""
import hashlib
import importlib
import importlib.util
import os
import sqlite3
import json
import re
import uuid
from datetime import date
from pathlib import Path
from urllib.parse import quote as urlquote

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from meetings import confirmations
from meetings import documents as docs
from meetings import extract, store
from meetings.auth import (COOKIE, ROLE_LABELS, TTL, MeetError, capabilities, check_password, current_user,
                           MeetRoute, ensure_demo_users, make_cookie, require)
from meetings.auth import has_capability as auth_has
from meetings.llm import get_llm
from providers.local_settings import LocalAIError

ROOT = Path(__file__).resolve().parents[1]
SPEAKER_LINE = re.compile(r'^\s*(?:\[?(\d{1,2}):(\d{2})(?::(\d{2}))?\]?\s*[-–—]?\s*)?'
                          r'([A-Za-zА-Яа-яЁё][\w .\-ёЁ]{0,40}?)\s*:\s*(.+)$')


def not_found():
    return MeetError(404, 'not_found', 'Не найдено или нет доступа.')


def denied(user, object_type: str, object_id, action: str):
    """404 for a foreign or missing object. The denial is audited (type and id only — never the title)."""
    return MeetError(404, 'not_found', 'Не найдено или нет доступа.',
                     audit={'user_id': user['id'], 'action': 'access_denied', 'object_type': object_type,
                            'object_id': object_id, 'result': 'denied', 'error_code': 'not_found', 'attempted': action})


def time_error(error: store.TimeError):
    return MeetError(422, error.code, error.detail)


def model_error(error: LocalAIError):
    return MeetError(503, f'model_{error.code}', f'{error} Данные сохранены, можно повторить.')


# Routers of other track-3 modules are registered here (not in app.py). A module that is not delivered yet is
# skipped; a delivered module that fails to import is a real error and is not hidden.
OPTIONAL_ROUTERS = ('meetings.knowledge', 'meetings.management')


def _optional_routers():
    found = []
    for package in OPTIONAL_ROUTERS:
        if importlib.util.find_spec(package) is None or importlib.util.find_spec(package + '.api') is None:
            continue
        found.append(importlib.import_module(package + '.api').router())
    return found


def _write_denial(details: dict, request_id: str | None):
    token = store.request_id_var.set(request_id)
    try:
        store.audit_independent(details.pop('user_id', None), details.pop('action', 'access_denied'), **details)
    finally:
        store.request_id_var.reset(token)


def install(app):
    if os.getenv('MEETINGS_DEMO_USERS', 'true').lower() == 'true':
        ensure_demo_users()

    @app.exception_handler(MeetError)
    async def _handle(_request, error: MeetError):
        if error.audit:
            details = dict(error.audit)
            try:  # own transaction (the request's one is rolled back), off the event loop
                await run_in_threadpool(_write_denial, details, store.request_id_var.get())
            except Exception:  # noqa: BLE001 - never turn a clean 403/404 into a 500
                pass
        return JSONResponse({'detail': error.detail, 'code': error.code}, status_code=error.status)

    @app.middleware('http')
    async def _request_id(request: Request, call_next):
        if not request.url.path.startswith('/api/meet'):
            return await call_next(request)
        incoming = request.headers.get('x-request-id', '')
        request_id = incoming if re.fullmatch(r'[A-Za-z0-9._-]{8,64}', incoming) else uuid.uuid4().hex
        token = store.request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            store.request_id_var.reset(token)
        response.headers['X-Request-ID'] = request_id
        return response

    app.include_router(router())
    from meetings.calendar.api import router as calendar_router
    from meetings.feedback import router as feedback_router
    app.include_router(calendar_router())
    app.include_router(feedback_router())
    for extra in _optional_routers():
        app.include_router(extra)


# ---------- payloads ----------
class Login(BaseModel):
    login: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=200)


class MeetingIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    topic: str = Field(default='', max_length=2000)
    scheduled_at: str | None = Field(default=None, max_length=40)
    timezone: str | None = Field(default=None, max_length=60)  # required when scheduled_at has no offset
    participants: list[str] = Field(default_factory=list, max_length=50)
    access_user_ids: list[int] = Field(default_factory=list, max_length=50)


class MeetingPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    topic: str | None = Field(default=None, max_length=2000)
    scheduled_at: str | None = Field(default=None, max_length=40)
    timezone: str | None = Field(default=None, max_length=60)
    participants: list[str] | None = Field(default=None, max_length=50)
    access_user_ids: list[int] | None = Field(default=None, max_length=50)


class AttachIn(BaseModel):
    document_id: int


class TranscriptIn(BaseModel):
    text: str = Field(max_length=300_000)


class UtteranceIn(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    speaker_label: str = Field(default='Говорящий ?', max_length=60)
    source: str = Field(default='manual', pattern='^(voice|manual)$')
    start_ms: int | None = Field(default=None, ge=0, le=7 * 24 * 3600 * 1000)


class UtterancePatch(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=5000)
    speaker_label: str | None = Field(default=None, min_length=1, max_length=60)


class SpeakersIn(BaseModel):
    speaker_map: dict[str, str]


class ItemIn(BaseModel):
    id: int | None = None
    kind: str = Field(pattern='^(decision|proposal|task|open_question|risk)$')
    text: str = Field(min_length=1, max_length=1000)
    outcome: str | None = Field(default=None, pattern='^(accepted|rejected|discussed)$')
    assignee: str | None = Field(default=None, max_length=120)
    due: str | None = Field(default=None, max_length=10)
    due_text: str | None = Field(default=None, max_length=120)
    quotes: list[dict] | None = None


class ProtocolIn(BaseModel):
    items: list[ItemIn] = Field(max_length=300)


class ConfirmIn(BaseModel):
    item_ids: list[int] = Field(min_length=1, max_length=300)


class TaskPatch(BaseModel):
    status: str | None = Field(default=None, pattern='^(open|in_progress|done)$')
    assignee: str | None = Field(default=None, max_length=120)
    due: str | None = Field(default=None, max_length=10)


class TaskPreviewIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    changes: TaskPatch


class ConfirmTokenIn(BaseModel):
    """Confirm carries only the token and an idempotency key — never a payload that could be swapped."""
    model_config = ConfigDict(extra='forbid')
    confirmation_id: str = Field(min_length=8, max_length=80)
    idempotency_key: str = Field(min_length=8, max_length=80, pattern=r'^[A-Za-z0-9._:-]+$')


class NextAgendaIn(BaseModel):
    create_meeting: bool = False


# ---------- helpers ----------
def _sid(value: str, prefix: str) -> int:
    match = re.fullmatch(prefix + r'?(\d+)', str(value).strip().upper())
    if not match:
        raise not_found()
    return int(match[1])


def _meeting(connection, user, meeting_id, capability: str | None = None, action: str = 'meeting.read'):
    """ACL first (foreign → 404, audited), then the role capability (visible but not allowed → 403, audited)."""
    if not store.can_read_meeting(connection, user['id'], meeting_id):
        raise denied(user, 'meeting', meeting_id, action)
    if capability:
        require(user, capability, 'meeting', meeting_id, action)
    return connection.execute('SELECT * FROM meetings WHERE id=?', (meeting_id,)).fetchone()


def _document(connection, user, document_id, action='document.read'):
    if not store.can_read_document(connection, user['id'], document_id):
        raise denied(user, 'document', document_id, action)


def _meeting_date(row) -> date:
    """Calendar date of the meeting in Europe/Minsk (not the server zone)."""
    return store.local_date(row['scheduled_at']) or store.local_date(store.now())


def _scheduled(value, tz_name):
    if value in (None, ''):
        return None
    try:
        return store.iso_utc(store.parse_aware(value, tz_name))
    except store.TimeError as error:
        raise time_error(error) from None


def _valid_users(connection, ids):
    known = {r[0] for r in connection.execute('SELECT id FROM users')}
    return [i for i in dict.fromkeys(ids) if i in known]


def _iso_date(value):
    if value in (None, ''):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise MeetError(422, 'invalid_date', 'Срок должен быть датой в формате ГГГГ-ММ-ДД.') from None


def _meeting_documents(connection, user, meeting_id):
    rows = connection.execute('SELECT d.* FROM documents d JOIN meeting_documents md ON md.document_id=d.id '
                              'WHERE md.meeting_id=? ORDER BY d.id', (meeting_id,)).fetchall()
    visible = [r for r in rows if store.can_read_document(connection, user['id'], r['id'])]
    return visible, len(rows) - len(visible)


def _full_meeting(connection, user, row):
    visible, hidden = _meeting_documents(connection, user, row['id'])
    tasks = [store.task_out(connection, r) for r in connection.execute(
        'SELECT * FROM tasks WHERE meeting_id=? ORDER BY id', (row['id'],))]
    prep = store.prep(connection, row['id'])
    if prep:
        prep['meeting_id'] = row['id']
    return {'meeting': store.meeting_out(connection, row),
            'documents': [store.document_out(connection, d) for d in visible], 'hidden_documents': hidden,
            'utterances': store.utterances(connection, row['id']), 'prep': _visible_prep(connection, user, prep),
            'protocol': store.protocol(connection, row['id']), 'tasks': tasks}


def _visible_prep(connection, user, prep):
    """A saved briefing is derived from documents. Show it only within the viewer's own document access:
    claims citing a document the viewer cannot read are removed, model-written gaps are hidden then."""
    if not prep:
        return prep
    readable = {}

    def allowed(claim):
        for citation in claim.get('citations') or []:
            document_id = citation.get('document_id')
            if document_id is None:
                try:
                    fragment = connection.execute('SELECT document_id FROM fragments WHERE id=?',
                                                  (_sid(citation.get('fragment_id', ''), 'F'),)).fetchone()
                except MeetError:
                    return False
                document_id = fragment['document_id'] if fragment else None
            if document_id is None:
                return False
            if document_id not in readable:
                readable[document_id] = store.can_read_document(connection, user['id'], document_id)
            if not readable[document_id]:
                return False
        return True

    result = dict(prep)
    hidden = 0
    for key in ('brief', 'agenda', 'questions'):
        kept = [c for c in prep.get(key) or [] if allowed(c)]
        hidden += len(prep.get(key) or []) - len(kept)
        result[key] = kept
    if hidden:
        result['gaps'] = [f'Скрыто пунктов справки: {hidden} — они опираются на документы, к которым у вас нет доступа.']
        result['restricted'] = True
    # Open tasks are never taken from the stored copy: recomputed for THIS viewer from live data.
    row = connection.execute('SELECT * FROM meetings WHERE id=?', (prep.get('meeting_id') or 0,)).fetchone() \
        if prep.get('meeting_id') else None
    if row is not None:
        result.update(_open_task_block(connection, user, row))
    return result


def _owned_object(connection, user_id, object_type, object_id) -> bool:
    """Is the audited object (or its parent meeting/document) owned by user_id? Unknown → False."""
    raw = str(object_id or '')
    try:
        if object_type == 'meeting':
            row = connection.execute('SELECT owner_id FROM meetings WHERE id=?', (int(raw),)).fetchone()
        elif object_type == 'document':
            row = connection.execute('SELECT owner_id FROM documents WHERE id=?', (int(raw),)).fetchone()
        elif object_type == 'fragment':
            row = connection.execute('SELECT d.owner_id FROM fragments f JOIN documents d ON d.id=f.document_id '
                                     'WHERE f.id=?', (_sid(raw, 'F'),)).fetchone()
        elif object_type == 'utterance':
            row = connection.execute('SELECT m.owner_id FROM utterances u JOIN meetings m ON m.id=u.meeting_id '
                                     'WHERE u.id=?', (_sid(raw, 'U'),)).fetchone()
        elif object_type in ('task', 'protocol_item'):
            table = 'tasks' if object_type == 'task' else 'protocol_items'
            row = connection.execute(f'SELECT m.owner_id FROM {table} t JOIN meetings m ON m.id=t.meeting_id '
                                     'WHERE t.id=?', (int(raw),)).fetchone()
        else:
            return False
    except (ValueError, MeetError):
        return False
    return row is not None and row[0] == user_id


def _user_out(user: dict) -> dict:
    access_role = user.get('access_role') or 'reader'
    return {'id': user['id'], 'login': user['login'], 'name': user['name'], 'role': user['role'],
            'access_role': access_role, 'capabilities': capabilities({'access_role': access_role})}


def _related_meetings(connection, user, row, depth=5) -> list:
    """Previous meetings linked through `followup_of`, nearest first, only those this user can read."""
    result, seen, current = [], {row['id']}, row['followup_of']
    while current and current not in seen and len(seen) <= depth:
        seen.add(current)
        previous = connection.execute('SELECT * FROM meetings WHERE id=?', (current,)).fetchone()
        if previous is None:
            break
        if store.can_read_meeting(connection, user['id'], previous['id']):
            result.append(previous)
        current = previous['followup_of']
    return result


def task_source(connection, task: dict) -> dict:
    meeting = connection.execute('SELECT scheduled_at, created_at FROM meetings WHERE id=?', (task['meeting_id'],)).fetchone()
    source_at = (store.stored_utc(meeting['scheduled_at']) or meeting['created_at']) if meeting else task['created_at']
    return {'kind': 'task', 'id': f"T{task['id']}", 'title': task['text'], 'source_at': source_at,
            'quote': (task.get('source_quote') or {}).get('text'), 'locator': (task.get('source_quote') or {}).get('utterance_id')}


def _open_task_block(connection, user, row) -> dict:
    """§7.2.1: not-done tasks of accessible linked previous meetings, kept apart from document facts,
    each with its own source, plus deterministic follow-up questions (no model involved)."""
    open_tasks = []
    for previous in _related_meetings(connection, user, row):
        for task_row in connection.execute("SELECT * FROM tasks WHERE meeting_id=? AND status!='done' "
                                           "ORDER BY COALESCE(due,'9999'), id", (previous['id'],)):
            task = store.task_out(connection, task_row)
            task['source'] = task_source(connection, task)
            open_tasks.append(task)
    questions = []
    for task in open_tasks:
        owner = task['assignee'] or 'ответственный не назван'
        due = task['due'] or task['due_text'] or 'срок не назван'
        questions.append({'text': f"Каков статус поручения «{task['text']}» ({owner}, {due})?",
                          'task_id': task['id'], 'sources': [task['source']]})
    return {'open_tasks': open_tasks, 'task_questions': questions}


def parse_transcript(text: str) -> list[dict]:
    result = []
    for line in text.replace('\r\n', '\n').split('\n'):
        line = line.strip()
        if not line:
            continue
        match = SPEAKER_LINE.match(line)
        if match and len(match[4].split()) <= 4:
            start = None
            if match[1]:
                minutes, seconds, extra = int(match[1]), int(match[2]), match[3]
                start = ((minutes * 3600 + seconds * 60 + int(extra)) if extra else (minutes * 60 + seconds)) * 1000
            result.append({'speaker_label': match[4].strip(), 'text': match[5].strip(), 'start_ms': start})
        elif result:
            result[-1]['text'] += ' ' + line
        else:
            result.append({'speaker_label': 'Говорящий ?', 'text': line, 'start_ms': None})
    return result


def router():
    api = APIRouter(route_class=MeetRoute)

    @api.get('/meetings', include_in_schema=False)
    def page():
        return FileResponse(ROOT / 'static' / 'meetings.html')

    # ----- auth -----
    @api.post('/api/meet/login')
    def login(payload: Login, request: Request):
        with store.db() as connection:
            row = connection.execute('SELECT * FROM users WHERE login=?', (payload.login.strip().lower(),)).fetchone()
            if not row or not check_password(payload.password, row['password_hash']):
                store.audit(connection, None, 'login_failed', login=payload.login[:50], result='denied',
                            error_code='bad_credentials')
                raise MeetError(401, 'bad_credentials', 'Неверный логин или пароль.')
            store.audit(connection, row['id'], 'login')
        response = JSONResponse({'user': _user_out(dict(row))})
        response.set_cookie(COOKIE, make_cookie(row['id']), max_age=TTL, httponly=True, samesite='strict',
                            secure=request.url.scheme == 'https')
        return response

    @api.post('/api/meet/logout')
    def logout():
        response = JSONResponse({'ok': True})
        response.delete_cookie(COOKIE)
        return response

    @api.get('/api/meet/me')
    def me(request: Request):
        user = _user_out(current_user(request))
        return {'user': user, 'capabilities': user['capabilities'],
                'role': {'key': user['access_role'], 'label': ROLE_LABELS.get(user['access_role'], '')},
                'timezone': store.DISPLAY_ZONE}

    @api.get('/api/meet/users')
    def users(request: Request):
        current_user(request)
        with store.db() as connection:
            return {'users': [dict(r) for r in connection.execute(
                'SELECT id,login,name,role,access_role FROM users ORDER BY id')]}

    @api.get('/api/meet/audit')
    def audit_log(request: Request, limit: int = 50, scope: str = 'mine'):
        """Audit for the manager role. scope=mine — own actions; scope=my_objects — denied attempts of other
        users on meetings/documents (and their fragments, utterances, tasks) that this user OWNS.
        Ids and codes only — no titles or content."""
        user = current_user(request)
        require(user, 'audit.read', action='audit.read')
        if scope not in ('mine', 'my_objects'):
            raise MeetError(422, 'invalid_scope', 'scope: mine или my_objects.')
        limit = max(1, min(limit, 200))
        with store.db() as connection:
            if scope == 'mine':
                rows = connection.execute('SELECT * FROM audit WHERE user_id=? ORDER BY id DESC LIMIT ?', (user['id'], limit))
                return {'events': [store.audit_out(r) for r in rows], 'scope': scope}
            events = []
            for row in connection.execute("SELECT * FROM audit WHERE action='access_denied' AND result='denied' "
                                          "AND (user_id IS NULL OR user_id!=?) ORDER BY id DESC LIMIT 2000", (user['id'],)):
                if _owned_object(connection, user['id'], row['object_type'], row['object_id']):
                    events.append(store.audit_out(row))
                    if len(events) >= limit:
                        break
            return {'events': events, 'scope': scope}

    # ----- documents -----
    @api.post('/api/meet/documents')
    async def upload(request: Request, file: UploadFile = File(...), meeting_id: int | None = Form(default=None),
                     share_with: str = Form(default=''), title: str = Form(default='')):
        user = current_user(request)
        require(user, 'documents.upload', action='document.upload')
        share = [int(v) for v in re.findall(r'\d+', share_with)]
        if share:
            require(user, 'documents.share', action='document.share')
        data = await file.read(docs.MAX_BYTES + 1)
        filename = Path(file.filename or 'document.txt').name[:200]
        try:
            kind, fragments = docs.fragments(filename, data)
        except docs.DocumentError as error:
            raise MeetError(422, 'bad_document', str(error)) from None
        with store.db() as connection:
            if meeting_id is not None:
                _meeting(connection, user, meeting_id, 'meetings.edit', 'meeting.attach_document')
            cursor = connection.execute(
                'INSERT INTO documents(owner_id,title,filename,kind,content,sha256,created_at) VALUES (?,?,?,?,?,?,?)',
                (user['id'], (title.strip() or filename.rsplit('.', 1)[0])[:200], filename, kind, data,
                 hashlib.sha256(data).hexdigest(), store.now()))
            document_id = cursor.lastrowid
            connection.executemany('INSERT INTO fragments(document_id,idx,location,text) VALUES (?,?,?,?)',
                                   [(document_id, f['idx'], f['location'], f['text']) for f in fragments])
            for user_id in _valid_users(connection, share):
                if user_id != user['id']:
                    connection.execute('INSERT OR IGNORE INTO document_access VALUES (?,?)', (document_id, user_id))
            if meeting_id is not None:
                connection.execute('INSERT OR IGNORE INTO meeting_documents VALUES (?,?)', (meeting_id, document_id))
            store.audit(connection, user['id'], 'document_upload', document_id=document_id, filename=filename,
                        object_type='document', object_id=document_id)
            row = connection.execute('SELECT * FROM documents WHERE id=?', (document_id,)).fetchone()
            return {'document': store.document_out(connection, row)}

    @api.get('/api/meet/documents')
    def list_documents(request: Request):
        user = current_user(request)
        with store.db() as connection:
            ids = store.accessible_document_ids(connection, user['id'])
            rows = [connection.execute('SELECT * FROM documents WHERE id=?', (i,)).fetchone() for i in ids]
            return {'documents': [store.document_out(connection, r) for r in rows]}

    @api.get('/api/meet/documents/{document_id}')
    def get_document(document_id: int, request: Request):
        user = current_user(request)
        with store.db() as connection:
            _document(connection, user, document_id)
            row = connection.execute('SELECT * FROM documents WHERE id=?', (document_id,)).fetchone()
            fragments = [store.fragment_out(f, row['title']) for f in connection.execute(
                'SELECT * FROM fragments WHERE document_id=? ORDER BY idx', (document_id,))]
            return {'document': store.document_out(connection, row), 'fragments': fragments}

    @api.get('/api/meet/documents/{document_id}/download')
    def download(document_id: int, request: Request):
        user = current_user(request)
        with store.db() as connection:
            _document(connection, user, document_id, 'document.download')
            row = connection.execute('SELECT filename,kind,content FROM documents WHERE id=?', (document_id,)).fetchone()
            store.audit(connection, user['id'], 'document_download', document_id=document_id,
                        object_type='document', object_id=document_id)
        media = {'txt': 'text/plain; charset=utf-8', 'pdf': 'application/pdf',
                 'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}[row['kind']]
        return Response(row['content'], media_type=media, headers={
            'Content-Disposition': f"attachment; filename*=UTF-8''{urlquote(row['filename'])}"})

    @api.get('/api/meet/fragments/{fragment_id}')
    def fragment(fragment_id: str, request: Request):
        user = current_user(request)
        number = _sid(fragment_id, 'F')
        with store.db() as connection:
            row = connection.execute('SELECT f.*, d.title FROM fragments f JOIN documents d ON d.id=f.document_id '
                                     'WHERE f.id=?', (number,)).fetchone()
            if not row or not store.can_read_document(connection, user['id'], row['document_id']):
                raise denied(user, 'fragment', f'F{number}', 'fragment.read')
            return {'fragment': store.fragment_out(row)}

    @api.get('/api/meet/search')
    def search(request: Request, q: str = ''):
        user = current_user(request)
        terms = [t for t in extract.tu.norm(q).split() if len(t) > 1]
        if not terms:
            return {'results': []}
        with store.db() as connection:
            ids = store.accessible_document_ids(connection, user['id'])
            results = []
            for doc_id in ids:
                for row in connection.execute('SELECT f.*, d.title FROM fragments f JOIN documents d ON d.id=f.document_id '
                                              'WHERE f.document_id=? ORDER BY f.idx', (doc_id,)):
                    text = extract.tu.norm(row['text'])
                    stems = [extract.tu.stem(t) for t in terms]
                    if all(s in text for s in stems):
                        position = row['text'].lower().find(stems[0])
                        start = max(0, position - 80)
                        results.append({**store.fragment_out(row), 'snippet': row['text'][start:start + 240]})
            store.audit(connection, user['id'], 'search', query=store.safe_text(q, 100), results=len(results),
                        source_ids=[r['id'] for r in results[:50]])
            return {'results': results[:50]}

    # ----- meetings -----
    @api.post('/api/meet/meetings')
    def create_meeting(payload: MeetingIn, request: Request):
        user = current_user(request)
        require(user, 'meetings.create', action='meeting.create')
        if payload.access_user_ids:
            require(user, 'meetings.share', action='meeting.share')
        scheduled = _scheduled(payload.scheduled_at, payload.timezone)
        with store.db() as connection:
            cursor = connection.execute(
                'INSERT INTO meetings(owner_id,title,topic,scheduled_at,participants,created_at) VALUES (?,?,?,?,?,?)',
                (user['id'], payload.title.strip(), payload.topic.strip(), scheduled,
                 json.dumps([p.strip() for p in payload.participants if p.strip()], ensure_ascii=False), store.now()))
            for user_id in _valid_users(connection, payload.access_user_ids):
                if user_id != user['id']:
                    connection.execute('INSERT OR IGNORE INTO meeting_access VALUES (?,?)', (cursor.lastrowid, user_id))
            store.audit(connection, user['id'], 'meeting_create', object_type='meeting', object_id=cursor.lastrowid)
            row = connection.execute('SELECT * FROM meetings WHERE id=?', (cursor.lastrowid,)).fetchone()
            return {'meeting': store.meeting_out(connection, row)}

    @api.get('/api/meet/meetings')
    def list_meetings(request: Request):
        user = current_user(request)
        with store.db() as connection:
            rows = [connection.execute('SELECT * FROM meetings WHERE id=?', (i,)).fetchone()
                    for i in store.accessible_meeting_ids(connection, user['id'])]
            return {'meetings': [store.meeting_out(connection, r) for r in reversed(rows)]}

    @api.get('/api/meet/meetings/{meeting_id}')
    def get_meeting(meeting_id: int, request: Request):
        user = current_user(request)
        with store.db() as connection:
            return _full_meeting(connection, user, _meeting(connection, user, meeting_id))

    @api.patch('/api/meet/meetings/{meeting_id}')
    def patch_meeting(meeting_id: int, payload: MeetingPatch, request: Request):
        user = current_user(request)
        with store.db() as connection:
            row = _meeting(connection, user, meeting_id, 'meetings.edit', 'meeting.edit')
            values = payload.model_dump(exclude_unset=True)
            tz_name = values.pop('timezone', None)
            if 'access_user_ids' in values:
                require(user, 'meetings.share', 'meeting', meeting_id, 'meeting.share')
                if row['owner_id'] != user['id']:  # a shared (non-owned) meeting can never be re-shared
                    raise MeetError(403, 'owner_only', 'Доступ к встрече может менять только её владелец.',
                                    audit={'user_id': user['id'], 'action': 'access_denied', 'object_type': 'meeting',
                                           'object_id': meeting_id, 'result': 'denied', 'error_code': 'owner_only',
                                           'attempted': 'meeting.share'})
                before = sorted(r[0] for r in connection.execute(
                    'SELECT user_id FROM meeting_access WHERE meeting_id=?', (meeting_id,)))
                connection.execute('DELETE FROM meeting_access WHERE meeting_id=?', (meeting_id,))
                for user_id in _valid_users(connection, values.pop('access_user_ids') or []):
                    if user_id != row['owner_id']:
                        connection.execute('INSERT INTO meeting_access VALUES (?,?)', (meeting_id, user_id))
                after = sorted(r[0] for r in connection.execute(
                    'SELECT user_id FROM meeting_access WHERE meeting_id=?', (meeting_id,)))
                store.audit(connection, user['id'], 'meeting_access_change', object_type='meeting', object_id=meeting_id,
                            granted=[u for u in after if u not in before], revoked=[u for u in before if u not in after])
            if 'scheduled_at' in values:
                values['scheduled_at'] = _scheduled(values['scheduled_at'], tz_name)
            if 'participants' in values:
                values['participants'] = json.dumps(values['participants'] or [], ensure_ascii=False)
            for key, value in values.items():
                if key not in ('title', 'topic', 'scheduled_at', 'participants'):
                    continue
                connection.execute(f'UPDATE meetings SET {key}=? WHERE id=?', (value, meeting_id))
            if values:
                connection.execute('UPDATE meetings SET version=version+1 WHERE id=?', (meeting_id,))
            return {'meeting': store.meeting_out(connection, _meeting(connection, user, meeting_id))}

    @api.post('/api/meet/meetings/{meeting_id}/documents')
    def attach(meeting_id: int, payload: AttachIn, request: Request):
        user = current_user(request)
        with store.db() as connection:
            _meeting(connection, user, meeting_id, 'meetings.edit', 'meeting.attach_document')
            _document(connection, user, payload.document_id, 'meeting.attach_document')
            connection.execute('INSERT OR IGNORE INTO meeting_documents VALUES (?,?)', (meeting_id, payload.document_id))
            return _full_meeting(connection, user, _meeting(connection, user, meeting_id))

    @api.delete('/api/meet/meetings/{meeting_id}/documents/{document_id}')
    def detach(meeting_id: int, document_id: int, request: Request):
        user = current_user(request)
        with store.db() as connection:
            _meeting(connection, user, meeting_id, 'meetings.edit', 'meeting.detach_document')
            _document(connection, user, document_id, 'meeting.detach_document')
            connection.execute('DELETE FROM meeting_documents WHERE meeting_id=? AND document_id=?', (meeting_id, document_id))
            return _full_meeting(connection, user, _meeting(connection, user, meeting_id))

    @api.post('/api/meet/meetings/{meeting_id}/prepare')
    def prepare(meeting_id: int, request: Request):
        user = current_user(request)
        with store.db() as connection:
            row = _meeting(connection, user, meeting_id, 'prep.generate', 'meeting.prepare')
            visible, _hidden = _meeting_documents(connection, user, meeting_id)
            fragments = []
            for document in visible:  # model context = ONLY documents this user may read
                fragments += [store.fragment_out(f, document['title']) for f in connection.execute(
                    'SELECT * FROM fragments WHERE document_id=? ORDER BY idx', (document['id'],))]
            meeting = store.meeting_out(connection, row)
        llm = get_llm()
        context_ids = [f['id'] for f in fragments]
        try:
            result = extract.prepare(llm, meeting, fragments)
        except LocalAIError as error:
            store.audit_independent(user['id'], 'ai_prepare', object_type='meeting', object_id=meeting_id,
                                    result='error', error_code=f'model_{error.code}', source_ids=context_ids,
                                    model=getattr(llm, 'model', None), stage='draft')
            raise model_error(error) from None
        result['generated_at'] = store.now()
        result['generated_for'] = user['name']
        cited = sorted({c['fragment_id'] for key in ('brief', 'agenda', 'questions')
                        for claim in result.get(key) or [] for c in claim.get('citations') or []})
        with store.db() as connection:
            # Generation takes minutes: access may have been revoked meanwhile. Re-check the meeting, and show
            # only claims whose documents are still readable.
            row = _meeting(connection, user, meeting_id, 'prep.generate', 'meeting.prepare')
            visible = _visible_prep(connection, user, {**result, 'meeting_id': meeting_id})
            # The saved briefing is shared by everyone with access: only an editing role may replace it.
            # A reader gets a personal, unsaved briefing and never overwrites the manager's one.
            saved = auth_has(user, 'meetings.edit')
            if saved:
                connection.execute('INSERT OR REPLACE INTO preps VALUES (?,?,?,?)',
                                   (meeting_id, json.dumps(result, ensure_ascii=False), user['id'], store.now()))
            store.audit(connection, user['id'], 'ai_prepare', object_type='meeting', object_id=meeting_id,
                        result=result.get('status', 'ok'), source_ids=context_ids, model=result.get('model'),
                        stage='result', cited_ids=cited, fragments=len(fragments), saved=saved)
            visible.pop('meeting_id', None)
            return {'prep': {**visible, **_open_task_block(connection, user, row), 'saved': saved}}

    # ----- transcript -----
    @api.put('/api/meet/meetings/{meeting_id}/transcript')
    def put_transcript(meeting_id: int, payload: TranscriptIn, request: Request):
        user = current_user(request)
        lines = parse_transcript(payload.text)
        with store.db() as connection:
            _meeting(connection, user, meeting_id, 'transcript.edit', 'transcript.replace')
            connection.execute('UPDATE utterances SET deleted=1 WHERE meeting_id=?', (meeting_id,))
            connection.executemany(
                'INSERT INTO utterances(meeting_id,idx,speaker_label,text,original_text,source,start_ms) VALUES (?,?,?,?,?,?,?)',
                [(meeting_id, i + 1, u['speaker_label'], u['text'], u['text'], 'manual', u['start_ms'])
                 for i, u in enumerate(lines)])
            store.audit(connection, user['id'], 'transcript_replace', object_type='meeting', object_id=meeting_id,
                        utterances=len(lines))
            return {'utterances': store.utterances(connection, meeting_id)}

    @api.post('/api/meet/meetings/{meeting_id}/utterances')
    def add_utterance(meeting_id: int, payload: UtteranceIn, request: Request):
        user = current_user(request)
        with store.db() as connection:
            _meeting(connection, user, meeting_id, 'transcript.edit', 'transcript.add')
            position = connection.execute('SELECT COALESCE(MAX(idx),0)+1 FROM utterances WHERE meeting_id=?',
                                          (meeting_id,)).fetchone()[0]
            text = payload.text.strip()
            cursor = connection.execute(
                'INSERT INTO utterances(meeting_id,idx,speaker_label,text,original_text,source,start_ms) VALUES (?,?,?,?,?,?,?)',
                (meeting_id, position, payload.speaker_label.strip() or 'Говорящий ?', text, text, payload.source,
                 payload.start_ms))
            row = connection.execute('SELECT * FROM utterances WHERE id=?', (cursor.lastrowid,)).fetchone()
            return {'utterance': store.utterance_out(row, store.speaker_map(connection, meeting_id))}

    def _utterance(connection, user, utterance_id, capability=None, action='utterance.read'):
        number = _sid(utterance_id, 'U')
        row = connection.execute('SELECT * FROM utterances WHERE id=? AND deleted=0', (number,)).fetchone()
        if not row or not store.can_read_meeting(connection, user['id'], row['meeting_id']):
            raise denied(user, 'utterance', f'U{number}', action)
        if capability:
            require(user, capability, 'utterance', f'U{number}', action)
        return row

    @api.get('/api/meet/utterances/{utterance_id}')
    def get_utterance(utterance_id: str, request: Request):
        user = current_user(request)
        with store.db() as connection:
            row = _utterance(connection, user, utterance_id)
            meeting = connection.execute('SELECT title FROM meetings WHERE id=?', (row['meeting_id'],)).fetchone()
            return {'utterance': store.utterance_out(row, store.speaker_map(connection, row['meeting_id'])),
                    'meeting_title': meeting['title']}

    @api.patch('/api/meet/utterances/{utterance_id}')
    def patch_utterance(utterance_id: str, payload: UtterancePatch, request: Request):
        """Source edit of the transcript: an explicit user action (the UI save button); nothing calls it implicitly."""
        user = current_user(request)
        with store.db() as connection:
            row = _utterance(connection, user, utterance_id, 'transcript.edit', 'utterance.edit')
            if payload.text is not None:
                connection.execute('UPDATE utterances SET text=?, edited=1 WHERE id=?', (payload.text.strip(), row['id']))
            if payload.speaker_label is not None:
                connection.execute('UPDATE utterances SET speaker_label=? WHERE id=?', (payload.speaker_label.strip(), row['id']))
            store.audit(connection, user['id'], 'utterance_edit', object_type='utterance', object_id=f"U{row['id']}")
            row = connection.execute('SELECT * FROM utterances WHERE id=?', (row['id'],)).fetchone()
            return {'utterance': store.utterance_out(row, store.speaker_map(connection, row['meeting_id']))}

    @api.delete('/api/meet/utterances/{utterance_id}')
    def delete_utterance(utterance_id: str, request: Request):
        user = current_user(request)
        with store.db() as connection:
            row = _utterance(connection, user, utterance_id, 'transcript.edit', 'utterance.delete')
            connection.execute('UPDATE utterances SET deleted=1 WHERE id=?', (row['id'],))
            store.audit(connection, user['id'], 'utterance_delete', object_type='utterance', object_id=f"U{row['id']}")
            return {'ok': True}

    @api.put('/api/meet/meetings/{meeting_id}/speakers')
    def speakers(meeting_id: int, payload: SpeakersIn, request: Request):
        user = current_user(request)
        mapping = {k.strip()[:60]: v.strip()[:120] for k, v in payload.speaker_map.items() if k.strip() and v.strip()}
        with store.db() as connection:
            _meeting(connection, user, meeting_id, 'transcript.edit', 'transcript.speakers')
            connection.execute('UPDATE meetings SET speaker_map=? WHERE id=?', (json.dumps(mapping, ensure_ascii=False), meeting_id))
            return {'meeting': store.meeting_out(connection, _meeting(connection, user, meeting_id)),
                    'utterances': store.utterances(connection, meeting_id)}

    # ----- protocol -----
    @api.post('/api/meet/meetings/{meeting_id}/protocol/draft')
    def draft(meeting_id: int, request: Request):
        user = current_user(request)
        with store.db() as connection:
            row = _meeting(connection, user, meeting_id, 'protocol.edit', 'protocol.draft')
            utterances = store.utterances(connection, meeting_id)
            participants = json.loads(row['participants'])
            confirmed = [store.item_out(connection, r) for r in connection.execute(
                'SELECT * FROM protocol_items WHERE meeting_id=? AND confirmed_at IS NOT NULL', (meeting_id,))]
        if not utterances:
            raise MeetError(409, 'empty_transcript', 'Сначала добавьте расшифровку встречи.')
        llm = get_llm()
        context_ids = [u['id'] for u in utterances]
        try:
            items, warnings = extract.draft_protocol(llm, utterances, participants, _meeting_date(row))
        except LocalAIError as error:
            store.audit_independent(user['id'], 'ai_protocol_draft', object_type='meeting', object_id=meeting_id,
                                    result='error', error_code=f'model_{error.code}', source_ids=context_ids,
                                    model=getattr(llm, 'model', None), stage='draft')
            raise model_error(error) from None
        # Never duplicate already confirmed items on re-draft.
        fresh = [i for i in items if not any(
            c['kind'] == i['kind'] and (extract.tu.overlap(i['text'], c['text']) >= 0.6 or
                                         {q['utterance_id'] for q in c['quotes']} & {q['utterance_id'] for q in i['quotes']})
            for c in confirmed)]
        summary = extract.summarize(llm, confirmed + fresh, warnings)
        with store.write_tx() as connection:
            # Generation takes minutes: re-check rights, and refuse to store quotes of a transcript that was
            # edited meanwhile (the user's edit wins; nothing is lost, the draft can be requested again).
            _meeting(connection, user, meeting_id, 'protocol.edit', 'protocol.draft')
            current = [(u['id'], u['text'], u['speaker']) for u in store.utterances(connection, meeting_id)]
            if current != [(u['id'], u['text'], u['speaker']) for u in utterances]:
                raise MeetError(409, 'stale_transcript', 'Расшифровку изменили, пока готовился черновик. '
                                                        'Правки сохранены — сформируйте черновик ещё раз.')
            connection.execute('DELETE FROM protocol_items WHERE meeting_id=? AND confirmed_at IS NULL', (meeting_id,))
            connection.execute('INSERT OR REPLACE INTO protocols(meeting_id,warnings,generated_at,model,summary) '
                               'VALUES (?,?,?,?,?)',
                               (meeting_id, json.dumps(warnings, ensure_ascii=False), store.now(),
                                getattr(llm, 'model', None), json.dumps(summary, ensure_ascii=False)))
            base = len(confirmed)
            for position, item in enumerate(fresh, base + 1):
                _insert_item(connection, meeting_id, position, item)
            cited = sorted({q['utterance_id'] for i in fresh for q in i['quotes']})
            store.audit(connection, user['id'], 'protocol_draft', meeting_id=meeting_id, items=len(fresh),
                        object_type='meeting', object_id=meeting_id, source_ids=context_ids,
                        model=getattr(llm, 'model', None), stage='result', cited_ids=cited,
                        kinds={k: sum(1 for i in fresh if i['kind'] == k) for k in extract.KIND_RU},
                        summary_claims=len(summary), warnings=len(warnings))
            return {'protocol': store.protocol(connection, meeting_id)}

    @api.put('/api/meet/meetings/{meeting_id}/protocol')
    def save_protocol(meeting_id: int, payload: ProtocolIn, request: Request):
        user = current_user(request)
        with store.db() as connection:
            _meeting(connection, user, meeting_id, 'protocol.edit', 'protocol.save')
            if not connection.execute('SELECT 1 FROM protocols WHERE meeting_id=?', (meeting_id,)).fetchone():
                connection.execute('INSERT INTO protocols(meeting_id,generated_at) VALUES (?,?)', (meeting_id, store.now()))
            existing = {r['id']: r for r in connection.execute('SELECT * FROM protocol_items WHERE meeting_id=?', (meeting_id,))}
            keep = set()
            for position, item in enumerate(payload.items, 1):
                old = existing.get(item.id) if item.id else None
                if old is not None and old['confirmed_at'] is not None:
                    keep.add(old['id'])  # confirmed items are frozen; edit the task instead
                    connection.execute('UPDATE protocol_items SET position=? WHERE id=?', (position, old['id']))
                    continue
                values = _edited_values(item, old)
                if old is not None:
                    keep.add(old['id'])
                    connection.execute(
                        'UPDATE protocol_items SET position=?,kind=?,text=?,outcome=?,assignee=?,assignee_status=?,due=?,'
                        'due_text=?,due_status=?,edited=? WHERE id=?',
                        (position, values['kind'], values['text'], values['outcome'], values['assignee'],
                         values['assignee_status'], values['due'], values['due_text'], values['due_status'],
                         values['edited'], old['id']))
                else:
                    keep.add(_insert_item(connection, meeting_id, position, {**values, 'quotes': _checked_quotes(
                        connection, meeting_id, item.quotes or [])}))
            for item_id, row in existing.items():
                if item_id not in keep and row['confirmed_at'] is None:
                    connection.execute('DELETE FROM protocol_items WHERE id=?', (item_id,))
            _recheck_summary(connection, meeting_id)
            store.audit(connection, user['id'], 'protocol_save', object_type='meeting', object_id=meeting_id,
                        items=len(payload.items))
            return {'protocol': store.protocol(connection, meeting_id)}

    @api.post('/api/meet/meetings/{meeting_id}/protocol/confirm')
    def confirm(meeting_id: int, payload: ConfirmIn, request: Request):
        user = current_user(request)
        created, already = [], []
        with store.db() as connection:
            _meeting(connection, user, meeting_id, 'protocol.confirm', 'protocol.confirm')
            for item_id in dict.fromkeys(payload.item_ids):
                row = connection.execute('SELECT * FROM protocol_items WHERE id=? AND meeting_id=?', (item_id, meeting_id)).fetchone()
                if not row:
                    raise denied(user, 'protocol_item', item_id, 'protocol.confirm')
                if row['kind'] != 'task':
                    raise MeetError(422, 'not_a_task', 'Подтверждать в задачи можно только поручения.')
                existing = connection.execute('SELECT * FROM tasks WHERE protocol_item_id=?', (item_id,)).fetchone()
                if existing:
                    already.append(store.task_out(connection, existing))
                    continue
                quotes = json.loads(row['quotes'])
                stamp = store.now()
                try:
                    cursor = connection.execute(
                    'INSERT INTO tasks(meeting_id,protocol_item_id,text,assignee,assignee_status,due,due_text,due_status,status,'
                    'source_quote,confirmed_by,confirmed_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (meeting_id, item_id, row['text'], row['assignee'], row['assignee_status'], row['due'], row['due_text'],
                     row['due_status'], 'open', json.dumps(quotes[0] if quotes else {}, ensure_ascii=False), user['id'],
                     stamp, stamp, stamp))
                except sqlite3.IntegrityError:  # concurrent confirmation won the race
                    already.append(store.task_out(connection, connection.execute(
                        'SELECT * FROM tasks WHERE protocol_item_id=?', (item_id,)).fetchone()))
                    continue
                connection.execute('UPDATE protocol_items SET confirmed_by=?, confirmed_at=?, task_id=? WHERE id=?',
                                   (user['id'], stamp, cursor.lastrowid, item_id))
                store.audit(connection, user['id'], 'task_confirmed', item_id=item_id, task_id=cursor.lastrowid,
                            object_type='task', object_id=cursor.lastrowid, stage='confirm',
                            source_ids=[q['utterance_id'] for q in quotes])
                created.append(store.task_out(connection, connection.execute(
                    'SELECT * FROM tasks WHERE id=?', (cursor.lastrowid,)).fetchone()))
            return {'created': created, 'already_confirmed': already, 'protocol': store.protocol(connection, meeting_id)}

    # ----- tasks -----
    @api.get('/api/meet/tasks')
    def tasks(request: Request, status: str = ''):
        user = current_user(request)
        with store.db() as connection:
            ids = store.accessible_meeting_ids(connection, user['id'])
            if not ids:
                return {'tasks': []}
            marks = ','.join('?' * len(ids))
            query = f'SELECT * FROM tasks WHERE meeting_id IN ({marks})'
            args = list(ids)
            if status:
                query += ' AND status=?'
                args.append(status)
            rows = connection.execute(query + ' ORDER BY COALESCE(due,"9999"), id', args)
            return {'tasks': [store.task_out(connection, r) for r in rows]}

    def _task(connection, user, task_id, capability=None, action='task.read'):
        row = connection.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
        if not row or not store.can_read_meeting(connection, user['id'], row['meeting_id']):
            raise denied(user, 'task', task_id, action)
        if capability:
            require(user, capability, 'task', task_id, action)
        return row

    @api.patch('/api/meet/tasks/{task_id}')
    def patch_task(task_id: int, payload: TaskPatch, request: Request):
        """AI-03: direct saving is closed. Same ACL/role checks as before, then a clear pointer to the new flow."""
        user = current_user(request)
        with store.db() as connection:
            _task(connection, user, task_id, 'tasks.change', 'task.patch')
        # The detail is shown to people as is; the route pointer (/tasks/{id}/preview → /confirm) is in the handoff.
        raise MeetError(409, 'confirmation_required',
                        'Изменение задачи сохраняется только после предпросмотра и явного подтверждения. '
                        'Задача не изменена.')

    @api.post('/api/meet/tasks/{task_id}/preview')
    def preview_task(task_id: int, payload: TaskPreviewIn, request: Request):
        user = current_user(request)
        changes = _normalized_task_changes(payload.changes)
        with store.write_tx() as connection:
            row = _task(connection, user, task_id, 'tasks.change', 'task.preview')
            before = {k: row[k] for k in ('status', 'assignee', 'due')}
            after = {**before, **{k: v for k, v in changes.items() if k in before}}
            changed = {k: {'from': before[k], 'to': after[k]} for k in before if before[k] != after[k]}
            if not changed:
                raise MeetError(422, 'no_changes', 'Изменений нет: значения совпадают с текущими.')
            preview = {'task_id': task_id, 'meeting_id': row['meeting_id'], 'text': row['text'], 'before': before,
                       'after': after, 'changes': changed, 'version': row['version']}
            token = confirmations.create(connection, user, 'task.change', 'task', task_id, row['version'],
                                         {'changes': changes, 'preview': preview})
            store.audit(connection, user['id'], 'task_change_preview', object_type='task', object_id=task_id,
                        confirmation_id=token['confirmation_id'], stage='preview', fields=sorted(changed))
            return {**token, 'preview': preview}

    @api.post('/api/meet/tasks/{task_id}/confirm')
    def confirm_task(task_id: int, payload: ConfirmTokenIn, request: Request):
        user = current_user(request)
        with store.write_tx() as connection:
            pending = confirmations.load(connection, user, payload.confirmation_id, 'task.change', 'task', task_id,
                                         payload.idempotency_key)
            if pending.get('already'):
                row = _task(connection, user, task_id)
                return {'task': store.task_out(connection, row), 'already_confirmed': True,
                        'confirmation_id': payload.confirmation_id}
            row = _task(connection, user, task_id, 'tasks.change', 'task.confirm')  # rights re-checked now
            if row['version'] != pending['object_version']:
                raise MeetError(409, 'stale', 'Задача изменилась после предпросмотра. Обновите и проверьте ещё раз.')
            changes = pending['payload']['changes']
            stamp = store.now()
            if 'status' in changes:
                connection.execute('UPDATE tasks SET status=? WHERE id=?', (changes['status'], task_id))
            if 'assignee' in changes:
                connection.execute('UPDATE tasks SET assignee=?, assignee_status=? WHERE id=?',
                                   (changes['assignee'], 'stated' if changes['assignee'] else 'unknown', task_id))
            if 'due' in changes:
                # the spoken wording no longer describes the new date; the source quote keeps the evidence
                connection.execute('UPDATE tasks SET due=?, due_text=NULL, due_status=? WHERE id=?',
                                   (changes['due'], 'stated' if changes['due'] else 'unknown', task_id))
            connection.execute('UPDATE tasks SET updated_at=?, version=version+1 WHERE id=?', (stamp, task_id))
            task = store.task_out(connection, connection.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone())
            confirmations.finish(connection, payload.confirmation_id, payload.idempotency_key, {'task_id': task_id})
            store.audit(connection, user['id'], 'task_update', task_id=task_id, object_type='task', object_id=task_id,
                        confirmation_id=payload.confirmation_id, stage='confirm',
                        **{k: str(v) for k, v in changes.items()})
            return {'task': task, 'already_confirmed': False, 'confirmation_id': payload.confirmation_id}

    @api.post('/api/meet/confirmations/{confirmation_id}/cancel')
    def cancel_confirmation(confirmation_id: str, request: Request):
        """Cancel never touches the target object: only the token is closed (and audited)."""
        user = current_user(request)
        with store.write_tx() as connection:
            return confirmations.cancel(connection, user, confirmation_id)

    @api.post('/api/meet/meetings/{meeting_id}/next-agenda')
    def next_agenda(meeting_id: int, payload: NextAgendaIn, request: Request):
        user = current_user(request)
        with store.db() as connection:
            row = _meeting(connection, user, meeting_id)
            if payload.create_meeting:
                require(user, 'meetings.create', 'meeting', meeting_id, 'meeting.create_followup')
            open_tasks = [store.task_out(connection, r) for r in connection.execute(
                "SELECT * FROM tasks WHERE meeting_id=? AND status!='done' ORDER BY COALESCE(due,'9999'), id", (meeting_id,))]
            agenda = [{'task_id': t['id'], 'text': t['text'], 'assignee': t['assignee'], 'due': t['due'] or t['due_text'],
                       'status': t['status']} for t in open_tasks]
            result = {'agenda': agenda}
            if payload.create_meeting:
                cursor = connection.execute(
                    'INSERT INTO meetings(owner_id,title,topic,participants,followup_of,created_at) VALUES (?,?,?,?,?,?)',
                    (user['id'], f"Контроль поручений: {row['title']}"[:200],
                     f"Статус незавершённых поручений встречи «{row['title']}».", row['participants'], meeting_id, store.now()))
                new_id = cursor.lastrowid
                for access in connection.execute('SELECT user_id FROM meeting_access WHERE meeting_id=?', (meeting_id,)).fetchall():
                    if access[0] != user['id']:
                        connection.execute('INSERT OR IGNORE INTO meeting_access VALUES (?,?)', (new_id, access[0]))
                if row['owner_id'] != user['id']:
                    connection.execute('INSERT OR IGNORE INTO meeting_access VALUES (?,?)', (new_id, row['owner_id']))
                prep = {'status': 'ok', 'brief': [], 'gaps': [] if agenda else ['Незавершённых поручений нет.'],
                        'agenda': [{'text': f"{a['text']} — {a['assignee'] or 'ответственный не назван'}, "
                                            f"срок: {a['due'] or 'не назван'}, статус: {a['status']}", 'citations': []}
                                   for a in agenda],
                        'questions': [], 'generated_at': store.now(), 'model': None, 'source': 'tasks'}
                connection.execute('INSERT INTO preps VALUES (?,?,?,?)', (new_id, json.dumps(prep, ensure_ascii=False), user['id'], store.now()))
                result['meeting'] = store.meeting_out(connection, connection.execute('SELECT * FROM meetings WHERE id=?', (new_id,)).fetchone())
            return result

    return api


def _recheck_summary(connection, meeting_id):
    """After manual protocol edits a summary claim stays «verified» only while every quote it relies on is still
    a quote of some remaining item and those items still support its wording; otherwise it is downgraded to
    «требует уточнения» (it is never silently kept as a verified fact)."""
    head = connection.execute('SELECT summary FROM protocols WHERE meeting_id=?', (meeting_id,)).fetchone()
    claims = json.loads(head['summary'] or '[]') if head else []
    if not claims:
        return
    items = [store.item_out(connection, r) for r in connection.execute(
        'SELECT * FROM protocol_items WHERE meeting_id=?', (meeting_id,))]
    by_quote = {}
    for item in items:
        for quote in item['quotes']:
            by_quote.setdefault(quote['utterance_id'], []).append(item)
    for claim in claims:
        if claim.get('status') != 'verified':
            continue
        supporting = [i for q in claim.get('quotes') or [] for i in by_quote.get(q['utterance_id'], [])]
        missing = [q for q in claim.get('quotes') or [] if q['utterance_id'] not in by_quote]
        support = ' '.join([i['text'] for i in supporting] + [q['text'] for q in claim.get('quotes') or []])
        if missing or not supporting or extract.tu.overlap(claim['text'], ' '.join(i['text'] for i in supporting)) < 0.2 \
                or extract.tu.overlap(claim['text'], support) < 0.34:
            claim['status'] = 'needs_clarification'
            claim['note'] = f'{extract.NEEDS_CLARIFICATION}: пункты протокола изменены после формирования резюме'
    connection.execute('UPDATE protocols SET summary=? WHERE meeting_id=?', (json.dumps(claims, ensure_ascii=False), meeting_id))


def _normalized_task_changes(patch: TaskPatch) -> dict:
    values = patch.model_dump(exclude_unset=True)
    changes = {}
    if values.get('status'):
        changes['status'] = values['status']
    if 'assignee' in values:
        changes['assignee'] = (values['assignee'] or '').strip() or None
    if 'due' in values:
        changes['due'] = _iso_date(values['due'])
    if not changes:
        raise MeetError(422, 'no_changes', 'Укажите хотя бы одно изменение: status, assignee или due.')
    return changes


def _insert_item(connection, meeting_id, position, item) -> int:
    cursor = connection.execute(
        'INSERT INTO protocol_items(meeting_id,position,kind,text,outcome,assignee,assignee_status,due,due_text,due_status,'
        'quotes,edited) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
        (meeting_id, position, item['kind'], item['text'], item.get('outcome'), item.get('assignee'),
         item.get('assignee_status', 'unknown'), item.get('due'), item.get('due_text'), item.get('due_status', 'unknown'),
         json.dumps(item.get('quotes') or [], ensure_ascii=False), int(item.get('edited', 0))))
    return cursor.lastrowid


def _edited_values(item: ItemIn, old) -> dict:
    assignee = (item.assignee or '').strip() or None
    due = _iso_date(item.due)
    due_text = (item.due_text or '').strip() or None
    values = {'kind': item.kind, 'text': item.text.strip(),
              'outcome': (item.outcome or 'discussed') if item.kind == 'proposal' else None,
              'assignee': assignee if item.kind == 'task' else None,
              'assignee_status': 'stated' if assignee and item.kind == 'task' else 'unknown',
              'due': due if item.kind == 'task' else None, 'due_text': due_text if item.kind == 'task' else None,
              'due_status': 'stated' if (due or due_text) and item.kind == 'task' else 'unknown'}
    changed = old is None or any(values[k] != old[k] for k in ('kind', 'text', 'outcome', 'assignee', 'due', 'due_text'))
    values['edited'] = 1 if changed or (old is not None and old['edited']) else 0
    return values


def _checked_quotes(connection, meeting_id, quotes):
    """User-added items may reference utterances; only real, accessible ones are kept, with stored text."""
    result = []
    for quote in quotes[:5]:
        try:
            utterance_id = _sid(quote.get('utterance_id', ''), 'U')
        except MeetError:
            continue
        row = connection.execute('SELECT * FROM utterances WHERE id=? AND meeting_id=? AND deleted=0',
                                 (utterance_id, meeting_id)).fetchone()
        if row:
            mapping = store.speaker_map(connection, meeting_id)
            result.append({'utterance_id': f'U{row["id"]}', 'speaker': mapping.get(row['speaker_label'], row['speaker_label']),
                           'text': row['text'], 'verified': True})
    return result
