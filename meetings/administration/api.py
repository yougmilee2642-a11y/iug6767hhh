import json
import re
from datetime import timedelta

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from meetings import access, confirmations, store
from meetings.auth import MeetError, MeetRoute, current_user, require, forbidden


class ChangeUser(BaseModel):
    model_config = ConfigDict(extra='forbid')
    user_id: int = Field(gt=0)
    level: str | None = None
    department_id: int | None = Field(default=None, gt=0)
    active: bool | None = None


class Grant(BaseModel):
    model_config = ConfigDict(extra='forbid')
    to_user: int = Field(gt=0)
    department_id: int = Field(gt=0)
    starts_at: str
    ends_at: str
    reason: str = Field(min_length=5, max_length=500)


class Token(BaseModel):
    model_config = ConfigDict(extra='forbid')
    confirmation_id: str = Field(min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=100)


def user_changes(c, actor, data):
    require(actor, 'users.manage', 'user', data['user_id'], 'users.change')
    target = c.execute('SELECT id,level,department_id,active FROM users WHERE id=?', (data['user_id'],)).fetchone()
    if not target:
        raise MeetError(404, 'not_found', 'Пользователь не найден.')
    changes = {k: v for k, v in data.items() if k != 'user_id' and v is not None}
    if not changes:
        raise MeetError(422, 'no_changes', 'Укажите изменение.')
    if 'level' in changes and changes['level'] not in access.CONTENT_LEVELS | {'admin', 'auditor'}:
        raise MeetError(422, 'invalid_role', 'Неизвестный уровень доступа.')
    if 'department_id' in changes and not c.execute('SELECT 1 FROM departments WHERE id=?', (changes['department_id'],)).fetchone():
        raise MeetError(422, 'invalid_department', 'Отдел не найден.')
    if actor['id'] == data['user_id']:
        raise MeetError(403, 'own_admin_change', 'Администратор не изменяет собственные полномочия и активность.')
    return dict(target), changes


def grant_scope(c, actor, data):
    require(actor, 'delegation.grant', 'delegation', None, 'delegation.grant')
    if actor.get('level') not in ('director', 'head'):
        raise forbidden(actor, 'delegation.grant', 'delegation', None, 'delegation.grant')
    if actor['level'] != 'director' and data['department_id'] != actor['department_id']:
        raise forbidden(actor, 'delegation.grant', 'department', data['department_id'], 'delegation.grant')
    deputy = access.load_user(c, data['to_user'])
    if not deputy or not deputy['active'] or deputy['level'] not in ('head', 'lead', 'employee') or deputy['id'] == actor['id']:
        raise MeetError(422, 'invalid_deputy', 'Выберите другого действующего сотрудника или руководителя.')
    if not c.execute('SELECT 1 FROM departments WHERE id=?', (data['department_id'],)).fetchone():
        raise MeetError(422, 'invalid_department', 'Отдел не найден.')
    try:
        start, end = store.parse_aware(data['starts_at']), store.parse_aware(data['ends_at'])
        if start >= end or end - start > timedelta(days=60) or end <= store.parse_aware(store.now()):
            raise ValueError()
    except (ValueError, store.TimeError):
        raise MeetError(422, 'invalid_period', 'Укажите aware ISO-даты: начало раньше конца, срок не более 60 дней и ещё не истёк.') from None
    return {**data, 'starts_at': store.iso_utc(start), 'ends_at': store.iso_utc(end)}


