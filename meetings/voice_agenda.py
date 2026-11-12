"""«Фокус» о расписании и делах: встречи, задачи, сроки, решения, документы.

Только чтение. Каждая выборка идёт через те же правила доступа, что и экраны прототипа
(store.accessible_meeting_ids, management.visible_tasks, decisions.visible,
store.accessible_document_ids). Ответ возвращает id показанных объектов, чтобы голосовой
слой мог решить, можно ли произнести его вслух при остальных участниках.
"""
import json
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from meetings import store

ZONE = ZoneInfo(store.DISPLAY_ZONE)
SPOKEN_ITEMS = 3
WEEKDAYS = ('понедельник', 'вторник', 'среду', 'четверг', 'пятницу', 'субботу', 'воскресенье')
WEEKDAYS_NOM = ('понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота', 'воскресенье')
MONTHS = ('января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября',
          'октября', 'ноября', 'декабря')

MEETING_CUE = re.compile(r'встреч|совещани|созвон|планерк|планёрк|расписани|календар|'
                         r'что\s+у\s+(?:меня|нас)\s+(?:сегодня|завтра|послезавтра|на\s+(?:этой\s+|следующей\s+)?недел)|'
                         r'чем\s+я\s+занят|какие\s+(?:у\s+меня\s+)?планы', re.I)
PEOPLE_CUE = re.compile(r'кто\s+(?:будет|был|была|были|участвует|участвовал|идет|идёт|придет|придёт|приглашен|приглашён|там)|'
                        r'участник|состав', re.I)
MY_TASKS = re.compile(r'мои\s+(?:задач|поручени|дела)|у\s+меня\s+(?:задач|поручени|дел)|на\s+мне|'
                      r'(?:мне|я)\s+(?:нужно|надо|должен|должна)\s+(?:сделать|успеть|сдать)|что\s+мне\s+(?:делать|сделать)|'
                      r'мой\s+список', re.I)
DEADLINES = re.compile(r'срок(?:и|ов)?\b|дедлайн|что\s+(?:горит|сдать|сдавать)|ближайш\w*\s+(?:срок|задач)', re.I)
PERSON_TASKS = re.compile(r'(?:задач\w*|поручени\w*|дела)\s+(?:у\s+)?([А-ЯЁа-яё]+(?:\s+[А-ЯЁа-яё]+)?)|'
                          r'что\s+(?:делает|должен|должна|поручили|на)\s+([А-ЯЁа-яё]+(?:\s+[А-ЯЁа-яё]+)?)|'
                          r'(?-i:([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?))\s+(?:задач|поручени)', re.I)
# Те же три формы по отдельности: у каждой свой кандидат на имя.
PERSON_PATTERNS = (
    re.compile(r'(?:задач\w*|поручени\w*|дела)\s+(?:у\s+)?([А-ЯЁа-яё]+(?:\s+[А-ЯЁа-яё]+)?)', re.I),
    re.compile(r'что\s+(?:делает|должен|должна|поручили|на)\s+([А-ЯЁа-яё]+(?:\s+[А-ЯЁа-яё]+)?)', re.I),
    re.compile(r'([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)\s+(?:задач|поручени)'),
)
DECISIONS = re.compile(r'решени\w*\s+на\s+контрол|какие\s+(?:у\s+нас\s+)?решени|что\s+(?:мы\s+)?(?:решили|постановили)|'
                       r'на\s+чем\s+(?:мы\s+)?(?:договорились|остановились)|о\s+ч[её]м\s+договорились', re.I)
DOCUMENTS = re.compile(r'(?:какие|новые|последние|свежие|недавние)\s+(?:у\s+нас\s+)?документ|список\s+документ|'
                       r'что\s+нового\s+в\s+документ|сколько\s+(?:у\s+нас\s+)?документ', re.I)
DOCUMENT_HINT = re.compile(r'регламент|договор|инструкц|положени|политик|прайс|в\s+файл|в\s+документе', re.I)


# ---------- время ----------
def local_day(value):
    moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ZONE)
    return moment.astimezone(ZONE)


