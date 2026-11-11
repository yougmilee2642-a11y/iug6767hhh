"""Server-owned guardrails. Intent patterns are conservative, not a semantic safety oracle."""
import os
import re
from datetime import datetime, timezone

TERMINAL = {'completed', 'escalated', 'stopped'}


def enabled():
    return os.getenv('CALLWISE_CONVERSATION_SAFETY', 'true').lower() == 'true'


def stamp():
    return datetime.now(timezone.utc).isoformat()


def notice(config):
    return config.safety.notice or (
        f'Это AI-помощник компании «{config.business.name}», а не человек. Это тестовая версия: используйте вымышленные данные. '
        'Текст разговора и подтверждённые данные обращения сохраняются в Callwise. '
        'При подключённой CRM/календаре данные подтверждённой записи передаются туда; настроенные уведомления могут передавать данные владельцу. '
        'Голос обрабатывается распознаванием; исходная аудиозапись этим прототипом не архивируется. '
        'До начала разговора выберите согласие или отказ. Без согласия микрофон и приём обращения не включаются. '
        'Это техническое согласие на демо, не утверждённая юридическая политика бизнеса.')


def initialize(state, config):
    if not enabled(): return
    state['safety'] = {'enabled': True, 'turns': 0, 'off_topic': 0, 'abuse': 0, 'events': []}
    state['privacy'] = {'status': 'pending' if config.safety.privacy_required else 'not_required',
                        'notice': notice(config), 'version': config.safety.notice_version, 'decision_at': None}
    if config.safety.privacy_required:
        state['transcript'] = [{'role': 'assistant', 'content': state['privacy']['notice']}]
        state['llm_history'] = []
        state['pending_collection'] = None


def accepted(state):
    return not state.get('safety', {}).get('enabled') or state.get('privacy', {}).get('status') in {'accepted', 'not_required'}


def consent(state, config, decision, version):
    privacy = state.get('privacy')
    if not privacy or privacy.get('version') != version:
        raise ValueError('Уведомление изменилось. Начните новый разговор.')
    if decision:
        if privacy['status'] == 'accepted': return
        if privacy['status'] != 'pending' or state['status'] in TERMINAL:
            raise ValueError('Нельзя возобновить закрытый разговор. Начните новый.')
        privacy.update(status='accepted', decision_at=stamp())
        state['transcript'] = [{'role': 'assistant', 'content': config.greeting}]
        state['llm_history'] = [{'role': 'assistant', 'text': config.greeting, 'calls': [], 'call_id': None, 'result': None}]
        state['pending_collection'] = None
        for field in config.fields:
            if 'user' in field.allowed_sources and config.greeting.endswith(field.question):
                state['pending_collection'] = {'field_id': field.id, 'question_index': 0}
                break
    else:
        was_accepted = privacy['status'] == 'accepted'
        privacy.update(status='withdrawn' if was_accepted else 'declined', decision_at=stamp())
        # Confirmed business records are not deleted automatically: separate owner/legal review is required.
        has_action = any(event.get('confirmed') and event.get('name') != 'check_slots' for event in state['tool_events'])
        state.update(status='stopped', pending_action=None, pending_collection=None,
                     result='Обработка разговора остановлена. Новые действия не выполняются.' +
                     (' Ранее подтверждённые записи требуют отдельной проверки владельцем.' if has_action else ' Заявка не создана.'))
        if not has_action:
            state.update(customer_name=None, phone=None, summary='', structured_data={}, collected_fields={},
                         action_provenance={}, action_result={}, tool_events=[], transcript=[], llm_history=[], escalation=None)
            state.pop('brief_summary', None)
        state.pop('last_response', None)
        state.pop('last_request_id', None)
        from services.privacy_actions import cancel_pending
        cancel_pending(state['id'])


def audit(state, code):
    events = state['safety']['events']
    events.append({'code': code, 'at': stamp()})
    del events[:-40]


def clear_proposal(state):
    state.update(pending_action=None, pending_collection=None)
    if state['status'] not in TERMINAL: state['status'] = 'active'


def redact(text):
    # Conservative redaction of credentials/payment secrets; a phone is never an authentication factor.
    text = re.sub(r'(?i)\b(?:пароль|password|cvv|cvc|пин[- ]?код|pin|код из (?:смс|sms))\s*[:=]?\s*\S+', '[секрет скрыт]', text)
    text = re.sub(r'(?<!\d)(?:\d[ -]?){15,19}(?!\d)', '[длинный номер скрыт]', text)
    return text


