"""Derived free/busy only: never expose private HR rows or event titles.

Explicit shift rows override the ordinary 09–18 working day in each user's
zone. A user with a shift schedule but no shift on a date is unavailable.
Legacy users without any shifts use a documented office-hours fallback.
"""
from datetime import datetime, time, timedelta, timezone
import os
import sqlite3

from meetings import store
from meetings.auth import MeetError
from meetings.calendar import service

BUFFER = timedelta(minutes=10)


def snapshot(c, user_ids, start, end):
    fault = os.getenv('MOCK_CALENDAR_FAULT', '')
    if fault not in ('', 'down', 'stale'):
        raise MeetError(503, 'calendar_config', 'Проверьте настройки источника календаря.')
    if fault == 'down':
        raise MeetError(503, 'calendar_unavailable', 'Источник занятости недоступен. Параметры сохранены; повторите подбор позже.')
    result, warnings = {}, []
    for uid in user_ids:
        user = c.execute('SELECT id,active,timezone,department_id,personnel_code FROM users WHERE id=?', (uid,)).fetchone()
        if not user or not user['active']:
            raise MeetError(422, 'unknown_participant', 'Один из участников недоступен. Обновите список участников.')
        try:
            zone = store.zone(user['timezone'])
            shift_rows = c.execute('SELECT start_at,end_at,break_start,break_end,as_of FROM work_shifts '
                                  'WHERE user_id=? AND julianday(start_at)<julianday(?) AND julianday(end_at)>julianday(?)',
                                  (uid, store.iso_utc(end), store.iso_utc(start))).fetchall()
            shifted = bool(shift_rows) or bool(c.execute('SELECT 1 FROM work_shifts WHERE user_id=? LIMIT 1', (uid,)).fetchone())
            shifts = []
            for row in shift_rows:
                a, b = store.parse_aware(row['start_at']), store.parse_aware(row['end_at'])
                if b <= a: raise ValueError()
                breaks = []
                if row['break_start'] or row['break_end']:
                    x, y = store.parse_aware(row['break_start']), store.parse_aware(row['break_end'])
                    if not a <= x < y <= b: raise ValueError()
                    breaks.append((x, y))
                shifts.append((a, b, breaks))
                if (store.parse_aware(store.now()) - store.parse_aware(row['as_of'])).total_seconds() > 86400:
                    warnings.append('График смен старше 24 часов; перед подтверждением уточните актуальность.')
            busy = [(a-BUFFER, b+BUFFER) for a,b in service.busy_intervals(c, [uid], start-BUFFER, end+BUFFER)]
            if user['personnel_code']:
                for row in c.execute('SELECT start_at,end_at FROM hr_absences WHERE personnel_code=? AND department_id=? '
                                     'AND julianday(start_at)<julianday(?) AND julianday(end_at)>julianday(?)',
                                     (user['personnel_code'],user['department_id'],store.iso_utc(end),store.iso_utc(start))):
                    busy.append((store.parse_aware(row['start_at']),store.parse_aware(row['end_at'])))
            result[uid] = {'zone': zone, 'shifted': shifted, 'shifts': shifts, 'busy': busy}
            if not shifted:
                warnings.append('Для части участников график смен не задан: использованы будни 09:00–18:00, обед 13:00–14:00 и планёрка 09:00–09:15 в их часовом поясе.')
        except (store.TimeError, ValueError, TypeError, sqlite3.Error):
            raise MeetError(503, 'calendar_unavailable', 'График рабочего времени повреждён. Обратитесь к администратору.') from None
    if fault == 'stale': warnings.append('Источник занятости помечен устаревшим; перед подтверждением уточните актуальность.')
    return result, list(dict.fromkeys(warnings))


def available(person, start, end):
    if any(service.overlaps(a,b,start,end) for a,b in person['busy']): return False
    if person['shifted']:
        return any(a <= start and end <= b and not any(service.overlaps(x,y,start,end) for x,y in breaks)
                   for a,b,breaks in person['shifts'])
    a, b = start.astimezone(person['zone']), end.astimezone(person['zone'])
    if a.weekday() >= 5 or a.date() != b.date() or a.time() < time(9,15) or b.time() > time(18) or b.time() == time(0): return False
    lunch_a = a.replace(hour=13,minute=0,second=0,microsecond=0)
    lunch_b = lunch_a + timedelta(hours=1)
    return not service.overlaps(lunch_a,lunch_b,a,b)


def validate(c, required, optional, start, end):
    people, warnings = snapshot(c, [*required, *optional], start, end)
    if start <= datetime.now(timezone.utc):
        raise MeetError(422, 'slot_in_past', 'Нельзя назначить встречу на прошедшее время.')
    if not all(available(people[uid],start,end) for uid in required):
        raise MeetError(409, 'slot_taken', 'Время не подходит обязательным участникам: занятость, смена или перерыв изменились. Обновите слоты.')
    optional_busy = sum(not available(people[uid],start,end) for uid in optional)
    if optional_busy: warnings.append(f'Необязательных участников, которым не подходит время: {optional_busy}.')
    return warnings, optional_busy


def slots(c, required, optional, start, end, duration_minutes, tz_name, work_start, work_end, weekends=False):
    if not timedelta(0) < end-start <= timedelta(days=service.MAX_RANGE_DAYS):
        raise MeetError(422,'invalid_range','Период поиска должен быть больше нуля и не дольше 31 дня.')
    if work_end <= work_start:
        raise MeetError(422,'invalid_work_hours','Конец рабочего дня должен быть позже начала.')
    people, warnings = snapshot(c, [*required, *optional], start, end)
    zone = store.zone(tz_name)
    cursor = service._ceil_to_step(max(start,datetime.now(timezone.utc)),service.STEP_MINUTES)
    duration = timedelta(minutes=duration_minutes)
    found = []
    while cursor+duration <= end:
        finish = cursor+duration
        a,b = cursor.astimezone(zone), finish.astimezone(zone)
        within = ((weekends or a.weekday()<5) and a.date()==b.date() and a.time()>=work_start
                  and b.time()<=work_end and b.time()!=time(0))
        if within and all(available(people[uid],cursor,finish) for uid in required):
            optional_busy = sum(not available(people[uid],cursor,finish) for uid in optional)
            found.append({**service.slot_out(cursor,finish,zone), 'optional_busy_count':optional_busy,
                          'reason': 'Все обязательные участники свободны; учтены рабочее время, перерывы и буфер 10 минут.'
                                    + (f' Необязательных участников с конфликтом: {optional_busy}.' if optional_busy else ' Все необязательные участники тоже свободны.')})
        cursor += timedelta(minutes=service.STEP_MINUTES)
    # Earliest among those with the best optional attendance; no titles or shift rows returned.
    return sorted(found,key=lambda row:(row['optional_busy_count'],row['start_at']))[:3],warnings