def day_range(text, today):
    """(начало, конец включительно, подпись) или None, если период не назван."""
    t = text.casefold()
    if 'послезавтра' in t:
        day = today + timedelta(days=2); return day, day, 'послезавтра'
    if 'завтра' in t:
        day = today + timedelta(days=1); return day, day, 'завтра'
    if 'вчера' in t:
        day = today - timedelta(days=1); return day, day, 'вчера'
    if 'сегодня' in t or 'на сегодня' in t:
        return today, today, 'сегодня'
    if re.search(r'следующ\w*\s+недел', t):
        start = today + timedelta(days=7 - today.weekday()); return start, start + timedelta(days=6), 'на следующей неделе'
    if 'недел' in t:
        start = today - timedelta(days=today.weekday()); return today, start + timedelta(days=6), 'на этой неделе'
    for index, name in enumerate(WEEKDAYS):
        if re.search(rf'\b(?:в|во|на)\s+{name[:-1]}', t) or name in t:
            ahead = (index - today.weekday()) % 7
            day = today + timedelta(days=ahead); return day, day, f'в {name}'
    return None


def spoken_day(day, today, weekday=True):
    if day == today:
        return 'сегодня'
    if day == today + timedelta(days=1):
        return 'завтра'
    if day == today - timedelta(days=1):
        return 'вчера'
    short = f'{day.day} {MONTHS[day.month - 1]}'
    return f'{WEEKDAYS_NOM[day.weekday()]}, {short}' if weekday and abs((day - today).days) < 7 else short


def plural(n, one, few, many):
    n = abs(n) % 100
    d = n % 10
    return many if 10 < n < 20 else one if d == 1 else few if 2 <= d <= 4 else many


def listing(items, more_noun):
    """«А, Б и В» вслух, остальное — на экране."""
    head = items[:SPOKEN_ITEMS]
    text = head[0] if len(head) == 1 else ', '.join(head[:-1]) + ' и ' + head[-1]
    rest = len(items) - len(head)
    return text + (f'. Ещё {rest} {more_noun(rest)} — на экране' if rest else '')


# ---------- выборки с учётом прав ----------
def visible_meetings(connection, user_id):
    ids = store.accessible_meeting_ids(connection, user_id, model=True)
    if not ids:
        return []
    rows = connection.execute(f'SELECT * FROM meetings WHERE id IN ({",".join("?" * len(ids))})', ids).fetchall()
    return [dict(row) for row in rows]


def visible_tasks(connection, user_id):
    from meetings.management.service import visible_tasks as tasks
    rows = tasks(connection, user_id)
    titles = {m['id']: m['title'] for m in visible_meetings(connection, user_id)}
    for row in rows:
        row['meeting_title'] = titles.get(row['meeting_id'], '')
    return rows


def roster(connection):
    return [dict(row) for row in connection.execute('SELECT id, name FROM users WHERE active=1')]


def assigned_to(task, person, people):
    """Задача на человеке: по id, по полному имени или по однозначному имени без фамилии."""
    if task.get('assignee_user_id') == person['id']:
        return True
    name = ' '.join(str(task.get('assignee') or '').split()).casefold()
    if not name:
        return False
    full = person['name'].casefold()
    if name == full:
        return True
    first = full.split(' ')[0]
    same_first = [p for p in people if p['name'].casefold().split(' ')[0] == first]
    return name == first and len(same_first) == 1


def find_person(connection, words):
    """Сотрудник по имени/фамилии из вопроса; None, если не найден или неоднозначен."""
    people = roster(connection)
    # Основа без падежного окончания: «Анны»→«анн», «Морозовой»→«морозо», «Дениса»→«ден».
    stems = [w.casefold()[:max(3, min(len(w) - 2, 6))] for w in re.findall(r'[А-ЯЁа-яё]{3,}', words)]
    matches = {}
    for person in people:
        parts = [p.casefold().replace('ё', 'е') for p in person['name'].split()]
        if any(part.startswith(stem.replace('ё', 'е')) for stem in stems for part in parts):
            matches[person['id']] = person
    return next(iter(matches.values())) if len(matches) == 1 else None


