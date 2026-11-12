"""Bounded RFC 5545 interchange. No URLs, attachments, alarms or commands execute.

Export uses UTC instants (Z), so clients display them in their own time zone.
Import intentionally supports single VEVENTs only; recurrence is rejected rather
than silently treating a recurring busy period as one free calendar interval.
"""
from datetime import datetime, timedelta, timezone
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_BYTES = 1024 * 1024
MAX_EVENTS = 500


class ICSError(ValueError):
    pass


def escape(value):
    value = str(value).replace('\r\n', '\n').replace('\r', '\n')
    value = ''.join(c for c in value if c in '\n\t' or ord(c) >= 32 and ord(c) != 127)
    return value.replace('\\', '\\\\').replace('\n', '\\n').replace(';', '\\;').replace(',', '\\,')


def fold(line):
    """75 octets, including continuation space; never split a UTF-8 character."""
    lines, current = [], ''
    for char in line:
        if len((current + char).encode('utf-8')) > 75:
            lines.append(current)
            current = ' '
        current += char
    return '\r\n'.join([*lines, current])


def utc(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ICSError('Для экспорта требуется время с часовым поясом.')
    return result.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def calendar(events):
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//CallWise//Focus v2//RU',
             'CALSCALE:GREGORIAN', 'METHOD:PUBLISH', 'X-WR-TIMEZONE:Europe/Minsk']
    for event in events:
        lines += ['BEGIN:VEVENT', 'UID:' + escape(event['uid']),
                  'DTSTAMP:' + utc(event['created_at']), 'DTSTART:' + utc(event['start_at']),
                  'DTEND:' + utc(event['end_at']), 'SUMMARY:' + escape(event['title']),
                  'STATUS:' + ('CONFIRMED' if event.get('status','confirmed') == 'confirmed' else
                               'CANCELLED' if event.get('status') in ('cancelled','failed') else 'TENTATIVE'),
                  'TRANSP:OPAQUE', 'END:VEVENT']
    return ('\r\n'.join(fold(line) for line in [*lines, 'END:VCALENDAR']) + '\r\n').encode('utf-8')


def _moment(params, value, default_zone):
    is_date = params.get('VALUE') == 'DATE'
    try:
        if params.get('VALUE', 'DATE-TIME') not in ('DATE', 'DATE-TIME'):
            raise ValueError()
        if is_date:
            if not re.fullmatch(r'\d{8}', value): raise ValueError()
            moment = datetime.strptime(value, '%Y%m%d')
        else:
            if not re.fullmatch(r'\d{8}T\d{6}Z?', value): raise ValueError()
            moment = datetime.strptime(value.rstrip('Z'), '%Y%m%dT%H%M%S')
        if value.endswith('Z'):
            if is_date or 'TZID' in params: raise ValueError()
            return moment.replace(tzinfo=timezone.utc), is_date
        zone = ZoneInfo(params.get('TZID', default_zone).strip('"'))
        aware = moment.replace(tzinfo=zone)
        # Reject ambiguous/nonexistent wall clocks rather than guessing a DST fold.
        if aware.utcoffset() != moment.replace(tzinfo=zone, fold=1).utcoffset(): raise ValueError()
        if aware.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != moment: raise ValueError()
        return aware, is_date
    except (ValueError, ZoneInfoNotFoundError, OverflowError):
        raise ICSError('Некорректное или неоднозначное время ICS. Укажите IANA-пояс или UTC.') from None


def parse(data, default_zone='Europe/Minsk'):
    if len(data) > MAX_BYTES: raise ICSError('Календарь больше 1 МБ.')
    try:
        ZoneInfo(default_zone)
        text = data.decode('utf-8-sig')
    except (UnicodeDecodeError, ZoneInfoNotFoundError, ValueError):
        raise ICSError('Ожидается ICS в UTF-8 и существующий часовой пояс.') from None
    if '\x00' in text: raise ICSError('Некорректный файл ICS.')
    lines = re.sub(r'\r?\n[ \t]', '', text).splitlines()
    if not lines or lines[0] != 'BEGIN:VCALENDAR' or lines[-1] != 'END:VCALENDAR':
        raise ICSError('Файл не является календарём ICS.')
    stack, events, event, seen, count = [], [], None, set(), 0
    for line in lines:
        if len(line) > 20000: raise ICSError('Слишком длинная строка ICS.')
        head, separator, value = line.partition(':')
        if not separator: raise ICSError('Повреждённая строка ICS.')
        pieces = head.split(';'); name = pieces[0].upper()
        if name == 'BEGIN':
            component = value.upper()
            if component == 'VEVENT':
                if stack != ['VCALENDAR']: raise ICSError('Некорректная вложенность ICS.')
                event = {}; count += 1
                if count > MAX_EVENTS: raise ICSError('Не больше 500 событий за импорт.')
            stack.append(component)
            continue
        if name == 'END':
            if not stack or stack.pop() != value.upper(): raise ICSError('Некорректная вложенность ICS.')
            if value.upper() == 'VEVENT':
                if not event or 'UID' not in event or 'DTSTART' not in event:
                    raise ICSError('У события должны быть UID и DTSTART.')
                if event.get('STATUS', ({}, ''))[1].upper() != 'CANCELLED' and event.get('TRANSP', ({}, ''))[1].upper() != 'TRANSPARENT':
                    start, is_date = _moment(*event['DTSTART'], default_zone)
                    if 'DTEND' in event:
                        end, end_date = _moment(*event['DTEND'], default_zone)
                        if end_date != is_date: raise ICSError('DTSTART и DTEND должны иметь один тип.')
                    elif is_date:
                        end = start + timedelta(days=1)
                    else:
                        raise ICSError('Для события со временем требуется DTEND.')
                    if not timedelta(0) < end - start <= timedelta(days=31):
                        raise ICSError('Интервал ICS должен быть больше нуля и не дольше 31 дня.')
                    key = (event['UID'][1], start.isoformat(), end.isoformat())
                    if not key[0] or len(key[0]) > 1000: raise ICSError('Некорректный UID события.')
                    if key not in seen:
                        seen.add(key)
                        # Titles, descriptions, participants and attachments never enter storage/model.
                        events.append({'start_at': start.astimezone(timezone.utc).isoformat(timespec='seconds'),
                                       'end_at': end.astimezone(timezone.utc).isoformat(timespec='seconds')})
                event = None
            continue
        if not stack: raise ICSError('Данные вне компонента ICS.')
        if stack == ['VCALENDAR', 'VEVENT']:
            if name in ('RRULE', 'RDATE', 'EXDATE', 'RECURRENCE-ID', 'EXRULE'):
                raise ICSError('Повторяющиеся события пока не поддерживаются. Экспортируйте отдельные события.')
            if name in ('UID', 'DTSTART', 'DTEND', 'STATUS', 'TRANSP'):
                if name in event: raise ICSError('Повтор обязательного поля события ICS.')
                params = {}
                for piece in pieces[1:]:
                    key, sep, val = piece.partition('=')
                    if not sep or key.upper() in params: raise ICSError('Повреждённый параметр ICS.')
                    params[key.upper()] = val
                event[name] = (params, value)
            if name == 'DURATION': raise ICSError('Для импорта укажите DTEND вместо DURATION.')
    if stack: raise ICSError('Незавершённый компонент ICS.')
    return sorted(events, key=lambda row: (row['start_at'], row['end_at']))
