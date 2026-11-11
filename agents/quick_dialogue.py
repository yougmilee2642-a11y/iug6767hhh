"""Questions and refusals take priority over short-wizard contact collection."""
import re

CALLBACK_DECLINED = 'Обращение не сохранено. Можете задать вопрос о компании.'


def phone_refusal(text):
    return bool(re.search(r'(?:не буду|не хочу|отказываюсь|не стану).{0,35}(?:телефон|номер)|(?:телефон|номер).{0,35}(?:не буду|не хочу|не дам|не сообщу)|\bнет (?:телефона|номера)\b', text, re.I))


def callback_refusal(text, pending=False):
    value = text.casefold().strip()
    if re.search(r'\bне\s+(?:сохраняйте|сохраняй|записывайте|записывай|оформляйте|оформляй)\b', value):
        return True
    return pending and bool(re.fullmatch(r'\s*(?:нет|не подтверждаю|отказываюсь)[.!\s]*', value))


def quick_interruption(runtime, state, text):
    config = runtime.config
    if config.business.knowledge.get('track1_profile') not in {'secretary', 'support'}:
        return None
    value = text.casefold()
    if 'save_callback_request' in runtime.tools:
        if phone_refusal(text):
            state.update(pending_action=None, pending_collection=None, status='active')
            state.setdefault('declined_actions', {})['save_callback_request'] = True
            return 'Без контактного телефона я не могу сохранить обращение для обратного звонка. ' + CALLBACK_DECLINED
        pending = state.get('pending_action', {}).get('name') if state.get('pending_action') else None
        if callback_refusal(text, pending == 'save_callback_request'):
            state.update(pending_action=None, pending_collection=None, status='active')
            state.setdefault('declined_actions', {})['save_callback_request'] = True
            return CALLBACK_DECLINED
        if state.get('declined_actions', {}).get('save_callback_request'):
            if re.search(r'\b(?:хочу|прошу|давайте)\s+(?:снова\s+)?(?:оформить|сохранить|обратный звонок)|\b(?:передумал|передумала|сохраните обращение)\b', value):
                state['declined_actions'].pop('save_callback_request', None)
            elif re.search(r'\b(?:мой телефон|мой номер|меня зовут)\b', value):
                return CALLBACK_DECLINED
    if re.search(r'представьтесь|представься|\bкто (?:вы|ты)\b|(?:ваш[ау]|тво[яю]) роль', value):
        return f'Я AI-помощница компании «{config.business.name}». Моя роль — {config.role.name}. {config.role.description}'
    canonical = re.sub(r'[^\w\s]', '', value).strip()
    for qa in config.business.knowledge.get('qa', []):
        question = re.sub(r'[^\w\s]', '', qa.get('question', '').casefold()).strip()
        if question and canonical == question:
            return qa['answer']
    if re.search(r'телефонн\w* звон|обычн\w* звон|телефони', value):
        if config.business.knowledge.get('channel_status', {}).get('telephony') == 'not_connected':
            return 'Сейчас доступен веб-тест. Обычные телефонные звонки и реальное соединение с сотрудником не подключены.'
    if re.search(r'\b(?:запишите|запиши|забронируйте|забронируй)\b', value) and 'create_booking' not in runtime.tools:
        return 'Календарь не подключён: я не могу проверить свободное время или подтвердить запись. Могу принять обращение для сотрудника.'
    return None
