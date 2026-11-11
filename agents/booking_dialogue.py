"""Repair non-actionable model replies using catalog facts and actual tool results.

Preferences are not field evidence. Final proposals still pass verify_action,
slot revalidation and explicit confirmation in AgentRuntime.dispatch.
"""
import re
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from providers.base import ToolCall
from providers.language import is_confirmation
from agents.booking_language import service_matches, booking_request, unknown_service, time_candidates, resolve_time

WEEKDAYS = [r'понедельник(?:а|у|ом)?', r'вторник(?:а|у|ом)?',
            r'сред(?:а|у|ы|е|ой)', r'четверг(?:а|у|ом)?',
            r'пятниц(?:а|у|ы|е|ей)', r'суббот(?:а|у|ы|е|ой)',
            r'воскресень(?:е|я|ю|ем|и)']

HOURS = {'ноль':0, 'один':1, 'час':1, 'два':2, 'две':2, 'три':3, 'трех':3, 'трёх':3,
         'четыре':4, 'пять':5, 'шесть':6, 'семь':7, 'восемь':8, 'девять':9,
         'десять':10, 'одиннадцать':11, 'двенадцать':12, 'тринадцать':13,
         'четырнадцать':14, 'пятнадцать':15, 'шестнадцать':16, 'семнадцать':17,
         'восемнадцать':18, 'девятнадцать':19, 'двадцать':20}
HOURS.update({'одного':1, 'двух':2, 'четырех':4, 'четырёх':4, 'пяти':5,
              'шести':6, 'семи':7, 'восьми':8, 'девяти':9, 'десяти':10,
              'одиннадцати':11, 'двенадцати':12})


def requested_clock(text, slots=()):
    value = re.sub(r'\b\d{4}-\d{2}-\d{2}\b', '', text.casefold())
    if re.search(r'телефон|номер|BYN|рубл|стоимость|цена', value, re.I):
        return None
    if len(re.findall(r'\d', value)) > 4:
        return None  # A formatted phone must not be mistaken for HHMM inside it.
    match = re.search(r'(?<!\d)([01]?\d|2[0-3])[:.\-]([0-5]\d)(?!\d)', value)
    if match:
        return f'{int(match[1]):02d}:{match[2]}'
    match = re.search(r'(?<!\d)([01]?\d|2[0-3])[- ]([0-5])[- ]([0-9])(?!\d)', value)
    if match:
        return f'{int(match[1]):02d}:{match[2]}{match[3]}'
    match = re.search(r'(?<!\d)([01]\d|2[0-3])([0-5]\d)(?!\d)', value)
    if match:
        return f'{int(match[1]):02d}:{match[2]}'
    numeric_hour = re.fullmatch(r'\s*(\d{1,2})(?:\s+час(?:а|ов)?)?[.!]?\s*', value) or re.search(r'\b(?:в|на|после)\s+(\d{1,2})\b', value)
    if numeric_hour and int(numeric_hour[1]) < 24:
        hour = int(numeric_hour[1])
        possibilities = sorted({s['datetime'][11:16] for s in slots
                                if int(s['datetime'][11:13]) % 12 == hour % 12
                                and (s['datetime'][14:16] == '00' or 'после' in value)})
        hours = {p[:2] for p in possibilities}
        return f'{next(iter(hours))}:00' if hour <= 12 and len(hours) == 1 else f'{hour:02d}:00' if hour > 12 else None
    words = '|'.join(sorted(HOURS, key=len, reverse=True))
    if re.fullmatch(r'\s*(?:' + words + r')(?:\s+час(?:а|ов)?)?[.!]?\s*', value):
        value = 'в ' + value
    match = re.search(r'\b(?:в|на|после)\s+(' + words + r')(?:\s+(один|два|три))?\b', value)
    if not match:
        return None
    hour = HOURS[match[1]] + (HOURS[match[2]] if match[2] and HOURS[match[1]] == 20 else 0)
    minute = 30 if re.search(r'\bтридцать\b', value) else 15 if re.search(r'\bпятнадцать\b', value[match.end():]) else 0
    if re.search(r'\b(?:дня|вечера)\b', value) and hour < 12:
        hour += 12
    elif re.search(r'\b(?:утра|ночи)\b', value):
        hour %= 12
    elif hour <= 12:
        possibilities = sorted({s['datetime'][11:16] for s in slots
                                if int(s['datetime'][11:13]) % 12 == hour % 12
                                and (int(s['datetime'][14:16]) == minute or 'после' in value)})
        hours = {p[:2] for p in possibilities}
        if 'после' in value and len(hours) == 1:
            return f'{next(iter(hours))}:{minute:02d}'
        if len(possibilities) == 1:
            return possibilities[0]
        return None
    return f'{hour:02d}:{minute:02d}'


