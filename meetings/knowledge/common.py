"""Request boundaries shared by the two track-3 read modules."""
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from meetings import auth, store
from meetings.auth import MeetError, current_user


def utc_now():
    return datetime.now(timezone.utc)


def iso(value):
    return value.astimezone(timezone.utc).isoformat()


def aware(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('timezone required')
    return parsed


def not_found():
    return MeetError(404, 'not_found', 'Не найдено или нет доступа.')


def run(request, response, action, operation):
    # Reuse the core's validated correlation ID, or generate one on the base API.
    context = getattr(store, 'request_id_var', None)
    request_id = (context.get() if context else None) or uuid4().hex
    response.headers['X-Request-ID'] = request_id
    actor = None
    details = {'request_id': request_id, 'object_type': action.split('.')[0],
               'source_ids': [], 'model': None}
    try:
        user = current_user(request)
        actor = user['id']
        # Core's capability API is optional on the agreed base commit. Both core
        # roles can read; when integrated, enforce the capability server-side too.
        if hasattr(auth, 'require'):
            capability = 'qa.ask' if action.startswith('qa.') else 'overview.read'
            auth.require(user, capability, action=action)
        result = operation(actor, details)
        details['result'] = result.get('status', 'ok')
    except sqlite3.OperationalError:
        details.update(result='error', error_code='storage_unavailable')
        raise MeetError(503, 'storage_unavailable', 'Хранилище временно недоступно. Проверьте миграции.') from None
    except MeetError as error:
        details.update(result='denied' if error.status in (401, 403, 404) else 'error', error_code=error.code)
        raise
    finally:
        # A separate transaction keeps refusal audit after the operation rolls back.
        with store.db() as connection:
            store.audit(connection, actor, action, **details)
    return result
