"""Preview → confirm tokens for significant actions (AI-03).

A token is bound to: user, action, object (type + id) and the object's version at preview time. The normalised
payload is stored server-side; confirm accepts only the token and an idempotency key, so recipients, times or
field values cannot be swapped between preview and confirm. All functions expect a `store.write_tx()` connection,
which serialises concurrent confirms (BEGIN IMMEDIATE): the second of two simultaneous confirms sees the first
one's result and answers `already_confirmed` instead of repeating the action.
"""
import json
import secrets
from datetime import datetime, timedelta, timezone

from meetings import store
from meetings.auth import MeetError

TTL_MINUTES = 15


def _gone(user, confirmation_id, action):
    # Unknown token, another user's token or a token for another object: the same audited 404 (no oracle).
    return MeetError(404, 'confirmation_not_found', 'Подтверждение не найдено или недоступно.',
                     audit={'user_id': user['id'], 'action': 'access_denied', 'object_type': 'confirmation',
                            'object_id': str(confirmation_id)[:80], 'result': 'denied',
                            'error_code': 'confirmation_not_found', 'attempted': action})


def create(connection, user, action: str, object_type: str, object_id, object_version, payload: dict) -> dict:
    token = 'cf_' + secrets.token_urlsafe(18)
    created = datetime.now(timezone.utc)
    expires = created + timedelta(minutes=TTL_MINUTES)
    connection.execute(
        'INSERT INTO confirmations(id,user_id,action,object_type,object_id,object_version,payload,status,created_at,expires_at) '
        "VALUES (?,?,?,?,?,?,?,'pending',?,?)",
        (token, user['id'], action, object_type, str(object_id), object_version,
         json.dumps(payload, ensure_ascii=False), store.iso_utc(created), store.iso_utc(expires)))
    return {'confirmation_id': token, 'expires_at': store.iso_utc(expires)}


def load(connection, user, confirmation_id: str, action: str, object_type: str | None = None, object_id=None,
         idempotency_key: str | None = None) -> dict:
    """Validate a token for confirm. Returns {'already': True, 'result': ...} for a token that was already
    confirmed (repeat or lost race), else the pending record with decoded payload."""
    row = connection.execute('SELECT * FROM confirmations WHERE id=?', (confirmation_id,)).fetchone()
    if (row is None or row['user_id'] != user['id'] or row['action'] != action
            or (object_type is not None and row['object_type'] != object_type)
            or (object_id is not None and row['object_id'] != str(object_id))):
        raise _gone(user, confirmation_id, action)
    if idempotency_key:
        reused = connection.execute('SELECT 1 FROM confirmations WHERE user_id=? AND idempotency_key=? AND id!=?',
                                    (user['id'], idempotency_key, confirmation_id)).fetchone()
        if reused:
            raise MeetError(409, 'idempotency_key_reused', 'Этот ключ идемпотентности уже использован для другого '
                                                          'подтверждения. Сформируйте новый ключ.')
    if row['status'] == 'confirmed':
        return {'already': True, 'result': json.loads(row['result'] or '{}'), 'payload': json.loads(row['payload'])}
    if row['status'] == 'cancelled':
        raise MeetError(409, 'confirmation_cancelled', 'Действие было отменено. Сформируйте новый предпросмотр.')
    if row['status'] != 'pending' or datetime.fromisoformat(row['expires_at']) <= datetime.now(timezone.utc):
        raise MeetError(409, 'confirmation_expired', 'Срок подтверждения истёк. Сформируйте новый предпросмотр.')
    return {'already': False, 'object_version': row['object_version'], 'payload': json.loads(row['payload']),
            'object_id': row['object_id']}


def finish(connection, confirmation_id: str, idempotency_key: str, result: dict):
    updated = connection.execute(
        "UPDATE confirmations SET status='confirmed', idempotency_key=?, result=?, finished_at=? "
        "WHERE id=? AND status='pending'",
        (idempotency_key, json.dumps(result, ensure_ascii=False), store.now(), confirmation_id)).rowcount
    if updated != 1:  # cannot happen inside write_tx; guard against misuse outside it
        raise MeetError(409, 'conflict', 'Подтверждение уже обработано.')


def cancel(connection, user, confirmation_id: str) -> dict:
    row = connection.execute('SELECT * FROM confirmations WHERE id=?', (confirmation_id,)).fetchone()
    if row is None or row['user_id'] != user['id']:
        raise _gone(user, confirmation_id, 'confirmation.cancel')
    if row['status'] == 'confirmed':
        raise MeetError(409, 'already_confirmed', 'Действие уже подтверждено, отменить предпросмотр нельзя.')
    if row['status'] == 'pending':
        connection.execute("UPDATE confirmations SET status='cancelled', finished_at=? WHERE id=?",
                           (store.now(), confirmation_id))
        if row['action'] == 'document.version':
            connection.execute('DELETE FROM document_version_drafts WHERE confirmation_id=?', (confirmation_id,))
        store.audit(connection, user['id'], 'confirmation_cancelled', object_type=row['object_type'],
                    object_id=row['object_id'], confirmation_id=confirmation_id, result='cancelled',
                    action_kind=row['action'], stage='cancel')
    return {'confirmation_id': confirmation_id, 'status': 'cancelled'}


def purge(connection, older_than: datetime) -> int:
    """Retention (§7.4): delete spent tokens — confirmed/cancelled ones finished before `older_than`, and pending
    ones that expired before it. Live pending tokens are never touched. The audit trail keeps the
    confirmation_id, so the chain preview → confirm stays traceable. Returns the number of deleted rows."""
    if older_than.tzinfo is None:
        raise ValueError('older_than must be timezone-aware')
    cutoff = store.iso_utc(older_than)
    return connection.execute(
        "DELETE FROM confirmations WHERE (status IN ('confirmed','cancelled') AND finished_at < ?) "
        "OR (status='pending' AND expires_at < ?)", (cutoff, cutoff)).rowcount
