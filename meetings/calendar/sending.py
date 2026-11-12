"""Durable external send. A claimed/uncertain write is NEVER blindly retried.

Reservation and token are committed before HTTP. After process interruption a
new confirm returns 'uncertain', preserving the slot until manual reconciliation.
"""
import json
from fastapi.responses import JSONResponse
from meetings import access, store
from meetings.api import _meeting
from meetings.auth import MeetError
from meetings.calendar import providers, service
from meetings.connectors.contracts import IntegrationError
from meetings.connectors.mock import digest


def snapshot(c, user, ids):
    try: return providers.provider(c, user).proof(ids)
    except IntegrationError as error:
        raise MeetError(503, 'calendar_' + error.code, 'Календарь не настроен или недоступен. Предпросмотр сохранён в форме.') from None


def reserve(c, user, meeting, body, confirmation_id, idem):
    result = service.create_event(c, user, meeting, body, confirmation_id,
                                  status='pending_external', provider=body['provider'])
    c.execute('INSERT INTO calendar_provider_outbox(event_id,user_id,provider,payload,payload_hash,idempotency_key,created_at,updated_at) '
              'VALUES (?,?,?,?,?,?,?,?)', (result['event_id'], user['id'], body['provider'],
              json.dumps(body, ensure_ascii=False), digest(body), idem, store.now(), store.now()))
    return result


def _reply(c, user, event_id, already=False):
    row = c.execute('SELECT status,last_error,external_ref FROM calendar_provider_outbox WHERE event_id=?', (event_id,)).fetchone()
    result = {**service.event_bundle(c, user['id'], event_id), 'already_confirmed': already,
              'delivery_status': row['status'], 'external_ref': row['external_ref']}
    if row['status'] != 'sent':
        result.update(status=row['status'], error={'code': 'calendar_' + (row['last_error'] or row['status']),
            'message': 'Событие не подтверждено внешним календарём. Не создавайте повтор: проверьте результат у администратора.'})
        return JSONResponse(result, status_code=503)
    return result


def dispatch(user, event_id, *, already=False):
    with store.write_tx() as c:
        row = c.execute('SELECT * FROM calendar_provider_outbox WHERE event_id=? AND user_id=?', (event_id, user['id'])).fetchone()
        if not row: raise MeetError(404, 'calendar_not_found', 'Событие не найдено.')
        event = c.execute('SELECT * FROM calendar_events WHERE id=?', (event_id,)).fetchone()
        _meeting(c, user, event['meeting_id'], 'calendar.invite', 'calendar.confirm')
        if row['status'] == 'sending':
            c.execute("UPDATE calendar_provider_outbox SET status='uncertain',last_error='uncertain',updated_at=? WHERE id=?", (store.now(),row['id']))
            c.execute("UPDATE calendar_events SET status='uncertain' WHERE id=?", (event_id,))
        if row['status'] != 'pending': return _reply(c, user, event_id, already)
        body = json.loads(row['payload'])
        actor = access.load_user(c, user['id'])
        try:
            if digest(body) != row['payload_hash'] or snapshot(c, actor, [p['id'] for p in body['participants']]) != body['provider_proof']:
                raise IntegrationError('conflict')
        except (IntegrationError, MeetError):
            c.execute("UPDATE calendar_provider_outbox SET status='failed',last_error='conflict',updated_at=? WHERE id=?", (store.now(), row['id']))
            c.execute("UPDATE calendar_events SET status='failed' WHERE id=?", (event_id,))
            return _reply(c, user, event_id, already)
        c.execute("UPDATE calendar_provider_outbox SET status='sending',updated_at=? WHERE id=?", (store.now(), row['id']))
    # sending state is durable before the first byte is sent.
    failure = None
    try:
        with store.db() as c:
            actor = access.load_user(c, user['id'])
            result = providers.provider(c, actor).create_event(body, row['idempotency_key'])
    except IntegrationError as error:
        failure = ('uncertain' if error.uncertain or error.code == 'uncertain' else 'failed', error.code)
    with store.write_tx() as c:
        # A concurrent replay may already have marked this send uncertain. A known
        # successful response can reconcile it, while failure never resends.
        if failure:
            status, code = failure
            c.execute('UPDATE calendar_provider_outbox SET status=?,last_error=?,updated_at=? WHERE id=?', (status, code, store.now(), row['id']))
            c.execute('UPDATE calendar_events SET status=? WHERE id=?', ('uncertain' if status=='uncertain' else 'failed', event_id))
        else:
            c.execute("UPDATE calendar_provider_outbox SET status='sent',external_ref=?,updated_at=? WHERE id=?", (result['ref'],store.now(),row['id']))
            meeting = c.execute('SELECT * FROM meetings WHERE id=?', (body['meeting_id'],)).fetchone()
            service.finalize_event(c, actor, meeting, body, event_id)
        store.audit(c, user['id'], 'calendar_delivery', object_type='calendar_event', object_id=event_id,
                    result=failure[0] if failure else 'sent', error_code=failure[1] if failure else None)
        return _reply(c, user, event_id, already)