def open_task(task):
    return task['status'] not in ('done', 'cancelled')


def due_day(task):
    try:
        return date.fromisoformat(str(task.get('due') or '')[:10])
    except ValueError:
        return None


def match_meeting(meetings, text):
    """Встреча, чьё название лучше всего совпадает со словами вопроса (≥ 2 общих основы)."""
    # Основы из 4 букв переживают падежи: «итогам»/«итоги» → «итог», «картона»/«картон» → «карт».
    stop = {'встр', 'кото', 'сего', 'завт', 'фото', 'буде', 'какие', 'како', 'когд', 'учас', 'решил', 'реши'}
    stems = {w.casefold()[:4] for w in re.findall(r'[А-ЯЁа-яё]{4,}', text)} - stop
    best, score = None, 1
    for meeting in meetings:
        title = {w.casefold()[:4] for w in re.findall(r'[А-ЯЁа-яё]{4,}', meeting['title'] + ' ' + meeting['topic'])} - stop
        overlap = len(stems & title)
        if overlap > score or (overlap == score and best is None and overlap >= 2):
            best, score = meeting, overlap
    return best


# ---------- ответы ----------
def meetings_answer(connection, user, text, now):
    today = now.astimezone(ZONE).date()
    rows = [m for m in visible_meetings(connection, user['id']) if m.get('scheduled_at')]
    rows.sort(key=lambda m: m['scheduled_at'])
    named = match_meeting(rows, text)
    span = day_range(text, today)
    if named:
        chosen = [named]
    elif span:
        start, end, _label = span
        chosen = [m for m in rows if start <= local_day(m['scheduled_at']).date() <= end]
    else:  # «следующая встреча», «расписание» — ближайшие предстоящие
        chosen = [m for m in rows if local_day(m['scheduled_at']) >= now.astimezone(ZONE)][:SPOKEN_ITEMS + 2]
        if re.search(r'следующ|ближайш', text, re.I):
            chosen = chosen[:1]
    items = [{'kind': 'meeting', 'id': m['id'], 'meeting_id': m['id'], 'title': m['title'],
              'meta': f'{spoken_day(local_day(m["scheduled_at"]).date(), today)}, {local_day(m["scheduled_at"]):%H:%M}',
              'participants': json.loads(m['participants'] or '[]')} for m in chosen]
    if PEOPLE_CUE.search(text):
        if not items:
            return 'Не нашёл подходящей встречи.', items
        first = items[0]
        people = first['participants']
        who = listing(people, lambda n: plural(n, 'участник', 'участника', 'участников')) if people else 'участники не указаны'
        return f'На встрече «{first["title"]}» {first["meta"]}: {who}.', items[:1]
    if not items:
        when = span[2] if span else 'в ближайшие дни'
        return f'{when.capitalize()} встреч нет.' if span else 'Запланированных встреч впереди нет.', items
    if len(items) == 1:
        one = items[0]
        return f'{one["meta"].capitalize()} — «{one["title"]}».', items
    label = span[2] if span else 'Ближайшие'
    spoken = listing([f'в {i["meta"].split(", ")[-1]} «{i["title"]}»' if span and span[0] == span[1]
                      else f'{i["meta"]} — «{i["title"]}»' for i in items],
                     lambda n: plural(n, 'встреча', 'встречи', 'встреч'))
    count = f'{len(items)} {plural(len(items), "встреча", "встречи", "встреч")}'
    return (f'{label.capitalize()} {count}: {spoken}.' if span else f'Ближайшие встречи: {spoken}.'), items


def task_items(tasks, today):
    items = []
    for task in tasks:
        day = due_day(task)
        late = day is not None and day < today and open_task(task)
        meta = (f'срок был {spoken_day(day, today, weekday=False)}' if late else
                f'срок {spoken_day(day, today)}' if day and (day - today).days <= 1 else
                f'до {spoken_day(day, today, weekday=False)}' if day else 'без срока')
        items.append({'kind': 'task', 'id': task['id'], 'meeting_id': task['meeting_id'], 'title': task['text'],
                      'meta': meta + (f' · {task["assignee"]}' if task.get('assignee') else ''), 'late': late})
    return items


