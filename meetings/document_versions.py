"""Immutable editions; scoped history, extractive summaries and fragment diffs.

The document is never overwritten and meeting attachments remain explicit.
Only its owner can propose a successor, with the current ACL copied at confirm.
"""
import hashlib
import json
from difflib import SequenceMatcher
from pathlib import PurePosixPath

from fastapi import APIRouter, File, Form, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from meetings import access, confirmations, documents, store
from meetings.auth import MeetError, MeetRoute, current_user, require
from meetings.privacy import prohibited_intent, source_is_injection


class Confirm(BaseModel):
    model_config = ConfigDict(extra='forbid')
    confirmation_id: str = Field(min_length=8, max_length=80)
    idempotency_key: str = Field(min_length=8, max_length=100)


def read(c, user, did, *, model=False):
    from meetings.api import denied
    if not store.can_read_document(c, user['id'], did, model=model):
        raise denied(user, 'document', did, 'document.read')
    return c.execute('SELECT * FROM documents WHERE id=?', (did,)).fetchone()


def owned(c, user, did):
    row = read(c, user, did)
    if row['owner_id'] != user['id']:
        from meetings.api import denied
        raise denied(user, 'document', did, 'document.version')
    require(user, 'documents.upload', action='document.version')
    return row


def snapshot(c, row):
    # Bind ACL and all metadata, without copying file bytes into token JSON.
    fields = {k: row[k] for k in row.keys() if k != 'content'}
    fields['acl'] = [r[0] for r in c.execute(
        'SELECT user_id FROM document_access WHERE document_id=? ORDER BY user_id', (row['id'],))]
    return hashlib.sha256(json.dumps(fields, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def metadata_time(value):
    if not value.strip():
        return None
    try:
        return store.iso_utc(store.parse_aware(value.strip()))
    except store.TimeError:
        raise MeetError(422, 'invalid_time', 'Дата должна содержать время и часовой пояс (ISO 8601).') from None


def freshness(c, actor, did):
    """Do not expose the existence/id/title of an inaccessible successor."""
    row = c.execute('SELECT valid_until FROM documents WHERE id=?', (did,)).fetchone()
    visible, params = access.predicate(c, actor, 'document', 'd')
    replaced = bool(c.execute('WITH RECURSIVE family(id) AS (SELECT id FROM documents WHERE supersedes_id=? '
                              'UNION SELECT child.id FROM documents child JOIN family f ON child.supersedes_id=f.id) '
                              'SELECT 1 FROM documents d JOIN family f ON f.id=d.id WHERE ' + visible,
                              [did, *params]).fetchone())
    expired = False
    if row and row['valid_until']:
        try:
            expired = store.parse_aware(row['valid_until']) <= store.parse_aware(store.now())
        except store.TimeError:
            expired = True
    return {'superseded': replaced, 'expired': expired, 'stale': replaced or expired}


def warnings(c, actor, rows):
    result = []
    for did in dict.fromkeys(row['document_id'] for row in rows):
        state = freshness(c, actor, did)
        if state['stale']:
            result.append({'document_id': did, **state, 'message': 'Источник устарел: ' +
                           ('есть доступная новая версия.' if state['superseded'] else 'срок действия истёк.')})
    return result


def cited(row, fragment):
    return {'kind': 'document', 'id': f"F{fragment['id']}", 'title': row['title'],
            'source_at': row['authored_at'] or row['created_at'], 'quote': fragment['text'],
            'locator': fragment['location'], 'document_id': row['id'], 'version': row['version']}


def parts(c, did):
    return [dict(r) for r in c.execute('SELECT * FROM fragments WHERE document_id=? ORDER BY idx', (did,))]


def router():
    api = APIRouter(route_class=MeetRoute)

    @api.post('/api/meet/documents/{document_id}/versions/preview')
    async def preview(document_id: int, request: Request, file: UploadFile = File(...),
                      authored_at: str = Form(default=''), valid_until: str = Form(default='')):
        user = current_user(request)
        with store.db() as c:
            owned(c, user, document_id)  # deny before parsing untrusted content
        data = await file.read(documents.MAX_BYTES + 1)
        filename = PurePosixPath((file.filename or 'document.txt').replace('\\', '/')).name[:200]
        try:
            kind, fragments = documents.fragments(filename, data)
        except documents.DocumentError as error:
            raise MeetError(422, 'bad_document', str(error)) from None
        authored = metadata_time(authored_at) or store.now()
        until = metadata_time(valid_until)
        if until and store.parse_aware(until) <= store.parse_aware(authored):
            raise MeetError(422, 'invalid_validity', 'Срок действия должен быть позже даты документа.')
        with store.write_tx() as c:
            row = owned(c, user, document_id)
            if c.execute('SELECT 1 FROM documents WHERE supersedes_id=?', (document_id,)).fetchone():
                raise MeetError(409, 'version_superseded', 'Версия уже заменена. Откройте актуальный документ.')
            if row['sha256'] == hashlib.sha256(data).hexdigest():
                raise MeetError(422, 'identical_version', 'Содержимое не изменилось.')
            # Expired drafts cannot retain file bytes indefinitely between uploads.
            c.execute('DELETE FROM document_version_drafts WHERE confirmation_id IN '
                      '(SELECT id FROM confirmations WHERE expires_at<=? OR status!=\'pending\')', (store.now(),))
            payload = {'filename': filename, 'kind': kind, 'sha256': hashlib.sha256(data).hexdigest(),
                       'authored_at': authored, 'valid_until': until, 'snapshot': snapshot(c, row)}
            token = confirmations.create(c, user, 'document.version', 'document', document_id, row['version'], payload)
            c.execute('INSERT INTO document_version_drafts VALUES (?,?,?)', (token['confirmation_id'], user['id'], data))
            store.audit(c, user['id'], 'document_version_preview', object_type='document', object_id=document_id,
                        stage='preview', confirmation_id=token['confirmation_id'])
            return {**token, 'preview': {'document_id': document_id, 'title': row['title'],
                    'version': row['version'] + 1, 'filename': filename, 'fragments_count': len(fragments),
                    'authored_at': authored, 'valid_until': until,
                    'notice': 'Доступ и отдел наследуются. Привязки встреч остаются на прежней версии.'}}

    @api.post('/api/meet/documents/{document_id}/versions/confirm')
    def confirm(document_id: int, payload: Confirm, request: Request):
        user = current_user(request)
        with store.write_tx() as c:
            row = owned(c, user, document_id)
            pending = confirmations.load(c, user, payload.confirmation_id, 'document.version', 'document',
                                         document_id, payload.idempotency_key)
            if pending['already']:
                new = read(c, user, pending['result']['document_id'])
                return {'document': store.document_out(c, new, user['id']), 'already_confirmed': True}
            p = pending['payload']
            if snapshot(c, row) != p['snapshot'] or c.execute(
                    'SELECT 1 FROM documents WHERE supersedes_id=?', (document_id,)).fetchone():
                raise MeetError(409, 'stale_version', 'Документ или доступ изменились. Сформируйте новый предпросмотр.')
            draft = c.execute('SELECT content FROM document_version_drafts WHERE confirmation_id=? AND user_id=?',
                              (payload.confirmation_id, user['id'])).fetchone()
            if not draft or hashlib.sha256(draft['content']).hexdigest() != p['sha256']:
                raise MeetError(409, 'draft_unavailable', 'Файл предпросмотра недоступен. Загрузите снова.')
            kind, fragments = documents.fragments(p['filename'], draft['content'])
            did = c.execute('INSERT INTO documents(owner_id,title,filename,kind,content,sha256,created_at,'
                'department_id,confidentiality,doc_type,authored_at,valid_until,version,supersedes_id,source_ref) '
                'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (row['owner_id'], row['title'], p['filename'], kind, draft['content'], p['sha256'], store.now(),
                 row['department_id'], row['confidentiality'], row['doc_type'], p['authored_at'], p['valid_until'],
                 row['version'] + 1, document_id, row['source_ref'])).lastrowid
            c.executemany('INSERT INTO fragments(document_id,idx,location,text) VALUES (?,?,?,?)',
                          [(did, f['idx'], f['location'], f['text']) for f in fragments])
            c.execute('INSERT INTO document_access SELECT ?,user_id FROM document_access WHERE document_id=?', (did, document_id))
            confirmations.finish(c, payload.confirmation_id, payload.idempotency_key, {'document_id': did})
            c.execute('DELETE FROM document_version_drafts WHERE confirmation_id=?', (payload.confirmation_id,))
            store.audit(c, user['id'], 'document_version_confirmed', object_type='document', object_id=did,
                        supersedes_id=document_id, stage='confirm', confirmation_id=payload.confirmation_id)
            return {'document': store.document_out(c, read(c, user, did), user['id']), 'already_confirmed': False}

    @api.get('/api/meet/documents/{document_id}/versions')
    def history(document_id: int, request: Request):
        user = current_user(request)
        with store.db() as c:
            read(c, user, document_id)
            # Traverse identifiers only. Every returned edition gets its own ACL decision.
            ids = [r[0] for r in c.execute('WITH RECURSIVE family(id) AS (SELECT ? UNION '
                'SELECT d.supersedes_id FROM documents d JOIN family f ON d.id=f.id WHERE d.supersedes_id IS NOT NULL UNION '
                'SELECT d.id FROM documents d JOIN family f ON d.supersedes_id=f.id) SELECT id FROM family', (document_id,))]
            result = [store.document_out(c, read(c, user, did), user['id']) for did in ids
                      if store.can_read_document(c, user['id'], did)]
            store.audit(c, user['id'], 'document_versions_read', object_type='document', object_id=document_id)
            return {'versions': sorted(result, key=lambda d: (d['version'], d['id']))}

    @api.get('/api/meet/documents/{document_id}/compare/{other_id}')
    def compare(document_id: int, other_id: int, request: Request):
        user = current_user(request)
        with store.db() as c:
            # Content analytics follows model policy, including the Secret exclusion.
            left, right = read(c, user, document_id, model=True), read(c, user, other_id, model=True)
            a, b = parts(c, document_id), parts(c, other_id)
            if len(a) + len(b) > 2000:
                raise MeetError(422, 'comparison_too_large', 'Слишком много фрагментов для сравнения (максимум 2000).')
            changes = []
            for tag, i, j, k, l in SequenceMatcher(None, [p['text'] for p in a], [p['text'] for p in b], autojunk=False).get_opcodes():
                if tag != 'equal':
                    changes.append({'change': tag, 'before': [cited(left, p) for p in a[i:j]],
                                    'after': [cited(right, p) for p in b[k:l]]})
            store.audit(c, user['id'], 'document_compare', object_type='document', object_id=document_id, other_id=other_id)
            return {'changes': changes, 'mode': 'fragment_diff', 'model': None}

    @api.get('/api/meet/documents/{document_id}/summary')
    def summary(document_id: int, request: Request):
        user = current_user(request)
        with store.db() as c:
            row = read(c, user, document_id, model=True)
            candidates = []
            if not source_is_injection(row['title']) and not source_is_injection(row['filename']):
                candidates = [p for p in parts(c, document_id) if 12 <= len(p['text']) <= 1000
                              and not source_is_injection(p['text']) and not prohibited_intent(p['text'])][:5]
            claims = [{'text': p['text'], 'sources': [cited(row, p)]} for p in candidates]
            store.audit(c, user['id'], 'document_summary', object_type='document', object_id=document_id,
                        source_ids=[s['id'] for claim in claims for s in claim['sources']])
            return {'status': 'grounded' if claims else 'insufficient_data', 'mode': 'extractive', 'model': None,
                    'claims': claims, 'warnings': warnings(c, user['id'], [{'document_id': document_id}]),
                    'notice': 'Выдержки первых пяти подходящих фрагментов; это не полная смысловая сводка.'}

    return api