def employee_pattern(name):
    name = name.casefold()
    if name.endswith('ия'):
        return re.escape(name[:-1]) + r'(?:я|и|ю|ей)'
    if name.endswith('а'):
        return re.escape(name[:-1]) + r'(?:а|ы|и|е|у|ой)'
    return re.escape(name)


def unsupported_variant(text, services):
    # A generic catalog entry does not establish every body area or procedure.
    pattern = r'\b(?:лобк\w*|интим\w*|бикини|пах\w*|генитал\w*|подмыш\w*)\b'
    requested = re.findall(pattern, text.casefold())
    if not requested:
        return False
    return not any(re.search(pattern, str(s.get('name', '')) + ' ' + str(s.get('description', '')), re.I) for s in services)


def weekday_date(text, today):
    days = [i for i, pattern in enumerate(WEEKDAYS) if re.search(r'\b(?:' + pattern + r')\b', text, re.I)]
    if len(days) != 1:
        return None
    day = days[0]
    if re.search(r'следующ\w*\s+недел', text, re.I):
        return today + timedelta(days=7 - today.weekday() + day)
    if re.search(r'(?:этой|текущей)\s+недел', text, re.I):
        return today + timedelta(days=day - today.weekday())
    distance = (day - today.weekday()) % 7
    if distance == 0 and re.search(r'следующ', text, re.I):
        distance = 7
    return today + timedelta(days=distance)


def booking_interruption(runtime, state, text):
    """Handle factual questions before they can be mistaken for field answers."""
    if not {'check_slots', 'create_booking'} <= runtime.tools.keys():
        return None
    knowledge=runtime.config.business.knowledge
    configured_aliases=knowledge.get('service_aliases',{})
    alias_request=any(isinstance(alias,str) and alias.casefold() in text.casefold()
        for aliases in configured_aliases.values() if isinstance(aliases,list) for alias in aliases) if isinstance(configured_aliases,dict) else False
    from agents.quick_dialogue import callback_refusal
    previous = state['transcript'][-2]['content'] if len(state['transcript']) > 1 else ''
    if (callback_refusal(text, previous.startswith('Подтвердите действие'))
            or re.search(r'\bне (?:хочу|надо|нужно|буду)\b.{0,40}(?:запис|брониров)',text,re.I)):
        state.update(pending_action=None, pending_collection=None)
        state.setdefault('declined_actions', {})['create_booking'] = True
        return 'Запись не создана. Если захотите оформить новую, скажите об этом.'
    if re.search(r'\b(?:хочу|давайте|прошу)\s+(?:снова\s+)?(?:записаться|записать|оформить)|\bпередумал[а]?\b', text, re.I):
        state.get('declined_actions', {}).pop('create_booking', None)
    if booking_request(text) or alias_request:
        return booking_fallback(runtime,state,text)
    if (unsupported_variant(text, runtime.config.business.knowledge.get('services', []))
            or state.get('booking_preferences') and (
                requested_clock(text, [s for e in state['tool_events'] for s in e['result'].get('slots', [])])
                or re.search(r'\bк\s+[а-яё]+|\bмастер', text, re.I))):
        return booking_fallback(runtime, state, text)
    requested_services = service_matches(text,knowledge)
    if len(requested_services) > 1 or requested_services and state.get('booking_preferences'):
        return booking_fallback(runtime, state, text)
    if weekday_date(text, datetime.now(ZoneInfo(runtime.config.business.timezone)).date()) is not None or re.search(r'п[еи]ди[-\s]?кюр|\bвчера\b|скид|дорого|сколько|цен[ау]|стоит|стоимость|пофиг|всё равно|все равно|ближайш|что.*свобод|мужик|мужчин|по тапку|(?:нет|без).*телефон|телефон.*нет', text, re.I):
        return booking_fallback(runtime, state, text)
    return None