def router():
    api = APIRouter(route_class=MeetRoute)

    @api.get('/api/meet/admin/users')
    def users(request: Request):
        actor = current_user(request)
        require(actor, 'users.manage', action='users.list')
        with store.db() as c:
            return {'users': [dict(r) for r in c.execute('SELECT id,login,name,level,department_id,active,timezone FROM users ORDER BY id')],
                    'departments': [dict(r) for r in c.execute('SELECT id,code,name FROM departments ORDER BY id')]}

    @api.post('/api/meet/admin/users')
    @api.post('/api/meet/admin/users/preview')
    def preview_users(payload: ChangeUser, request: Request):
        actor = current_user(request)
        with store.write_tx() as c:
            before, changes = user_changes(c, actor, payload.model_dump())
            token = confirmations.create(c, actor, 'users.change', 'user', payload.user_id, None,
                                         {'before': before, 'changes': changes})
            store.audit(c, actor['id'], 'users_change_preview', object_type='user', object_id=payload.user_id,
                        confirmation_id=token['confirmation_id'], fields=list(changes))
            return {**token, 'preview': {'before': before, 'after': {**before, **changes}}}

    @api.post('/api/meet/admin/users/confirm')
    def confirm_users(payload: Token, request: Request):
        actor = current_user(request)
        require(actor, 'users.manage', action='users.change')
        with store.write_tx() as c:
            pending = confirmations.load(c, actor, payload.confirmation_id, 'users.change', idempotency_key=payload.idempotency_key)
            if pending.get('already'):
                return {**pending['result'], 'already_confirmed': True}
            data = pending['payload']
            target = int(pending['object_id'])
            before, changes = user_changes(c, access.load_user(c, actor['id']), {'user_id': target, **data['changes']})
            if before != data['before']:
                raise MeetError(409, 'stale', 'Пользователь изменён после предпросмотра.')
            c.execute('UPDATE users SET ' + ','.join(k + '=?' for k in changes) + ' WHERE id=?', [*changes.values(), target])
            confirmations.finish(c, payload.confirmation_id, payload.idempotency_key, {'user_id': target})
            store.audit(c, actor['id'], 'users_change', object_type='user', object_id=target,
                        confirmation_id=payload.confirmation_id, fields=list(changes))
            return {'user_id': target, 'already_confirmed': False}

    @api.post('/api/meet/delegations')
    def preview_grant(payload: Grant, request: Request):
        actor = current_user(request)
        with store.write_tx() as c:
            data = grant_scope(c, actor, payload.model_dump())
            token = confirmations.create(c, actor, 'delegation.grant', 'department', data['department_id'], None, data)
            store.audit(c, actor['id'], 'delegation_preview', object_type='department', object_id=data['department_id'],
                        confirmation_id=token['confirmation_id'])
            return {**token, 'preview': data}

    @api.post('/api/meet/delegations/confirm')
    def confirm_grant(payload: Token, request: Request):
        actor = current_user(request)
        with store.write_tx() as c:
            pending = confirmations.load(c, actor, payload.confirmation_id, 'delegation.grant', idempotency_key=payload.idempotency_key)
            if pending.get('already'):
                return {**pending['result'], 'already_confirmed': True}
            data = grant_scope(c, access.load_user(c, actor['id']), pending['payload'])
            did = c.execute('INSERT INTO delegations(from_user,to_user,department_id,starts_at,ends_at,reason,confirmation_id,created_at) '
                            'VALUES (?,?,?,?,?,?,?,?)', (actor['id'], data['to_user'], data['department_id'], data['starts_at'],
                            data['ends_at'], data['reason'], payload.confirmation_id, store.now())).lastrowid
            confirmations.finish(c, payload.confirmation_id, payload.idempotency_key, {'delegation_id': did})
            store.audit(c, actor['id'], 'delegation_granted', object_type='delegation', object_id=did,
                        confirmation_id=payload.confirmation_id, department_id=data['department_id'], to_user=data['to_user'])
            return {'delegation_id': did, 'already_confirmed': False}

    @api.get('/api/meet/access/explain')
    def explain(request: Request, object: str):
        actor = current_user(request)
        match = re.fullmatch(r'(document|meeting|metric):([DFM]?)(\d+)', object)
        if not match:
            raise MeetError(422, 'invalid_object', 'Укажите document:D12, document:F12, meeting:M12 или metric:12.')
        kind, prefix, oid = match.groups()
        with store.db() as c:
            if kind == 'document' and prefix == 'F':
                fragment = c.execute('SELECT document_id FROM fragments WHERE id=?', (int(oid),)).fetchone()
                oid = fragment[0] if fragment else 0
            decision = access.object_decision(c, actor['id'], kind, int(oid))
            if not decision.allowed:
                raise MeetError(404, 'not_found', 'Не найдено или нет доступа.', audit={
                    'user_id': actor['id'], 'action': 'access_denied', 'object_type': kind, 'object_id': oid,
                    'result': 'denied', 'error_code': 'not_found'})
            return {'allowed': True, 'reason_code': decision.reason_code}

    return api
