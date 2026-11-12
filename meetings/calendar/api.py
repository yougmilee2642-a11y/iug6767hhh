"""HTTP API of the test calendar (§7.2.2). Registered by meetings.api.install."""
from datetime import datetime, time, timedelta, timezone

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from meetings import confirmations, store
from meetings.api import ConfirmTokenIn, _meeting, time_error
from meetings.auth import MeetError, MeetRoute, current_user, require
from meetings.calendar import service

ACTION = 'calendar.schedule'


class SlotsIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    participant_ids: list[int] = Field(default_factory=list, max_length=service.MAX_PARTICIPANTS)
    range_start: str = Field(max_length=40)
    range_end: str = Field(max_length=40)
    duration_minutes: int = Field(ge=15, le=480)
    timezone: str = Field(default=store.DISPLAY_ZONE, max_length=60)
    work_start: str = Field(default='09:00', pattern=r'^\d{2}:\d{2}$')
    work_end: str = Field(default='18:00', pattern=r'^\d{2}:\d{2}$')
    include_weekends: bool = False


class PreviewIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    meeting_id: int
    participant_ids: list[int] = Field(default_factory=list, max_length=service.MAX_PARTICIPANTS)
    start_at: str = Field(max_length=40)
    duration_minutes: int = Field(ge=15, le=480)
    timezone: str = Field(default=store.DISPLAY_ZONE, max_length=60)  # zone of display; naive start_at uses it only if explicit


class CancelIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    confirmation_id: str = Field(min_length=8, max_length=80)


def _aware(value: str, tz_name: str | None = None) -> datetime:
    try:
        return store.parse_aware(value, tz_name)
    except store.TimeError as error:
        raise time_error(error) from None


def _clock(value: str) -> time:
    try:
        return time.fromisoformat(value)
    except ValueError:
        raise MeetError(422, 'invalid_work_hours', 'Рабочие часы задаются как ЧЧ:ММ.') from None


def _zone_name(name: str) -> str:
    try:
        store.zone(name)
    except store.TimeError as error:
        raise time_error(error) from None
    return name


