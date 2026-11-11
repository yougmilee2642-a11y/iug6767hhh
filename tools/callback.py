"""Confirmed callback + optional atomic Telegram outbox; no direct network call."""
import json
import uuid
from datetime import datetime, timezone
import storage
from tools.base import BusinessTool, ToolResult
from services.telegram_store import enqueue_callback


def validate_callback_dependencies(config):
    fields = {f.id: f for f in config.fields}
    required = {'customer_name', 'phone', 'request_details'}
    if not required <= fields.keys():
        return ['Приём обращения требует имя, телефон и причину обращения']
    if any(fields[name].allowed_sources != ['user'] or not fields[name].required for name in required):
        return ['Контакт и причина обращения должны быть обязательными полями от пользователя']
    return []


def callback_tool():
    def prepare(arguments, context):
        # Runtime checks complete user provenance before presenting confirmation.
        return ToolResult(dict(arguments))

    def execute(arguments, context):
        with storage.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS callback_requests (interaction_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL)')
            existing = db.execute('SELECT payload FROM callback_requests WHERE interaction_id=?', (context.interaction_id,)).fetchone()
            if existing:
                saved = json.loads(existing[0])
            else:
                saved = {**arguments, 'callback_id': str(uuid.uuid4())}
                db.execute('INSERT INTO callback_requests VALUES (?,?,?,?)',
                           (context.interaction_id, context.config.id, json.dumps(saved, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))
            queued = enqueue_callback(db, saved, context)
        return ToolResult({'structured_data': saved, 'action_result': saved, 'intent': 'Обратный звонок'},
                          status='completed', text=('Обращение сохранено в Callwise и поставлено в очередь Telegram. Отправка ещё не подтверждена.' if queued
                            else 'Обращение сохранено в Callwise. Автоматическая доставка владельцу пока не подключена.'))

    return BusinessTool('save_callback_request', 'Сохранить подтверждённое обращение. Если владелец настроил получателя, поставить в очередь Telegram. Не обещает доставку, срок ответа или выполненную услугу.',
        {'type': 'object', 'properties': {key: {'type': 'string'} for key in ('customer_name', 'phone', 'request_details')},
         'required': ['customer_name', 'phone', 'request_details'], 'additionalProperties': False},
        execute, prepare, read_only=False, requires_confirmation=True, risk_level='medium',
        required_capabilities=('call_intake',), action_fields=('customer_name', 'phone', 'request_details'),
        source_constraints={key: ('user',) for key in ('customer_name', 'phone', 'request_details')},
        action_label='сохранить обращение для обратного звонка')
