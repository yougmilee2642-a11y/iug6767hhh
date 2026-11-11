"""Request boundaries shared by the two track-3 read modules."""
import sqlite3
import logging
from datetime import datetime, timezone
from uuid import uuid4

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool

from meetings import auth, store
from meetings.auth import MeetError, current_user

logger = logging.getLogger(__name__)


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


def correlation_id(request):
    existing = getattr(request.state, 'track3_request_id', None)
    if existing:
        return existing
    context = getattr(store, 'request_id_var', None)
    value = (context.get() if context else None) or uuid4().hex
    request.state.track3_request_id = value
    return value


def write_audit(actor, action, details):
    try:
        with store.db() as connection:
            store.audit(connection, actor, action, **details)
        return True
    except (sqlite3.Error, OSError):
        # Do not log backend exception text, questions, or document contents.
        logger.error('audit_unavailable request_id=%s action=%s', details['request_id'], action)
        return False


class ExtensionRoute(APIRoute):
    """Keep validation errors safe and correlated even without the core middleware."""
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handle(request):
            request_id = correlation_id(request)
            try:
                return await original(request)
            except RequestValidationError:
                def record_validation():
                    try:
                        actor = current_user(request)['id']
                    except (MeetError, sqlite3.Error, OSError):
                        actor = None
                    write_audit(actor, 'request.invalid', {'request_id': request_id,
                                'object_type': 'extension', 'result': 'denied', 'error_code': 'invalid_request'})
                await run_in_threadpool(record_validation)
                return JSONResponse({'code': 'invalid_request', 'detail': 'Проверьте формат и допустимую длину полей запроса.'},
                                    status_code=422, headers={'X-Request-ID': request_id})
            except MeetError as error:
                return JSONResponse({'code': error.code, 'detail': error.detail}, status_code=error.status,
                                    headers={'X-Request-ID': request_id})
        return handle


def run(request, response, action, operation):
    # Reuse the core's validated correlation ID, or generate one on the base API.
    request_id = correlation_id(request)
    response.headers['X-Request-ID'] = request_id
    actor = None
    details = {'request_id': request_id, 'object_type': action.split('.')[0],
               'source_ids': [], 'model': None}
    failed = False
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
    except (sqlite3.Error, OSError):
        failed = True
        details.update(result='error', error_code='storage_unavailable')
        raise MeetError(503, 'storage_unavailable', 'Хранилище временно недоступно. Проверьте миграции.') from None
    except MeetError as error:
        failed = True
        details.update(result='denied' if error.status in (401, 403, 404) else 'error', error_code=error.code)
        raise
    except Exception:
        failed = True
        details.update(result='error', error_code='internal_error')
        raise
    finally:
        # A separate transaction keeps refusal audit after the operation rolls back.
        if not write_audit(actor, action, details) and not failed:
            raise MeetError(503, 'audit_unavailable', 'Не удалось записать результат в журнал. Повторите запрос позже.')
    return result