def sort_tasks(tasks, today):
    return sorted(tasks, key=lambda t: (due_day(t) is None, due_day(t) or today, t['id']))


def tasks_answer(connection, user, text, now, person=None):
    today = now.astimezone(ZONE).date()
    people = roster(connection)
    everything = [t for t in visible_tasks(connection, user['id']) if open_task(t)]
    target = person or {'id': user['id'], 'name': user.get('name') or ''}
    mine = [t for t in everything if assigned_to(t, target, people)]
    span = day_range(text, today)
    if span:
        start, end, label = span
        mine = [t for t in mine if due_day(t) and (start <= due_day(t) <= end or (start == today and due_day(t) < today))]
    mine = sort_tasks(mine, today)
    items = task_items(mine, today)
    when = f' {span[2]}' if span else ''
    if not items:
        if person is None and everything:
            late = sum(1 for t in everything if due_day(t) and due_day(t) < today)
            return (f'Лично на вас открытых задач{when} нет. По вашим встречам открыто {len(everything)} '
                    f'{plural(len(everything), "задача", "задачи", "задач")}, просрочено {late}.'), []
        return (f'Открытых задач{when} на вас нет.' if person is None
                else f'{person["name"]}: открытых задач{when} нет.'), []
    late = sum(1 for i in items if i['late'])
    count = f'{len(items)} {plural(len(items), "открытая задача", "открытые задачи", "открытых задач")}'
    head = (f'На вас {count}' if person is None else f'{person["name"]}: {count}') + when
    if late:
        head += f', из них {late} {plural(late, "просрочена", "просрочены", "просрочено")}'
    spoken = listing([f'«{i["title"]}» — {i["meta"].split(" · ")[0]}' for i in items],
                     lambda n: plural(n, 'задача', 'задачи', 'задач'))
    return f'{head}. {spoken}.', items


def deadlines_answer(connection, user, text, now):
    today = now.astimezone(ZONE).date()
    span = day_range(text, today) or (today, today + timedelta(days=3), 'в ближайшие три дня')
    start, end, label = span
    tasks = [t for t in visible_tasks(connection, user['id']) if open_task(t) and due_day(t)]
    late = sort_tasks([t for t in tasks if due_day(t) < today], today)
    soon = sort_tasks([t for t in tasks if start <= due_day(t) <= end and due_day(t) >= today], today)
    items = task_items(late + soon, today)
    parts = []
    if late:
        parts.append(f'Просрочено {len(late)}: ' + listing([f'«{t["text"]}»' for t in late],
                                                          lambda n: plural(n, 'задача', 'задачи', 'задач')))
    if soon:
        parts.append(f'Срок {label}: ' + listing([f'«{t["text"]}» — {spoken_day(due_day(t), today, weekday=False)}' for t in soon],
                                                lambda n: plural(n, 'задача', 'задачи', 'задач')))
    if not parts:
        return f'Сроков {label} нет, просроченных задач тоже нет.', items
    return '. '.join(parts) + '.', items


