"""HTTP API for CallWise Meetings. Access is checked on the server for every read, search, download
and before building any model context. Inaccessible resources answer 404 (existence is not revealed)."""
import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote as urlquote

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from meetings import documents as docs
from meetings import extract, store
from meetings.auth import COOKIE, TTL, MeetError, check_password, current_user, ensure_demo_users, make_cookie
from meetings.llm import get_llm
from providers.local_settings import LocalAIError

ROOT = Path(__file__).resolve().parents[1]
SPEAKER_LINE = re.compile(r'^\s*(?:\[?(\d{1,2}):(\d{2})(?::(\d{2}))?\]?\s*[-–—]?\s*)?'
                          r'([A-Za-zА-Яа-яЁё][\w .\-ёЁ]{0,40}?)\s*:\s*(.+)$')


def not_found():
    return MeetError(404, 'not_found', 'Не найдено или нет доступа.')


def model_error(error: LocalAIError):
    return MeetError(503, f'model_{error.code}', f'{error} Данные сохранены, можно повторить.')


def install(app):
    ensure_demo_users()

    @app.exception_handler(MeetError)
    async def _handle(_request, error: MeetError):
        return JSONResponse({'detail': error.detail, 'code': error.code}, status_code=error.status)

    app.include_router(router())


# ---------- payloads ----------
class Login(BaseModel):
    login: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=200)


class MeetingIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    topic: str = Field(default='', max_length=2000)
    scheduled_at: str | None = Field(default=None, max_length=40)
    participants: list[str] = Field(default_factory=list, max_length=50)
    access_user_ids: list[int] = Field(default_factory=list, max_length=50)


class MeetingPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    topic: str | None = Field(default=None, max_length=2000)
    scheduled_at: str | None = Field(default=None, max_length=40)
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
    start_ms: int | None = None


class UtterancePatch(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=5000)
    speaker_label: str | None = Field(default=None, min_length=1, max_length=60)


class SpeakersIn(BaseModel):
    speaker_map: dict[str, str]


class ItemIn(BaseModel):
    id: int | None = None
    kind: str = Field(pattern='^(decision|proposal|task|open_question)$')
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


class NextAgendaIn(BaseModel):
    create_meeting: bool = False


# ---------- helpers ----------
def _sid(value: str, prefix: str) -> int:
    match = re.fullmatch(prefix + r'?(\d+)', str(value).strip().upper())
    if not match:
        raise not_found()
    return int(match[1])


def _meeting(connection, user, meeting_id):
    if not store.can_read_meeting(connection, user['id'], meeting_id):
        raise not_found()
    return connection.execute('SELECT * FROM meetings WHERE id=?', (meeting_id,)).fetchone()


