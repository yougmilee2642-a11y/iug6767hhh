"""Compact, deterministic summary of verified intake fields; no extra model call."""


def intake_summary(state):
    if state.get('agent_config', {}).get('business', {}).get('knowledge', {}).get('track1_quick') is not True:
        return None
    fields = state.get('action_result') or state.get('structured_data', {})
    if state.get('status') == 'completed' and fields.get('callback_id'):
        prefix = 'Подтверждённое обращение.'
    elif state.get('status') == 'escalated':
        prefix = 'Запрос на связь с человеком.'
    else:
        prefix = 'Незавершённое обращение.'
    lines = [prefix]
    if fields.get('customer_name'):
        lines.append(f"Клиент: {fields['customer_name']}.")
    if fields.get('phone'):
        lines.append(f"Телефон: {fields['phone']}.")
    if fields.get('request_details'):
        lines.append('Запрос: ' + str(fields['request_details']))
    from services.telegram_store import delivery
    status = delivery(state['id'])['status']
    lines.append({'pending':'Telegram: ожидает отправки.', 'retry':'Telegram: ожидает повторной попытки.',
                  'sending':'Telegram: отправляется.', 'sent':'Telegram: доставлено в чат (чтение не подтверждено).',
                  'failed':'Telegram: ошибка отправки.', 'unknown':'Telegram: результат отправки неизвестен; автоматического повтора нет.',
                  'cancelled':'Telegram: отправка отменена.'}.get(status,'Автоматическая доставка не подключена.'))
    return ' '.join(lines)