def router():
    api = APIRouter(route_class=MeetRoute)

    @api.get('/api/meet/calendar/participants')
    def directory(request: Request):
        current_user(request)
        with store.db() as connection:
            return {'participants': service.directory(connection), 'provider': service.PROVIDER}

    @api.post('/api/meet/calendar/slots')
    def slots(payload: SlotsIn, request: Request):
        user = current_user(request)
        require(user, 'calendar.view', action='calendar.slots')
        tz_name = _zone_name(payload.timezone)
        start, end = _aware(payload.range_start), _aware(payload.range_end)
        with store.db() as connection:
            people = service.participants(connection, payload.participant_ids, user['id'])
            found = service.free_slots(connection, [p['id'] for p in people], start, end, payload.duration_minutes,
                                       tz_name, _clock(payload.work_start), _clock(payload.work_end),
                                       payload.include_weekends)
        return {'slots': found, 'timezone': tz_name, 'participants': people, 'duration_minutes': payload.duration_minutes,
                'step_minutes': service.STEP_MINUTES, 'provider': service.PROVIDER}

    @api.post('/api/meet/calendar/preview')
    def preview(payload: PreviewIn, request: Request):
        user = current_user(request)
        tz_name = _zone_name(payload.timezone)
        start = _aware(payload.start_at)  # offset required: preview must be unambiguous
        end = start + timedelta(minutes=payload.duration_minutes)
        if start <= datetime.now(timezone.utc):
            raise MeetError(422, 'slot_in_past', 'Нельзя назначить встречу на прошедшее время.')
        with store.write_tx() as connection:
            row = _meeting(connection, user, payload.meeting_id, 'calendar.invite', 'calendar.preview')
            people = service.participants(connection, payload.participant_ids, user['id'])
            ids = [p['id'] for p in people]
            if not service.is_free(connection, ids, start, end):
                raise MeetError(409, 'slot_taken', 'Выбранное время уже занято у одного из участников. Обновите слоты.')
            invitations = [service.invitation(connection, p, row, start, end, tz_name) for p in people if p['id'] != user['id']]
            no_access = sum(1 for i in invitations if not i['has_meeting_access'])
            body = {'meeting_id': row['id'], 'title': row['title'], 'start_at': store.iso_utc(start),
                    'end_at': store.iso_utc(end), 'timezone': tz_name,
                    'start_local': start.astimezone(store.zone(tz_name)).isoformat(timespec='minutes'),
                    'end_local': end.astimezone(store.zone(tz_name)).isoformat(timespec='minutes'),
                    'duration_minutes': payload.duration_minutes, 'participants': people,
                    'invitations': invitations, 'provider': service.PROVIDER,
                    'warnings': ([f'У участников без доступа к материалам встречи ({no_access}) приглашение придёт '
                                  'без названия; доступ к встрече не выдаётся автоматически.'] if no_access else [])
                                + ['Тестовый календарь: реальные письма не отправляются.']}
            token = confirmations.create(connection, user, ACTION, 'meeting', row['id'], row['version'], body)
            store.audit(connection, user['id'], 'calendar_preview', object_type='meeting', object_id=row['id'],
                        confirmation_id=token['confirmation_id'], stage='preview', participants=ids,
                        start_at=body['start_at'])
            return {**token, 'preview': body}

    @api.post('/api/meet/calendar/confirm')
    def confirm(payload: ConfirmTokenIn, request: Request):
        user = current_user(request)
        with store.write_tx() as connection:
            pending = confirmations.load(connection, user, payload.confirmation_id, ACTION, 'meeting', None,
                                         payload.idempotency_key)
            require(user, 'calendar.invite', action='calendar.confirm')
            if pending['already']:
                bundle = service.event_bundle(connection, user['id'], pending['result']['event_id'])
                return {**bundle, 'already_confirmed': True}
            body = pending['payload']
            meeting_id = int(pending['object_id'])
            row = _meeting(connection, user, meeting_id, 'calendar.invite', 'calendar.confirm')  # ACL/role re-checked
            if row['version'] != pending['object_version']:
                raise MeetError(409, 'stale', 'Встреча изменилась после предпросмотра. Сформируйте предпросмотр заново.')
            start, end = datetime.fromisoformat(body['start_at']), datetime.fromisoformat(body['end_at'])
            if not service.is_free(connection, [p['id'] for p in body['participants']], start, end):
                raise MeetError(409, 'slot_taken', 'Пока вы подтверждали, это время заняли. Выберите другой слот.')
            created = service.create_event(connection, user, row, body, payload.confirmation_id)
            confirmations.finish(connection, payload.confirmation_id, payload.idempotency_key, created)
            store.audit(connection, user['id'], 'calendar_confirm', object_type='calendar_event',
                        object_id=created['event_id'], confirmation_id=payload.confirmation_id, stage='confirm',
                        meeting_id=meeting_id, invitations=len(body['participants']) - 1)
            return {**service.event_bundle(connection, user['id'], created['event_id']), 'already_confirmed': False}

    @api.post('/api/meet/calendar/cancel')
    def cancel(payload: CancelIn, request: Request):
        user = current_user(request)
        with store.write_tx() as connection:
            return confirmations.cancel(connection, user, payload.confirmation_id)

    @api.get('/api/meet/calendar/events')
    def events(request: Request):
        user = current_user(request)
        require(user, 'calendar.view', action='calendar.events')
        with store.db() as connection:
            rows = connection.execute(
                'SELECT DISTINCT e.* FROM calendar_events e LEFT JOIN calendar_event_participants p ON p.event_id=e.id '
                'WHERE e.organizer_id=? OR p.user_id=? ORDER BY e.start_at, e.id', (user['id'], user['id'])).fetchall()
            return {'events': [service.event_out(connection, user['id'], r) for r in rows]}

    @api.get('/api/meet/calendar/outbox')
    def outbox(request: Request):
        """Local test invitations addressed to me or sent by me. Nothing here is ever e-mailed."""
        user = current_user(request)
        require(user, 'calendar.view', action='calendar.outbox')
        with store.db() as connection:
            rows = connection.execute(
                'SELECT o.* FROM calendar_outbox o JOIN calendar_events e ON e.id=o.event_id '
                'WHERE o.recipient_id=? OR e.organizer_id=? ORDER BY o.id', (user['id'], user['id'])).fetchall()
            return {'invitations': [service.safe_outbox(connection, user['id'], r) for r in rows], 'delivery': 'local_outbox_only'}

    from meetings.calendar.interchange import router as interchange_router
    api.include_router(interchange_router())
    return api
