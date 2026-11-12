"""Bounded local calendar series: every occurrence is reviewed in one preview.

No unbounded scheduler or silent external writes; external calendar series must
be scheduled occurrence by occurrence through the existing outbox.
"""
from datetime import datetime, timedelta, timezone
import json
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from meetings import access, confirmations, store
from meetings.api import ConfirmTokenIn
from meetings.auth import MeetError, MeetRoute, current_user, require
from meetings.calendar import providers, service
from meetings.connectors.mock import digest


class Series(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=3, max_length=200)
    start_at: str = Field(max_length=40)
    timezone: str = Field(default=store.DISPLAY_ZONE, max_length=60)
    frequency: str = Field(pattern='^(daily|weekdays|weekly)$')
    count: int = Field(ge=2, le=30)
    duration_minutes: int = Field(default=30, ge=15, le=480)
    participant_ids: list[int] = Field(default_factory=list, max_length=29)
    smart: bool = True


def plan(c, user, data):
    require(user, 'meetings.create', action='series.create')
    require(user, 'calendar.invite', action='series.invite')
    if providers.configured_name() != 'mock':
        raise MeetError(409, 'local_series_only', 'Серия создаётся в локальном календаре. Внешний календарь требует отдельного подтверждения каждой встречи.')
    try:
        zone = store.zone(data['timezone'])
        first = store.parse_aware(data['start_at']).astimezone(zone)
        if first <= datetime.now(timezone.utc):
            raise ValueError()
    except (store.TimeError, ValueError):
        raise MeetError(422, 'series_time', 'Укажите будущее время с часовым поясом.') from None
    people = service.participants(c, data['participant_ids'], user['id'])
    dates = []; warnings = []; day = first.date()
    while len(dates) < data['count']:
        if data['frequency'] != 'weekdays' or day.weekday() < 5:
            try:
                start = store.parse_aware(day.isoformat() + 'T' + first.strftime('%H:%M:%S'), data['timezone'])
            except store.TimeError:
                raise MeetError(422, 'series_dst', 'В серии есть неоднозначное время перехода часов. Выберите другой час.') from None
            end = start + timedelta(minutes=data['duration_minutes'])
            if data['smart']:
                from meetings.calendar.availability import validate
                notes, _ = validate(c, [p['id'] for p in people], [], start, end)
                warnings.extend(notes)
            elif not service.is_free(c, [p['id'] for p in people], start, end):
                raise MeetError(409, 'slot_taken', 'В серии есть занятое время. Измените даты или состав участников.')
            dates.append({'start_at': store.iso_utc(start), 'end_at': store.iso_utc(end)})
        day += timedelta(days=7 if data['frequency'] == 'weekly' else 1)
    return {'spec': data, 'participants': people, 'occurrences': dates, 'warnings': list(dict.fromkeys(warnings)),
            'actor_context': digest([user.get('level'), user.get('department_id'), user.get('_delegated_departments', [])])}


def router():
    api = APIRouter(route_class=MeetRoute)

    @api.get('/api/meet/calendar/series')
    def listing(request: Request):
        user = current_user(request); require(user, 'calendar.view', action='series.read')
        with store.db() as c:
            result = []
            for row in c.execute('SELECT * FROM meeting_series ORDER BY id DESC'):
                meetings = [store.meeting_out(c, m) for m in c.execute('SELECT * FROM meetings WHERE series_id=? ORDER BY scheduled_at', (row['id'],))
                            if store.can_read_meeting(c, user['id'], m['id'], model=True)]
                if meetings:
                    result.append({'id': row['id'], 'title': row['title'], 'meetings': meetings, 'timezone': row['timezone']})
            return {'series': result}

    @api.post('/api/meet/calendar/series/preview')
    def preview(body: Series, request: Request):
        user = current_user(request)
        with store.write_tx() as c:
            data = plan(c, user, body.model_dump())
            token = confirmations.create(c, user, 'calendar.series', 'user', user['id'], None, data)
            store.audit(c, user['id'], 'series_preview', object_type='user', object_id=user['id'], stage='preview', confirmation_id=token['confirmation_id'])
            return {**token, 'preview': data, 'notice': 'Все даты серии требуют проверки. Протокол каждой встречи отдельный; письма останутся в локальной очереди.'}

    @api.post('/api/meet/calendar/series/confirm')
    def confirm(body: ConfirmTokenIn, request: Request):
        user = current_user(request)
        require(user, 'meetings.create', action='series.confirm'); require(user, 'calendar.invite', action='series.confirm')
        with store.write_tx() as c:
            p = confirmations.load(c, user, body.confirmation_id, 'calendar.series', 'user', user['id'], body.idempotency_key)
            if p['already']:
                return {**p['result'], 'already_confirmed': True}
            data = p['payload']
            if digest(plan(c, user, data['spec'])) != digest(data):
                raise MeetError(409, 'stale', 'Параметры или участники серии изменились. Нужен новый предпросмотр.')
            spec = data['spec']; stamp = store.now()
            sid = c.execute('INSERT INTO meeting_series(owner_id,title,hour,timezone,created_at,spec,department_id) VALUES (?,?,?,?,?,?,?)',
                (user['id'], spec['title'], store.parse_aware(spec['start_at']).astimezone(store.zone(spec['timezone'])).strftime('%H:%M'),
                 spec['timezone'], stamp, json.dumps(spec, ensure_ascii=False), user.get('department_id'))).lastrowid
            mids = []
            for i, interval in enumerate(data['occurrences']):
                mid = c.execute("INSERT INTO meetings(owner_id,title,topic,participants,created_at,department_id,confidentiality,series_id) VALUES (?,?,?,?,?,?,'department',?)",
                    (user['id'], spec['title'], 'Встреча серии', json.dumps([p['name'] for p in data['participants']], ensure_ascii=False), stamp, user.get('department_id'), sid)).lastrowid
                meeting = c.execute('SELECT * FROM meetings WHERE id=?', (mid,)).fetchone()
                service.create_event(c, user, meeting, {**interval, 'timezone': spec['timezone'], 'participants': data['participants']}, body.confirmation_id + ':' + str(i))
                mids.append(mid)
            result = {'series_id': sid, 'meeting_ids': mids, 'delivery': 'local_outbox_only'}
            confirmations.finish(c, body.confirmation_id, body.idempotency_key, result)
            store.audit(c, user['id'], 'series_confirmed', object_type='series', object_id=sid, stage='confirm', confirmation_id=body.confirmation_id)
            return {**result, 'already_confirmed': False}
    return api
