"""Test calendar (provider "mock"): busy intervals, common free time, events and a local invitation outbox.

Intervals are half-open [start, end): a meeting 10:00–11:00 and another 11:00–12:00 do not conflict.
Everything is stored as aware UTC; working hours are evaluated in the requested IANA zone (Europe/Minsk by
default). Busy intervals never expose their titles to other users. No e-mail or external calendar is used.
"""
from datetime import datetime, time, timedelta, timezone

from meetings import store
from meetings.auth import MeetError

PROVIDER = 'mock'
STEP_MINUTES = 15
MAX_RANGE_DAYS = 31
MAX_SLOTS = 20
MAX_PARTICIPANTS = 30


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def directory(connection) -> list[dict]:
    """Test participant directory: existing users only (no free-form e-mail addresses)."""
    return [{'id': r['id'], 'name': r['name']} for r in connection.execute('SELECT id, name FROM users ORDER BY id')]


def participants(connection, ids: list[int], organizer_id: int | None = None) -> list[dict]:
    wanted = list(dict.fromkeys(([organizer_id] if organizer_id else []) + list(ids)))
    if len(wanted) > MAX_PARTICIPANTS:
        raise MeetError(422, 'too_many_participants', f'Не больше {MAX_PARTICIPANTS} участников.')
    known = {p['id']: p for p in directory(connection)}
    unknown = [i for i in wanted if i not in known]
    if unknown:
        raise MeetError(422, 'unknown_participant', 'Участники выбираются только из тестового справочника.')
    return [known[i] for i in wanted]


def add_busy(connection, user_id: int, start_at, end_at, title: str = '', source: str = 'test') -> int:
    """For seeds/tests: store a busy interval as aware UTC. Naive input is rejected (pass an offset)."""
    start = start_at if isinstance(start_at, datetime) else store.parse_aware(start_at)
    end = end_at if isinstance(end_at, datetime) else store.parse_aware(end_at)
    if start.tzinfo is None or end.tzinfo is None:
        raise store.TimeError('naive_datetime', 'Интервал занятости должен быть с часовым поясом.')
    if end <= start:
        raise store.TimeError('invalid_interval', 'Конец интервала должен быть позже начала.')
    return connection.execute('INSERT INTO calendar_busy(user_id,start_at,end_at,title,source) VALUES (?,?,?,?,?)',
                              (user_id, store.iso_utc(start), store.iso_utc(end), title[:200], source)).lastrowid