def _meeting_date(row) -> date:
    try:
        return datetime.fromisoformat(row['scheduled_at']).date() if row['scheduled_at'] else date.today()
    except ValueError:
        return date.today()


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
    return {'meeting': store.meeting_out(connection, row),
            'documents': [store.document_out(connection, d) for d in visible], 'hidden_documents': hidden,
            'utterances': store.utterances(connection, row['id']), 'prep': store.prep(connection, row['id']),
            'protocol': store.protocol(connection, row['id']), 'tasks': tasks}


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
    api = APIRouter()

    @api.get('/meetings', include_in_schema=False)
    def page():
        return FileResponse(ROOT / 'static' / 'meetings.html')

    # ----- auth -----
    @api.post('/api/meet/login')
    def login(payload: Login, request: Request):
        with store.db() as connection:
            row = connection.execute('SELECT * FROM users WHERE login=?', (payload.login.strip().lower(),)).fetchone()
            if not row or not check_password(payload.password, row['password_hash']):
                store.audit(connection, None, 'login_failed', login=payload.login[:50])
                raise MeetError(401, 'bad_credentials', 'Неверный логин или пароль.')
            store.audit(connection, row['id'], 'login')
        response = JSONResponse({'user': {'id': row['id'], 'login': row['login'], 'name': row['name'], 'role': row['role']}})
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
        return {'user': current_user(request)}

    @api.get('/api/meet/users')
    def users(request: Request):
        current_user(request)
        with store.db() as connection:
            return {'users': [dict(r) for r in connection.execute('SELECT id,login,name,role FROM users ORDER BY id')]}

    # ----- documents -----
    @api.post('/api/meet/documents')
    async def upload(request: Request, file: UploadFile = File(...), meeting_id: int | None = Form(default=None),
                     share_with: str = Form(default=''), title: str = Form(default='')):
        user = current_user(request)
        data = await file.read(docs.MAX_BYTES + 1)
        filename = Path(file.filename or 'document.txt').name[:200]
        try:
            kind, fragments = docs.fragments(filename, data)
        except docs.DocumentError as error:
            raise MeetError(422, 'bad_document', str(error)) from None
        with store.db() as connection:
            if meeting_id is not None:
                _meeting(connection, user, meeting_id)
            cursor = connection.execute(
                'INSERT INTO documents(owner_id,title,filename,kind,content,sha256,created_at) VALUES (?,?,?,?,?,?,?)',
                (user['id'], (title.strip() or filename.rsplit('.', 1)[0])[:200], filename, kind, data,
                 hashlib.sha256(data).hexdigest(), store.now()))
            document_id = cursor.lastrowid
            connection.executemany('INSERT INTO fragments(document_id,idx,location,text) VALUES (?,?,?,?)',
                                   [(document_id, f['idx'], f['location'], f['text']) for f in fragments])
            share = [int(v) for v in re.findall(r'\d+', share_with)]
            for user_id in _valid_users(connection, share):
                if user_id != user['id']:
                    connection.execute('INSERT OR IGNORE INTO document_access VALUES (?,?)', (document_id, user_id))
            if meeting_id is not None:
                connection.execute('INSERT OR IGNORE INTO meeting_documents VALUES (?,?)', (meeting_id, document_id))
            store.audit(connection, user['id'], 'document_upload', document_id=document_id, filename=filename)
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
            if not store.can_read_document(connection, user['id'], document_id):
                raise not_found()
            row = connection.execute('SELECT * FROM documents WHERE id=?', (document_id,)).fetchone()
            fragments = [store.fragment_out(f, row['title']) for f in connection.execute(
                'SELECT * FROM fragments WHERE document_id=? ORDER BY idx', (document_id,))]
            return {'document': store.document_out(connection, row), 'fragments': fragments}

    @api.get('/api/meet/documents/{document_id}/download')
    def download(document_id: int, request: Request):
        user = current_user(request)
        with store.db() as connection:
            if not store.can_read_document(connection, user['id'], document_id):
                raise not_found()
            row = connection.execute('SELECT filename,kind,content FROM documents WHERE id=?', (document_id,)).fetchone()
            store.audit(connection, user['id'], 'document_download', document_id=document_id)
        media = {'txt': 'text/plain; charset=utf-8', 'pdf': 'application/pdf',
                 'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}[row['kind']]
        return Response(row['content'], media_type=media, headers={
            'Content-Disposition': f"attachment; filename*=UTF-8''{urlquote(row['filename'])}"})

    @api.get('/api/meet/fragments/{fragment_id}')
    def fragment(fragment_id: str, request: Request):
        user = current_user(request)
        with store.db() as connection:
            row = connection.execute('SELECT f.*, d.title FROM fragments f JOIN documents d ON d.id=f.document_id '
                                     'WHERE f.id=?', (_sid(fragment_id, 'F'),)).fetchone()
            if not row or not store.can_read_document(connection, user['id'], row['document_id']):
                raise not_found()
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
            store.audit(connection, user['id'], 'search', q=q[:100], results=len(results))
            return {'results': results[:50]}

    # ----- meetings -----
    @api.post('/api/meet/meetings')
    def create_meeting(payload: MeetingIn, request: Request):
        user = current_user(request)
        with store.db() as connection:
            cursor = connection.execute(
                'INSERT INTO meetings(owner_id,title,topic,scheduled_at,participants,created_at) VALUES (?,?,?,?,?,?)',
                (user['id'], payload.title.strip(), payload.topic.strip(), payload.scheduled_at,
                 json.dumps([p.strip() for p in payload.participants if p.strip()], ensure_ascii=False), store.now()))
            for user_id in _valid_users(connection, payload.access_user_ids):
                if user_id != user['id']:
                    connection.execute('INSERT OR IGNORE INTO meeting_access VALUES (?,?)', (cursor.lastrowid, user_id))
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
            row = _meeting(connection, user, meeting_id)
            values = payload.model_dump(exclude_unset=True)
            if 'access_user_ids' in values:
                if row['owner_id'] != user['id']:
                    raise MeetError(403, 'owner_only', 'Доступ к встрече может менять только её владелец.')
                connection.execute('DELETE FROM meeting_access WHERE meeting_id=?', (meeting_id,))
                for user_id in _valid_users(connection, values.pop('access_user_ids') or []):
                    if user_id != row['owner_id']:
                        connection.execute('INSERT INTO meeting_access VALUES (?,?)', (meeting_id, user_id))
            if 'participants' in values:
                values['participants'] = json.dumps(values['participants'] or [], ensure_ascii=False)
            for key, value in values.items():
                connection.execute(f'UPDATE meetings SET {key}=? WHERE id=?', (value, meeting_id))
            return {'meeting': store.meeting_out(connection, _meeting(connection, user, meeting_id))}

    @api.post('/api/meet/meetings/{meeting_id}/documents')
    def attach(meeting_id: int, payload: AttachIn, request: Request):
        user = current_user(request)
        with store.db() as connection:
            _meeting(connection, user, meeting_id)
            if not store.can_read_document(connection, user['id'], payload.document_id):
                raise not_found()
            connection.execute('INSERT OR IGNORE INTO meeting_documents VALUES (?,?)', (meeting_id, payload.document_id))
            return _full_meeting(connection, user, _meeting(connection, user, meeting_id))

    @api.delete('/api/meet/meetings/{meeting_id}/documents/{document_id}')
    def detach(meeting_id: int, document_id: int, request: Request):
        user = current_user(request)
        with store.db() as connection:
            _meeting(connection, user, meeting_id)
            if not store.can_read_document(connection, user['id'], document_id):
                raise not_found()
            connection.execute('DELETE FROM meeting_documents WHERE meeting_id=? AND document_id=?', (meeting_id, document_id))
            return _full_meeting(connection, user, _meeting(connection, user, meeting_id))

    @api.post('/api/meet/meetings/{meeting_id}/prepare')
    def prepare(meeting_id: int, request: Request):
        user = current_user(request)
        with store.db() as connection:
            row = _meeting(connection, user, meeting_id)
            visible, _hidden = _meeting_documents(connection, user, meeting_id)
            fragments = []
            for document in visible:  # model context = ONLY documents this user may read
                fragments += [store.fragment_out(f, document['title']) for f in connection.execute(
                    'SELECT * FROM fragments WHERE document_id=? ORDER BY idx', (document['id'],))]
            meeting = store.meeting_out(connection, row)
        try:
            result = extract.prepare(get_llm(), meeting, fragments)
        except LocalAIError as error:
            raise model_error(error) from None
        result['generated_at'] = store.now()
        result['generated_for'] = user['name']
        with store.db() as connection:
            connection.execute('INSERT OR REPLACE INTO preps VALUES (?,?,?,?)',
                               (meeting_id, json.dumps(result, ensure_ascii=False), user['id'], store.now()))
        return {'prep': result}

    # ----- transcript -----
    @api.put('/api/meet/meetings/{meeting_id}/transcript')
    def put_transcript(meeting_id: int, payload: TranscriptIn, request: Request):
        user = current_user(request)
        lines = parse_transcript(payload.text)
        with store.db() as connection:
            _meeting(connection, user, meeting_id)
            connection.execute('UPDATE utterances SET deleted=1 WHERE meeting_id=?', (meeting_id,))
            connection.executemany(
                'INSERT INTO utterances(meeting_id,idx,speaker_label,text,original_text,source,start_ms) VALUES (?,?,?,?,?,?,?)',
                [(meeting_id, i + 1, u['speaker_label'], u['text'], u['text'], 'manual', u['start_ms'])
                 for i, u in enumerate(lines)])
            return {'utterances': store.utterances(connection, meeting_id)}

    @api.post('/api/meet/meetings/{meeting_id}/utterances')
    def add_utterance(meeting_id: int, payload: UtteranceIn, request: Request):
        user = current_user(request)
        with store.db() as connection:
            _meeting(connection, user, meeting_id)
            position = connection.execute('SELECT COALESCE(MAX(idx),0)+1 FROM utterances WHERE meeting_id=?',
                                          (meeting_id,)).fetchone()[0]
            text = payload.text.strip()
            cursor = connection.execute(
                'INSERT INTO utterances(meeting_id,idx,speaker_label,text,original_text,source,start_ms) VALUES (?,?,?,?,?,?,?)',
                (meeting_id, position, payload.speaker_label.strip() or 'Говорящий ?', text, text, payload.source,
                 payload.start_ms))
            row = connection.execute('SELECT * FROM utterances WHERE id=?', (cursor.lastrowid,)).fetchone()
            return {'utterance': store.utterance_out(row, store.speaker_map(connection, meeting_id))}

    def _utterance(connection, user, utterance_id):
        row = connection.execute('SELECT * FROM utterances WHERE id=? AND deleted=0', (_sid(utterance_id, 'U'),)).fetchone()
        if not row or not store.can_read_meeting(connection, user['id'], row['meeting_id']):
            raise not_found()
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
        user = current_user(request)
        with store.db() as connection:
            row = _utterance(connection, user, utterance_id)
            if payload.text is not None:
                connection.execute('UPDATE utterances SET text=?, edited=1 WHERE id=?', (payload.text.strip(), row['id']))
            if payload.speaker_label is not None:
                connection.execute('UPDATE utterances SET speaker_label=? WHERE id=?', (payload.speaker_label.strip(), row['id']))
            row = connection.execute('SELECT * FROM utterances WHERE id=?', (row['id'],)).fetchone()
            return {'utterance': store.utterance_out(row, store.speaker_map(connection, row['meeting_id']))}

    @api.delete('/api/meet/utterances/{utterance_id}')
    def delete_utterance(utterance_id: str, request: Request):
        user = current_user(request)
        with store.db() as connection:
            row = _utterance(connection, user, utterance_id)
            connection.execute('UPDATE utterances SET deleted=1 WHERE id=?', (row['id'],))
            return {'ok': True}

    @api.put('/api/meet/meetings/{meeting_id}/speakers')
    def speakers(meeting_id: int, payload: SpeakersIn, request: Request):
        user = current_user(request)
        mapping = {k.strip()[:60]: v.strip()[:120] for k, v in payload.speaker_map.items() if k.strip() and v.strip()}
        with store.db() as connection:
            _meeting(connection, user, meeting_id)
            connection.execute('UPDATE meetings SET speaker_map=? WHERE id=?', (json.dumps(mapping, ensure_ascii=False), meeting_id))
            return {'meeting': store.meeting_out(connection, _meeting(connection, user, meeting_id)),
                    'utterances': store.utterances(connection, meeting_id)}

    # ----- protocol -----
    @api.post('/api/meet/meetings/{meeting_id}/protocol/draft')
    def draft(meeting_id: int, request: Request):
        user = current_user(request)
        with store.db() as connection:
            row = _meeting(connection, user, meeting_id)
            utterances = store.utterances(connection, meeting_id)
            participants = json.loads(row['participants'])
            confirmed = [store.item_out(connection, r) for r in connection.execute(
                'SELECT * FROM protocol_items WHERE meeting_id=? AND confirmed_at IS NOT NULL', (meeting_id,))]
        if not utterances:
            raise MeetError(409, 'empty_transcript', 'Сначала добавьте расшифровку встречи.')
        llm = get_llm()
        try:
            items, warnings = extract.draft_protocol(llm, utterances, participants, _meeting_date(row))
        except LocalAIError as error:
            raise model_error(error) from None
        # Never duplicate already confirmed items on re-draft.
        fresh = [i for i in items if not any(
            c['kind'] == i['kind'] and (extract.tu.overlap(i['text'], c['text']) >= 0.6 or
                                         {q['utterance_id'] for q in c['quotes']} & {q['utterance_id'] for q in i['quotes']})
            for c in confirmed)]
        with store.db() as connection:
            connection.execute('DELETE FROM protocol_items WHERE meeting_id=? AND confirmed_at IS NULL', (meeting_id,))
            connection.execute('INSERT OR REPLACE INTO protocols(meeting_id,warnings,generated_at,model) VALUES (?,?,?,?)',
                               (meeting_id, json.dumps(warnings, ensure_ascii=False), store.now(), getattr(llm, 'model', None)))
            base = len(confirmed)
            for position, item in enumerate(fresh, base + 1):
                _insert_item(connection, meeting_id, position, item)
            store.audit(connection, user['id'], 'protocol_draft', meeting_id=meeting_id, items=len(fresh))
            return {'protocol': store.protocol(connection, meeting_id)}

    @api.put('/api/meet/meetings/{meeting_id}/protocol')
    def save_protocol(meeting_id: int, payload: ProtocolIn, request: Request):
        user = current_user(request)
        with store.db() as connection:
            _meeting(connection, user, meeting_id)
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
            return {'protocol': store.protocol(connection, meeting_id)}

    @api.post('/api/meet/meetings/{meeting_id}/protocol/confirm')
    def confirm(meeting_id: int, payload: ConfirmIn, request: Request):
        user = current_user(request)
        created, already = [], []
        with store.db() as connection:
            _meeting(connection, user, meeting_id)
            for item_id in dict.fromkeys(payload.item_ids):
                row = connection.execute('SELECT * FROM protocol_items WHERE id=? AND meeting_id=?', (item_id, meeting_id)).fetchone()
                if not row:
                    raise not_found()
                if row['kind'] != 'task':
                    raise MeetError(422, 'not_a_task', 'Подтверждать в задачи можно только поручения.')
                existing = connection.execute('SELECT * FROM tasks WHERE protocol_item_id=?', (item_id,)).fetchone()
                if existing:
                    already.append(store.task_out(connection, existing))
                    continue
                quotes = json.loads(row['quotes'])
                stamp = store.now()
                cursor = connection.execute(
                    'INSERT INTO tasks(meeting_id,protocol_item_id,text,assignee,assignee_status,due,due_text,due_status,status,'
                    'source_quote,confirmed_by,confirmed_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (meeting_id, item_id, row['text'], row['assignee'], row['assignee_status'], row['due'], row['due_text'],
                     row['due_status'], 'open', json.dumps(quotes[0] if quotes else {}, ensure_ascii=False), user['id'],
                     stamp, stamp, stamp))
                connection.execute('UPDATE protocol_items SET confirmed_by=?, confirmed_at=?, task_id=? WHERE id=?',
                                   (user['id'], stamp, cursor.lastrowid, item_id))
                store.audit(connection, user['id'], 'task_confirmed', item_id=item_id, task_id=cursor.lastrowid)
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

    @api.patch('/api/meet/tasks/{task_id}')
    def patch_task(task_id: int, payload: TaskPatch, request: Request):
        user = current_user(request)
        with store.db() as connection:
            row = connection.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
            if not row or not store.can_read_meeting(connection, user['id'], row['meeting_id']):
                raise not_found()
            values = payload.model_dump(exclude_unset=True)
            if 'status' in values and values['status']:
                connection.execute('UPDATE tasks SET status=? WHERE id=?', (values['status'], task_id))
            if 'assignee' in values:
                assignee = (values['assignee'] or '').strip() or None
                connection.execute('UPDATE tasks SET assignee=?, assignee_status=? WHERE id=?',
                                   (assignee, 'stated' if assignee else 'unknown', task_id))
            if 'due' in values:
                due = _iso_date(values['due'])
                connection.execute('UPDATE tasks SET due=?, due_status=? WHERE id=?',
                                   (due, 'stated' if due else 'unknown', task_id))
            connection.execute('UPDATE tasks SET updated_at=? WHERE id=?', (store.now(), task_id))
            store.audit(connection, user['id'], 'task_update', task_id=task_id, **{k: str(v) for k, v in values.items()})
            return {'task': store.task_out(connection, connection.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone())}

    @api.post('/api/meet/meetings/{meeting_id}/next-agenda')
    def next_agenda(meeting_id: int, payload: NextAgendaIn, request: Request):
        user = current_user(request)
        with store.db() as connection:
            row = _meeting(connection, user, meeting_id)
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