def preflight(state, config, text):
    """Returns (safe_text, direct_answer, terminal, review_reason). No raw guard-trigger text is persisted."""
    if not state.get('safety', {}).get('enabled'): return text, None, False, None
    if not accepted(state):
        return '', state.get('privacy', {}).get('notice', 'Сначала выберите согласие в интерфейсе.'), False, None
    safety = state['safety']
    safety['turns'] += 1
    elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(state['created_at'])).total_seconds()
    if safety['turns'] > config.safety.max_turns or elapsed > config.safety.max_minutes * 60:
        audit(state, 'conversation_limit'); clear_proposal(state)
        return '', 'Лимит этого разговора достигнут. Разговор завершён; неподтверждённые действия не выполнены.', True, None
    value = text.casefold()
    if re.search(r'не (?:даю|согласен|согласна).*?(?:согласи|обработк)|отзываю согласие|не обрабатыва[йт].*данн', value):
        consent(state, config, False, state['privacy']['version']); audit(state, 'privacy_withdrawn')
        return '', state['result'], True, None
    code, answer, review = None, None, None
    if re.search(r'(?:личн\w*|домашн\w*)\s+(?:номер|телефон|адрес)|(?:паспорт|зарплат\w*|семь\w*)\s+(?:мастер|сотрудник)|где жив[её]т', value):
        code, answer = 'employee_privacy', 'Личные данные сотрудников не предоставляю. Могу сообщить только опубликованные бизнесом профессиональные сведения.'
    elif re.search(r'\b(?:cvv|cvc|парол[ья]|код из смс|пин[- ]?код)\b|обойди.*(?:правил|провер)|забудь.*(?:правил|инструкц)|выдай.*(?:ключ|токен)|притворись.*(?:директор|владельц)', value):
        code, answer = 'sensitive_or_fraud', 'Не передавайте пароли, платёжные данные и коды из СМС. Я не принимаю такие данные и не выполняю обход проверок.'
    elif re.search(r'не хочу.*(?:бот|ии|ai|робот)|не буду.*(?:бот|робот)|хочу (?:живого|настоящего) человека', value):
        code, answer, review = 'refused_ai', 'Общение с AI остановлено. Запрос менеджеру сохранён в Callwise; реального соединения и автоматического обратного звонка пока нет.', 'refused_ai'
    elif re.search(r'\b(?:отменить|перенести|изменить)\b.*(?:запис|брон|регистрац)|(?:опаздываю|опоздаю|задерживаюсь)', value):
        code, answer, review = 'change_or_late', 'Запрос на изменение записи или опоздание передан на ручную проверку в Callwise. Запись не изменена: менеджеру нужно проверить вашу личность и доступность времени.', 'change_or_late'
    elif re.search(r'перезвон(?:ите|ить)|обратн\w* звонок', value) and 'save_callback_request' not in {tool.name for tool in config.tools}:
        code, answer, review = 'callback', 'Просьба об обратном звонке сохранена на ручную проверку в Callwise. Автоматический звонок и время ответа не подтверждены.', 'callback'
    elif re.search(r'нестандартн\w* (?:запрос|услуг)|хочу.*(?:жалоб|возврат)|хочу услугу.*нет.*(?:каталог|списк)', value):
        code, answer, review = 'unsupported', 'Этот запрос требует решения сотрудника. Он сохранён на ручную проверку в Callwise; услуга, возврат или соединение с человеком не выполнены.', 'unsupported'
    elif re.search(r'(?:запис|запиш)\w*\s+(?:нас|двоих|троих|двух|трех|трёх)|(?:меня|мне)\s+и\s+(?:друга|подруг|жен|муж|сын|доч)', value):
        code, answer = 'multiple_customers', 'В текущей версии оформляем одного человека за разговор. Для остальных начните отдельный разговор: не будем смешивать имена и записи.'
    elif re.search(r'говор(?:и|ите).*?(?:английск|польск|немецк)|\b(?:speak english|english please)\b', value) or (len(re.findall(r'[a-z]', value)) > 20 and len(re.findall(r'[а-яё]', value)) < 3):
        code, answer = 'unsupported_language', 'Сейчас голосовой сценарий поддерживает русский язык. Продолжите по-русски или обратитесь к сотруднику; перевод на другие языки пока не подключён.'
    elif re.search(r'опыт|специализац|квалификац|расскаж.*мастер|характеристик.*мастер', value):
        code = 'employee_profile'
        employee = next((item for item in config.business.knowledge.get('employees', [])
                         if isinstance(item, dict) and item.get('name', '').casefold() in value and item.get('name')), None)
        profile = employee.get('public_profile', {}) if employee else {}
        if employee and isinstance(profile, dict) and profile.get('approved') is True:
            details = [profile[key] for key in ('specialization', 'experience', 'qualification')
                       if isinstance(profile.get(key), str) and profile[key].strip()]
            answer = employee['name'] + ': ' + '; '.join(item[:300] for item in details) if details else 'Подтверждённых профессиональных сведений пока нет.'
        else:
            answer = 'Подтверждённого публичного профиля этого сотрудника пока нет. Уточните у бизнеса; личные сведения не предоставляю.'
    elif re.search(r'(?:ты|вы).*(?:бот|робот|человек)|можно.*доверять|кто (?:ты|вы)', value):
        code, answer = 'identity', f'Я AI-помощница компании «{config.business.name}». Моя роль — {config.role.name}. {config.role.description} Не выполняю действия без подтверждения.'
    elif re.search(r'расскажи.*анекдот|какая погода|поговорим о политике|реши.*(?:интеграл|уравнение)', value):
        safety['off_topic'] += 1
        code, answer = 'off_topic', 'Я помогаю только по вопросам этого бизнеса. Вернёмся к вашему обращению?'
        if safety['off_topic'] >= config.safety.off_topic_limit:
            answer = 'Разговор неоднократно ушёл от темы бизнеса. Завершаю его; неподтверждённые действия не выполнены.'
    elif re.search(r'\b(?:идиот|дебил|сука|мудак)\b', value):
        safety['abuse'] += 1
        code, answer = 'abuse', 'Помогу по вопросу бизнеса. Пожалуйста, продолжим без оскорблений.'
        if safety['abuse'] >= config.safety.abuse_limit:
            answer = 'Разговор завершён из-за повторных оскорблений. Неподтверждённые действия не выполнены.'
    if code:
        audit(state, code); clear_proposal(state)
        terminal = bool(review) or code == 'off_topic' and safety['off_topic'] >= config.safety.off_topic_limit or code == 'abuse' and safety['abuse'] >= config.safety.abuse_limit
        return redact(text) if review else '[системная отметка: ' + code + ']', answer, terminal, review
    return redact(text), None, False, None