def busy_intervals(connection, user_ids: list[int], start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """Merged busy intervals of the given users that intersect [start, end). No titles, no owners."""
    if not user_ids:
        return []
    marks = ','.join('?' * len(user_ids))
    rows = connection.execute(
        f'SELECT start_at, end_at FROM calendar_busy WHERE user_id IN ({marks}) '
        f'UNION ALL SELECT e.start_at, e.end_at FROM calendar_events e JOIN calendar_event_participants p '
        f"ON p.event_id=e.id WHERE p.user_id IN ({marks}) AND e.status='confirmed'",
        list(user_ids) + list(user_ids)).fetchall()
    intervals = []
    for row in rows:
        a = datetime.fromisoformat(store.stored_utc(row[0]))
        b = datetime.fromisoformat(store.stored_utc(row[1]))
        if overlaps(a, b, start, end):
            intervals.append((a, b))
    intervals.sort()
    merged: list[list[datetime]] = []
    for a, b in intervals:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def is_free(connection, user_ids, start: datetime, end: datetime) -> bool:
    return not any(overlaps(a, b, start, end) for a, b in busy_intervals(connection, user_ids, start, end))


def _ceil_to_step(value: datetime, step: int) -> datetime:
    value = value.replace(second=0, microsecond=0) + (timedelta(minutes=1) if value.second or value.microsecond else timedelta())
    remainder = value.minute % step
    return value + timedelta(minutes=(step - remainder) % step)


def free_slots(connection, user_ids, range_start: datetime, range_end: datetime, duration_minutes: int,
               tz_name: str, work_start: time, work_end: time, weekends: bool) -> list[dict]:
    if range_end <= range_start:
        raise MeetError(422, 'invalid_range', 'Конец периода должен быть позже начала.')
    if range_end - range_start > timedelta(days=MAX_RANGE_DAYS):
        raise MeetError(422, 'range_too_long', f'Период поиска — не больше {MAX_RANGE_DAYS} дней.')
    if work_end <= work_start:
        raise MeetError(422, 'invalid_work_hours', 'Конец рабочего дня должен быть позже начала.')
    zone = store.zone(tz_name)
    duration = timedelta(minutes=duration_minutes)
    busy = busy_intervals(connection, user_ids, range_start, range_end)
    now = datetime.now(timezone.utc)
    cursor = _ceil_to_step(max(range_start, now).astimezone(zone), STEP_MINUTES)
    slots = []
    while cursor + duration <= range_end and len(slots) < MAX_SLOTS:
        local_end = cursor + duration
        working = (weekends or cursor.weekday() < 5) and cursor.time() >= work_start \
            and local_end.date() == cursor.date() and local_end.time() <= work_end and local_end.time() != time(0)
        if working:
            start_utc, end_utc = cursor.astimezone(timezone.utc), local_end.astimezone(timezone.utc)
            blocking = next((b for a, b in busy if overlaps(a, b, start_utc, end_utc)), None)
            if blocking is None:
                slots.append(slot_out(start_utc, end_utc, zone))
                cursor = (cursor + timedelta(minutes=STEP_MINUTES)).astimezone(zone)
                continue
            # jump past the blocking interval
            cursor = _ceil_to_step(blocking.astimezone(zone), STEP_MINUTES)
            continue
        cursor = (cursor + timedelta(minutes=STEP_MINUTES)).astimezone(zone)
    return slots


def slot_out(start: datetime, end: datetime, zone) -> dict:
    return {'start_at': store.iso_utc(start), 'end_at': store.iso_utc(end),
            'start_local': start.astimezone(zone).isoformat(timespec='minutes'),
            'end_local': end.astimezone(zone).isoformat(timespec='minutes')}


def local_label(value: datetime, tz_name: str) -> str:
    local = value.astimezone(store.zone(tz_name))
    return f"{local.strftime('%d.%m.%Y %H:%M')} ({tz_name})"


def invitation(connection, recipient: dict, meeting_row, start: datetime, end: datetime, tz_name: str) -> dict:
    """Local test invitation. The meeting title is included only for recipients who can read the meeting."""
    visible = store.can_read_meeting(connection, recipient['id'], meeting_row['id'])
    subject = f"Приглашение: {meeting_row['title']}" if visible else 'Приглашение на встречу'
    body = (f"{subject}\nКогда: {local_label(start, tz_name)} — {end.astimezone(store.zone(tz_name)).strftime('%H:%M')}\n"
            'Тестовый календарь CallWise: письмо не отправляется, приглашение хранится в локальном outbox.')
    return {'recipient_id': recipient['id'], 'recipient_name': recipient['name'], 'channel': 'local_outbox',
            'subject': subject[:250], 'body': body, 'has_meeting_access': visible}


def event_out(connection, viewer_id: int, row) -> dict:
    people = [{'id': r['id'], 'name': r['name']} for r in connection.execute(
        'SELECT u.id, u.name FROM calendar_event_participants p JOIN users u ON u.id=p.user_id '
        'WHERE p.event_id=? ORDER BY u.id', (row['id'],))]
    readable = row['meeting_id'] is not None and store.can_read_meeting(connection, viewer_id, row['meeting_id'])
    zone = store.zone(row['timezone'])
    start, end = datetime.fromisoformat(row['start_at']), datetime.fromisoformat(row['end_at'])
    return {'id': row['id'], 'meeting_id': row['meeting_id'] if readable else None,
            'title': row['title'] if readable else 'Встреча (нет доступа к материалам)',
            'start_at': row['start_at'], 'end_at': row['end_at'], 'timezone': row['timezone'],
            'start_local': start.astimezone(zone).isoformat(timespec='minutes'),
            'end_local': end.astimezone(zone).isoformat(timespec='minutes'),
            'organizer_id': row['organizer_id'], 'participants': people, 'provider': row['provider'],
            'status': row['status'], 'created_at': row['created_at']}


def outbox_out(row) -> dict:
    return {'id': row['id'], 'event_id': row['event_id'], 'recipient_id': row['recipient_id'],
            'channel': row['channel'], 'subject': row['subject'], 'body': row['body'], 'status': row['status'],
            'created_at': row['created_at']}


def create_event(connection, organizer: dict, meeting_row, payload: dict, confirmation_id: str) -> dict:
    stamp = store.now()
    event_id = connection.execute(
        'INSERT INTO calendar_events(meeting_id,organizer_id,title,start_at,end_at,timezone,provider,status,'
        "confirmation_id,created_at) VALUES (?,?,?,?,?,?,?,'confirmed',?,?)",
        (meeting_row['id'], organizer['id'], meeting_row['title'], payload['start_at'], payload['end_at'],
         payload['timezone'], PROVIDER, confirmation_id, stamp)).lastrowid
    for person in payload['participants']:
        connection.execute('INSERT OR IGNORE INTO calendar_event_participants VALUES (?,?)', (event_id, person['id']))
    start, end = datetime.fromisoformat(payload['start_at']), datetime.fromisoformat(payload['end_at'])
    for person in payload['participants']:
        if person['id'] == organizer['id']:
            continue
        # Re-rendered at confirm time from the frozen recipient list (access may have changed since preview).
        letter = invitation(connection, person, meeting_row, start, end, payload['timezone'])
        connection.execute('INSERT OR IGNORE INTO calendar_outbox(event_id,recipient_id,channel,subject,body,status,'
                           "created_at) VALUES (?,?,'local_outbox',?,?,'queued_local',?)",
                           (event_id, person['id'], letter['subject'], letter['body'], stamp))
    connection.execute('UPDATE meetings SET scheduled_at=?, version=version+1 WHERE id=?',
                       (payload['start_at'], meeting_row['id']))
    return {'event_id': event_id}


def event_bundle(connection, viewer_id: int, event_id: int) -> dict:
    row = connection.execute('SELECT * FROM calendar_events WHERE id=?', (event_id,)).fetchone()
    invitations = [outbox_out(r) for r in connection.execute(
        'SELECT * FROM calendar_outbox WHERE event_id=? ORDER BY id', (event_id,))]
    return {'event': event_out(connection, viewer_id, row), 'invitations': invitations}