def decisions_answer(connection, user, text, now):
    from meetings.decisions import visible
    today = now.astimezone(ZONE).date()
    meetings = visible_meetings(connection, user['id'])
    named = match_meeting(meetings, text)
    items = []
    if named:
        rows = connection.execute("SELECT id, text FROM protocol_items WHERE meeting_id=? AND kind='decision' "
                                  'AND confirmed_at IS NOT NULL ORDER BY position', (named['id'],)).fetchall()
        items = [{'kind': 'decision', 'id': r['id'], 'meeting_id': named['id'], 'title': r['text'], 'meta': named['title']}
                 for r in rows]
        if not items:
            return f'По встрече «{named["title"]}» подтверждённых решений нет.', [
                {'kind': 'meeting', 'id': named['id'], 'meeting_id': named['id'], 'title': named['title'], 'meta': ''}]
        return f'На встрече «{named["title"]}» решили: ' + listing([f'«{i["title"]}»' for i in items],
                                                                   lambda n: plural(n, 'решение', 'решения', 'решений')) + '.', items
    rows = [r for r in visible(connection, user['id'], model=True) if r['status'] == 'open']
    for row in rows:
        day = due_day(row)
        items.append({'kind': 'decision', 'id': row['id'], 'meeting_id': row['meeting_id'], 'title': row['text'],
                      'meta': (f'до {spoken_day(day, today)}' if day else 'без срока')
                              + (f' · {row["owner_name"]}' if row.get('owner_name') else '')})
    if not items:
        return 'Решений на контроле сейчас нет.', items
    return (f'На контроле {len(items)} {plural(len(items), "решение", "решения", "решений")}: '
            + listing([f'«{i["title"]}» {i["meta"].split(" · ")[0]}' for i in items],
                      lambda n: plural(n, 'решение', 'решения', 'решений')) + '.'), items


def documents_answer(connection, user, text, now):
    ids = store.accessible_document_ids(connection, user['id'], model=True)
    if not ids:
        return 'Доступных документов пока нет.', []
    from meetings.knowledge.index import current_clause
    current,args = current_clause(connection,user['id'])
    rows = connection.execute(
        f'SELECT d.id, d.title, COALESCE(d.authored_at, d.created_at) AS at FROM documents d WHERE d.id IN ({",".join("?" * len(ids))}) '
        'AND '+current+' ORDER BY at DESC,d.id DESC', [*ids,*args]).fetchall()
    today = now.astimezone(ZONE).date()
    items = [{'kind': 'document', 'id': r['id'], 'meeting_id': None, 'title': r['title'],
              'meta': spoken_day(local_day(r['at']).date(), today) if r['at'] else ''} for r in rows]
    newest = listing([f'«{i["title"]}»' for i in items[:SPOKEN_ITEMS]], lambda n: '')
    return (f'Вам доступно {len(items)} {plural(len(items), "документ", "документа", "документов")}. '
            f'Самые свежие: {newest}.'), items


# ---------- маршрут ----------
def detect(text):
    """Подходящие ответы по порядку; пустой список — вопрос уходит в обзор или в документы."""
    if DOCUMENT_HINT.search(text):
        return []
    found = []
    if DECISIONS.search(text):
        found.append('decisions')
    if DOCUMENTS.search(text):
        found.append('documents')
    if MY_TASKS.search(text):
        found.append('my_tasks')
    if PERSON_TASKS.search(text):
        found.append('person_tasks')
    if DEADLINES.search(text):
        found.append('deadlines')
    if MEETING_CUE.search(text) or PEOPLE_CUE.search(text):
        found.append('meetings')
    return found


def answer(connection, user, kind, text, now):
    """(фраза, элементы для экрана) или None, если вопрос не про это (например, имя не найдено)."""
    if kind == 'meetings':
        return meetings_answer(connection, user, text, now)
    if kind == 'my_tasks':
        return tasks_answer(connection, user, text, now)
    if kind == 'person_tasks':
        person = None
        for pattern in PERSON_PATTERNS:
            for found in pattern.finditer(text):
                person = find_person(connection, found.group(1))
                if person:
                    break
            if person:
                break
        if not person:
            return None
        if person['id'] == user['id']:
            return tasks_answer(connection, user, text, now)
        return tasks_answer(connection, user, text, now, person)
    if kind == 'deadlines':
        return deadlines_answer(connection, user, text, now)
    if kind == 'decisions':
        return decisions_answer(connection, user, text, now)
    if kind == 'documents':
        return documents_answer(connection, user, text, now)
    return None


def visible_to(connection, member, items):
    """Может ли слушатель сам увидеть каждый названный объект."""
    for item in items:
        if item['kind'] == 'document':
            if not store.can_read_document(connection, member, item['id'], model=True):
                return False
        elif item.get('meeting_id') is not None and not store.can_read_meeting(connection, member, item['meeting_id'], model=True):
            return False
    return True