def booking_fallback(runtime, state, text):
    if not {'check_slots', 'create_booking'} <= runtime.tools.keys():
        return None
    config = runtime.config
    services = config.business.knowledge.get('services', [])
    if not services:
        return None
    prefs = {}
    state['booking_preferences'] = prefs
    today = datetime.now(ZoneInfo(config.business.timezone)).date()
    # Reconstruct preferences from customer turns, never from model assertions.
    for index, message in enumerate(state['transcript']):
        if message['role'] != 'user':
            continue
        value = message['content'].casefold()
        value = re.sub(r'\bп[еи]ди[-\s]?кюр', 'педикюр', value)
        previous = state['transcript'][index - 1]['content'] if index else ''
        if is_confirmation(message['content'], config.language):
            if previous == 'На прошедшую дату записаться нельзя. Проверить ближайшее доступное время?':
                prefs.pop('date', None)
                prefs['any_date'] = True
            elif previous.endswith('Подойдёт любой доступный мастер?'):
                prefs.pop('gender', None)
                prefs.pop('employee', None)
            elif previous.endswith('Продолжить запись только на эту услугу?') and prefs.get('alternative'):
                prefs['service'] = prefs.pop('alternative')
                prefs.pop('unsupported', None)
        matches = service_matches(value,config.business.knowledge)
        if len(matches) == 1:
            service = matches[0]
            key = service.get('id', service['name'])
            for flag in ('service_options','unsupported','alternative','unsupported_detail'):
                prefs.pop(flag,None)
            prefs['service'] = key
        elif len(matches) > 1:
            prefs.pop('service', None)
            prefs['service_options'] = [s['name'] for s in matches]
        unsupported=unknown_service(value,config.business.knowledge)
        if unsupported:
            prefs.pop('service',None)
            prefs['unsupported']=unsupported
        if unsupported_variant(value, services):
            prefs['unsupported_detail'] = True
        # An unsupported named service must not silently become another service.
        if 'педикюр' in value and not any('педикюр' in s['name'].casefold() for s in services):
            prefs.clear()
            prefs['unsupported'] = 'педикюр'
            if len(matches) == 1:
                prefs['alternative'] = matches[0].get('id', matches[0]['name'])
        if re.search(r'\bвчера\b', value):
            prefs['date'] = (today - timedelta(days=1)).isoformat()
        elif re.search(r'\bпослезавтра\b', value):
            prefs['date'] = (today + timedelta(days=2)).isoformat()
        elif re.search(r'\bзавтра\b', value):
            prefs['date'] = (today + timedelta(days=1)).isoformat()
        elif re.search(r'\bсегодня\b', value):
            prefs['date'] = today.isoformat()
        else:
            day = re.search(r'\b\d{4}-\d{2}-\d{2}\b', value)
            if day:
                prefs['date'] = day[0]
            else:
                weekday = weekday_date(value, today)
                if weekday is not None:
                    prefs['date'] = weekday.isoformat()
        relative_choices=[(today+timedelta(days=offset)).isoformat() for word,offset in
                          [('вчера',-1),('сегодня',0),('завтра',1),('послезавтра',2)] if re.search(r'\b'+word+r'\b',value)]
        explicit_choices=re.findall(r'\b\d{4}-\d{2}-\d{2}\b',value)
        if 'или' in value and len(set(relative_choices+explicit_choices))>1:
            prefs.pop('date',None);prefs['date_options']=sorted(set(relative_choices+explicit_choices))
        elif relative_choices or explicit_choices or weekday_date(value,today) is not None:
            prefs.pop('date_options',None)
        if re.search(r'пофиг|всё равно|все равно|люб(?:ой|ое|ая)|ближайш|что есть|что.*свобод|без разницы|когда.*угодно', value):
            prefs['any_date'] = True
            if 'ближайш' in value:
                prefs.pop('date', None)
        if re.search(r'люб(?:ой|ого).*мастер|без предпочтений|мастер.*без разницы', value):
            prefs.pop('gender', None)
            prefs.pop('employee', None)
            prefs.pop('unknown_employee', None)
        offered = [s for e in state['tool_events'] if e['name'] == 'check_slots'
                   and e['arguments'].get('service') == prefs.get('service')
                   and (not prefs.get('date') or e['arguments'].get('date') == prefs['date'])
                   for s in e['result'].get('slots', [])]
        clock = requested_clock(value, offered)
        candidates=time_candidates(value,HOURS)
        if candidates:
            prefs['time_candidates']=candidates
            current_service=next((s for s in services if s.get('id',s['name'])==prefs.get('service')),None)
            choices=resolve_time(candidates,config,prefs.get('date',today.isoformat()),current_service) if current_service else candidates
            if len(choices)==1:clock=choices[0];prefs.pop('time_options',None)
            else:prefs['time_options']=choices;clock=None;prefs.pop('time',None)
        elif prefs.get('time_candidates') and matches and len(matches)==1:
            choices=resolve_time(prefs['time_candidates'],config,prefs.get('date',today.isoformat()),matches[0])
            if len(choices)==1:clock=choices[0];prefs.pop('time_options',None)
        if clock:
            prefs['time'] = clock
            if re.search(r'\bпосле\b', value):
                prefs['after_time'] = clock
            else:
                prefs.pop('after_time', None)
        choosing_employee = ('мастер' in value or 'предпочтение по мастеру' in previous.casefold()
                             or re.search(r'\bк\s+\w+', value)
                             or 'мастера:' in previous.casefold() and len(value.split()) <= 6
                             or previous.endswith('Кого выбираете?'))
        employee_matches = [e for s in services for e in s['employees']
                            if choosing_employee and re.search(r'\b' + employee_pattern(employee_name(config, e)) + r'\b', value)]
        if len(set(employee_matches)) == 1:
            prefs['employee'] = employee_matches[0]
            prefs.pop('unknown_employee', None)
        elif choosing_employee:
            candidate = re.search(r'\b(?:к|мастер(?:у|а)?)\s+([а-яёa-z]+)\b', value)
            if candidate and candidate[1] not in {'вам', 'тебе', 'мастеру', 'мужик', 'мужчине', 'женщине', 'любому', 'доступному'}:
                prefs['unknown_employee'] = candidate[1]
        if re.search(r'\b(?:мужик\w*|мужчин\w*|мужск\w*)\b', value):
            prefs['gender'] = 'male'
    if prefs.get('unsupported_detail'):
        return 'Такой разновидности услуги нет в опубликованном каталоге. Доступны: ' + ', '.join(s['name'] for s in services) + '. Какую услугу выбираете?'
    if prefs.get('unsupported'):
        if prefs.get('alternative'):
            alternative = next(s for s in services if s.get('id', s['name']) == prefs['alternative'])
            return f"Педикюра нет в опубликованном каталоге. Доступна услуга «{alternative['name']}». Продолжить запись только на эту услугу?"
        return ('Педикюра' if prefs['unsupported']=='педикюр' else f'Услуги «{prefs["unsupported"]}»') + ' нет в опубликованном каталоге. Доступны: ' + ', '.join(s['name'] for s in services) + '. Какую услугу выбираете?'
    if prefs.get('service_options'):
        return 'В одном разговоре оформляем одну услугу. С какой начнём: ' + ', '.join(prefs['service_options']) + '?'
    service = next((s for s in services if s.get('id', s['name']) == prefs.get('service')), None)
    if service is None:
        return None
    if prefs.get('date_options'):
        return 'Уточните дату: ' + ' или '.join(prefs['date_options']) + '?'
    value = text.casefold()
    if state.get('declined_actions', {}).get('create_booking') and not re.search(r'цен|стоит|стоимость|сколько', value):
        return 'Запись не создана. Если захотите оформить новую, скажите об этом.'
    if prefs.get('employee') and prefs['employee'] not in service['employees']:
        names = ', '.join(employee_name(config, key) for key in service['employees'])
        return f"{employee_name(config, prefs['employee'])} не оказывает услугу «{service['name']}» по каталогу. Доступные мастера: {names}. Кого выбираете?"
    if prefs.get('unknown_employee'):
        names = ', '.join(employee_name(config, key) for key in service['employees'])
        return f"Такого мастера нет в опубликованном каталоге. Для услуги «{service['name']}» доступны: {names}. Кого выбираете?"
    if re.search(r'\bвчера\b', value):
        return 'На прошедшую дату записаться нельзя. Проверить ближайшее доступное время?'
    if re.search(r'скид|дорого|сколько|цен[ау]|стоит|стоимость', value):
        # No discount action exists in this runtime. Do not invent eligibility.
        answer = (f"Стоимость услуги «{service['name']}» — {service['price']} {service['currency']}. "
                + ('Я не могу назначить скидку. Условия нужно уточнить у сотрудника.'
                   if re.search(r'скид|дорого', value) else '')).strip()
        missing = next((f for f in config.fields if f.required and 'user' in f.allowed_sources
                        and f.id not in state['collected_fields']), None)
        if missing and state.get('pending_collection'):
            answer += ' ' + missing.question
        return answer
    try:
        requested_day = datetime.fromisoformat(prefs.get('date', today.isoformat())).date()
    except ValueError:
        return 'Не удалось разобрать дату. Назовите день или скажите «ближайшее свободное время».'
    if requested_day < today:
        return 'На прошедшую дату записаться нельзя. Проверить ближайшее доступное время?'
    if prefs.get('gender'):
        # Gender is an explicit business fact, never inferred from a person's name.
        employees = config.business.knowledge.get('employees', [])
        eligible = [e['id'] for e in employees if isinstance(e, dict)
                    and e.get('gender') == prefs['gender'] and e.get('id') in service['employees']]
        if not eligible:
            return 'В каталоге нет подтверждённых сведений о мастере-мужчине для этой услуги. Подойдёт любой доступный мастер?'
        prefs['employee'] = eligible[0]
    if re.search(r'\b(?:нет|без|не имею)\b.*(?:телефон|номер)|(?:телефон|номер).*\bнет\b|по тапку', value):
        return 'Номер звонящего здесь недоступен. Для записи нужен контактный телефон. Можно назвать другой номер или обратиться к сотруднику.'
    day = prefs.get('date')
    if not day:
        if not prefs.get('any_date'):
            if state['transcript'][-2]['content'].startswith('Какой день вам подходит?'):
                return 'Можно назвать день словами: например, «завтра» или «в пятницу». Либо скажите «ближайшее свободное время».'
            return 'Какой день вам подходит? Можно выбрать ближайшее свободное время.'
        day = today.isoformat()
    events = [e for e in state['tool_events'] if not state.get('booking_calendar_refresh') and e['name'] == 'check_slots'
              and e['arguments'].get('service') == prefs['service']
              and (not prefs.get('date') or e['arguments'].get('date') == day)
              and (not prefs.get('employee') or e['arguments'].get('employee') == prefs['employee'])
              and 'slots' in e['result']]
    checked_now=not events
    if not events:
        for offset in range(7 if prefs.get('any_date') and not prefs.get('date') else 1):
            target = (datetime.fromisoformat(day).date() + timedelta(days=offset)).isoformat()
            args = {'service': prefs['service'], 'date': target}
            if prefs.get('employee'):
                args['employee'] = prefs['employee']
            data, answer = runtime.dispatch(ToolCall(uuid.uuid4().hex, 'check_slots', args), state)
            if 'error' in data:
                # One bounded retry of a read-only availability check, never a write retry.
                data, answer = runtime.dispatch(ToolCall(uuid.uuid4().hex, 'check_slots', args), state)
            if 'error' in data:
                return 'Не удалось проверить расписание: ' + data['error']
            state.pop('booking_calendar_refresh',None)
            if data.get('slots'):
                if not prefs.get('time') and not prefs.get('time_options'):
                    return answer
                events=[state['tool_events'][-1]]
                break
        if not events:
            return 'В ближайшие проверенные дни свободных слотов нет. Какую другую дату проверим?'
    slots = events[-1]['result']['slots']
    if prefs.get('time_options'):
        return 'Уточните время: ' + ' или '.join(prefs['time_options']) + '?'
    if prefs.get('after_time'):
        later = sorted({s['datetime'][11:16] for s in slots if s['datetime'][11:16] > prefs['after_time']})
        if later:
            prefs['time'] = later[0]
    selected = [s for s in slots if s['datetime'][11:16] == prefs.get('time')
                and (not prefs.get('employee') or s['employee'] == prefs['employee'])]
    if not selected:
        if not slots:
            return 'На эту дату свободных слотов нет. Какую другую дату проверим?'
        clocks=list(dict.fromkeys(s['datetime'][11:16] for s in slots))
        if prefs.get('time'):
            requested=int(prefs['time'][:2])*60+int(prefs['time'][3:])
            clocks.sort(key=lambda clock:abs(int(clock[:2])*60+int(clock[3:])-requested))
        options=', '.join(sorted(clocks[:4])) + ('; есть и другое время' if len(clocks)>4 else '')
        if prefs.get('time'):
            return f"На {prefs['time']} подходящего свободного слота нет. На {events[-1]['arguments']['date']} доступны: {options}. Какое время выбираете?"
        if not requested_clock(text, slots) and state['transcript'][-2]['content'].endswith('Какое время выбираете?'):
            return f'Не смогла разобрать выбранное время. Доступны: {options}. Назовите одно время, например «15:00» или «пятнадцать часов».'
        return f"На {events[-1]['arguments']['date']} доступны: {options}. Какое время выбираете?"
    slot = selected[0]
    known = state['collected_fields']
    missing = next((f for f in config.fields if f.required and 'user' in f.allowed_sources and f.id not in known), None)
    if missing:
        if checked_now:
            return f"На услугу «{service['name']}» {slot['datetime'][:10]} в {slot['datetime'][11:16]} есть свободное время. " + missing.question
        return missing.question
    args = {k: known[k]['value'] for k in ('customer_name', 'phone') if k in known}
    args.update({k: slot[k] for k in ('service', 'datetime', 'employee')})
    args['additional_fields'] = {f.id: known[f.id]['value'] for f in config.fields
                                if f.id in known and f.id not in args}
    data, answer = runtime.dispatch(ToolCall(uuid.uuid4().hex, 'create_booking', args), state)
    if 'error' in data and 'слот' in data['error'].casefold():state['booking_calendar_refresh']=True
    return answer or ('Не удалось подготовить запись: ' + data.get('error', 'уточните данные'))


def update_booking_flow(state,config):
    if not {'check_slots','create_booking'} <= {tool.name for tool in config.tools}:return
    prefs=state.get('booking_preferences',{})
    if state.get('privacy',{}).get('status')=='pending':step='consent'
    elif state['status'] in {'completed','stopped','escalated'}:step=state['status']
    elif state.get('pending_action'):step='confirmation'
    elif not prefs.get('service') or prefs.get('unsupported') or prefs.get('service_options'):step='service'
    elif not prefs.get('date') and not prefs.get('any_date'):step='date'
    elif prefs.get('unknown_employee'):step='employee'
    elif state.get('booking_calendar_refresh'):step='calendar_retry'
    elif not prefs.get('time') or prefs.get('time_options'):step='time'
    else:
        missing=next((field for field in config.fields if field.required and 'user' in field.allowed_sources
                      and field.id not in state['collected_fields']),None)
        step='field:'+missing.id if missing else 'proposal'
    state['booking_flow']={'step':step}


def employee_name(config, key):
    return next((e.get('name', key) for e in config.business.knowledge.get('employees', [])
                 if isinstance(e, dict) and e.get('id') == key), key)
