"""Authenticated ICS/EML export and confirmed, busy-only personal ICS imports."""
from datetime import timedelta
from email.message import EmailMessage
from email.policy import SMTP
import hashlib
import hmac
import logging
import re
import secrets

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import Response

from meetings import access, confirmations, store
from meetings.auth import MeetError, MeetRoute, _secret, current_user, require, has_capability
from meetings.api import ConfirmTokenIn
from meetings.calendar import ics, service

ACTION = 'calendar.import'


FEED_TOKEN = re.compile(r'(/api/meet/calendar/feed/)[^\s/?]+')


def _redact_feed(value):
    if isinstance(value, (int, float)) or value is None:
        return value
    text = str(value)  # httpx passes URL objects
    return FEED_TOKEN.sub(r'\1[REDACTED]', text) if FEED_TOKEN.search(text) else value


class FeedRedaction(logging.Filter):
    def filter(self, record):
        # Redact inside the arguments and keep their shape: uvicorn's access
        # formatter unpacks record.args (client, method, path, version, status).
        if isinstance(record.args, tuple):
            record.args = tuple(_redact_feed(arg) for arg in record.args)
        elif isinstance(record.args, dict):
            record.args = {key: _redact_feed(arg) for key, arg in record.args.items()}
        record.msg = _redact_feed(record.msg)
        return True


# Bearer links must not appear in the ordinary server/client access logs.
for name in ('uvicorn.access', 'httpx', 'httpcore'):
    logging.getLogger(name).addFilter(FeedRedaction())


def missing(user=None, kind='calendar', object_id=None):
    return MeetError(404, 'not_found', 'Не найдено или нет доступа.', audit={
        'user_id': user['id'] if user else None, 'action': 'calendar.access_denied',
        'object_type': kind, 'object_id': object_id, 'result': 'denied', 'error_code': 'not_found'})


def stamp_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def export_events(c, user, event_id=None, *, busy_only=False):
    require(user, 'calendar.view', action='calendar.export')
    query = ('SELECT DISTINCT e.* FROM calendar_events e LEFT JOIN calendar_event_participants p ON p.event_id=e.id '
             'WHERE (e.organizer_id=? OR p.user_id=?)')
    args = [user['id'], user['id']]
    if event_id is not None:
        query += ' AND e.id=?'; args.append(event_id)
    rows = c.execute(query + ' ORDER BY e.start_at,e.id', args).fetchall()
    if event_id is not None and not rows: raise missing(user, 'calendar_event', event_id)
    result = []
    for row in rows:
        output = service.event_out(c, user['id'], row)
        uid = hmac.new(_secret(), f"calendar-event:{row['id']}".encode(), hashlib.sha256).hexdigest()
        result.append({**output, 'uid': uid + '@focus.invalid',
                       'title': 'Занято' if busy_only else output['title']})
    return result


def response(data, media_type='text/calendar', filename='focus.ics'):
    return Response(data, media_type=media_type, headers={
        'Content-Disposition': f'attachment; filename="{filename}"',
        'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
        'X-Content-Type-Options': 'nosniff'})


def router():
    api = APIRouter(route_class=MeetRoute)

    @api.get('/api/meet/calendar/export.ics')
    def export(request: Request, event_id: int | None = None):
        user = current_user(request)
        with store.db() as c:
            events = export_events(c, user, event_id)
            store.audit(c, user['id'], 'calendar_export', object_type='calendar', event_count=len(events))
            return response(ics.calendar(events))

    @api.post('/api/meet/calendar/subscriptions')
    def subscribe(request: Request):
        user = current_user(request); require(user, 'calendar.view', action='calendar.subscribe')
        stamp = store.now(); expiry = store.iso_utc(store.parse_aware(stamp) + timedelta(days=90))
        value = f"{user['id']}.{int(store.parse_aware(expiry).timestamp())}.{secrets.token_urlsafe(24)}"
        token = value + '.' + hmac.new(_secret(), ('calendar-feed:' + value).encode(), hashlib.sha256).hexdigest()
        with store.write_tx() as c:
            # New generation automatically revokes earlier copies; at most one active bearer link.
            c.execute('UPDATE calendar_subscriptions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL', (stamp, user['id']))
            sid = c.execute('INSERT INTO calendar_subscriptions(user_id,token_hash,created_at,expires_at) VALUES (?,?,?,?)',
                            (user['id'], stamp_hash(token), stamp, expiry)).lastrowid
            store.audit(c, user['id'], 'calendar_subscription_created', object_type='calendar_subscription', object_id=sid)
        return {'id': sid, 'path': f'/api/meet/calendar/feed/{token}.ics', 'expires_at': expiry,
                'scope': 'busy_only', 'notice': 'Ссылка открывает только время занятости. Храните её как пароль. Предыдущая ссылка отозвана.'}

    @api.get('/api/meet/calendar/subscriptions')
    def subscriptions(request: Request):
        user = current_user(request); require(user, 'calendar.view', action='calendar.subscriptions')
        with store.db() as c:
            return {'subscriptions': [dict(row) for row in c.execute(
                'SELECT id,created_at,expires_at,revoked_at FROM calendar_subscriptions WHERE user_id=? ORDER BY id DESC', (user['id'],))]}

    @api.delete('/api/meet/calendar/subscriptions/{subscription_id}')
    def revoke(subscription_id: int, request: Request):
        user = current_user(request); require(user, 'calendar.view', action='calendar.subscription.revoke')
        with store.write_tx() as c:
            row = c.execute('SELECT id FROM calendar_subscriptions WHERE id=? AND user_id=?', (subscription_id, user['id'])).fetchone()
            if not row: raise missing(user, 'calendar_subscription', subscription_id)
            c.execute('UPDATE calendar_subscriptions SET revoked_at=COALESCE(revoked_at,?) WHERE id=?', (store.now(), subscription_id))
            store.audit(c, user['id'], 'calendar_subscription_revoked', object_type='calendar_subscription', object_id=subscription_id)
        return {'status': 'revoked'}

    @api.get('/api/meet/calendar/feed/{token}.ics')
    def feed(token: str):
        # No cookie identity: a signed, revocable bearer with a narrowly fixed read scope.
        if not re.fullmatch(r'[0-9]{1,18}\.[0-9]{1,12}\.[A-Za-z0-9_-]{32}\.[a-f0-9]{64}', token): raise missing()
        value, signature = token.rsplit('.', 1)
        if not hmac.compare_digest(signature, hmac.new(_secret(), ('calendar-feed:' + value).encode(), hashlib.sha256).hexdigest()): raise missing()
        with store.db() as c:
            row = c.execute('SELECT * FROM calendar_subscriptions WHERE token_hash=? AND revoked_at IS NULL AND expires_at>?',
                            (stamp_hash(token), store.now())).fetchone()
            user = access.load_user(c, row['user_id']) if row else None
            if not user or not has_capability(user, 'calendar.view'): raise missing()
            events = export_events(c, user, busy_only=True)
            store.audit(c, user['id'], 'calendar_feed_read', object_type='calendar_subscription', object_id=row['id'], event_count=len(events))
            return response(ics.calendar(events))

    @api.post('/api/meet/calendar/import/preview')
    async def import_preview(request: Request, file: UploadFile = File(...), timezone: str = Form('Europe/Minsk')):
        user = current_user(request); require(user, 'calendar.view', action='calendar.import.preview')
        data = await file.read(ics.MAX_BYTES + 1)
        try: intervals = ics.parse(data, timezone)
        except ics.ICSError as error: raise MeetError(422, 'invalid_ics', str(error)) from None
        digest = stamp_hash(str(intervals))
        with store.write_tx() as c:
            old = c.execute('SELECT sha256 FROM calendar_import_state WHERE user_id=?', (user['id'],)).fetchone()
            body = {'intervals': intervals, 'sha256': digest, 'previous_sha256': old['sha256'] if old else None,
                    'notice': 'Будет заменена только ваша ранее импортированная занятость ICS. Названия и участники не сохраняются. Встречи Фокуса не меняются.'}
            token = confirmations.create(c, user, ACTION, 'calendar', user['id'], None, body)
            store.audit(c, user['id'], 'calendar_import_preview', object_type='calendar', stage='preview',
                        confirmation_id=token['confirmation_id'], interval_count=len(intervals))
            return {**token, 'preview': body}

    @api.post('/api/meet/calendar/import/confirm')
    def import_confirm(payload: ConfirmTokenIn, request: Request):
        user = current_user(request); require(user, 'calendar.view', action='calendar.import.confirm')
        with store.write_tx() as c:
            pending = confirmations.load(c, user, payload.confirmation_id, ACTION, 'calendar', user['id'], payload.idempotency_key)
            if pending.get('already'): return {**pending['result'], 'already_confirmed': True}
            body = pending['payload']
            old = c.execute('SELECT sha256 FROM calendar_import_state WHERE user_id=?', (user['id'],)).fetchone()
            if (old['sha256'] if old else None) != body['previous_sha256']:
                raise MeetError(409, 'stale', 'Импортированная занятость изменилась. Нужен новый предпросмотр.')
            unchanged = old is not None and old['sha256'] == body['sha256']
            if not unchanged:
                c.execute("DELETE FROM calendar_busy WHERE user_id=? AND source='ics-upload'", (user['id'],))
                for interval in body['intervals']:
                    service.add_busy(c, user['id'], **interval, source='ics-upload')
                c.execute('INSERT INTO calendar_import_state(user_id,sha256,imported_at,interval_count) VALUES (?,?,?,?) '
                          'ON CONFLICT(user_id) DO UPDATE SET sha256=excluded.sha256,imported_at=excluded.imported_at,interval_count=excluded.interval_count',
                          (user['id'], body['sha256'], store.now(), len(body['intervals'])))
            result = {'status': 'imported', 'interval_count': len(body['intervals']), 'unchanged': unchanged}
            confirmations.finish(c, payload.confirmation_id, payload.idempotency_key, result)
            store.audit(c, user['id'], 'calendar_import_confirm', object_type='calendar', stage='confirm',
                        confirmation_id=payload.confirmation_id, interval_count=len(body['intervals']))
            return {**result, 'already_confirmed': False}

    @api.get('/api/meet/calendar/outbox/{invitation_id}/download.eml')
    def invitation_file(invitation_id: int, request: Request):
        user = current_user(request); require(user, 'calendar.view', action='calendar.invitation.download')
        with store.db() as c:
            row = c.execute('SELECT o.*,e.organizer_id FROM calendar_outbox o JOIN calendar_events e ON e.id=o.event_id '
                            'WHERE o.id=? AND (o.recipient_id=? OR e.organizer_id=?)', (invitation_id, user['id'], user['id'])).fetchone()
            if not row: raise missing(user, 'calendar_invitation', invitation_id)
            event = export_events(c, user, row['event_id'])[0]
            # Both downloader and addressee must still be allowed to see the title.
            original = c.execute('SELECT meeting_id FROM calendar_events WHERE id=?', (row['event_id'],)).fetchone()
            if not original['meeting_id'] or not store.can_read_meeting(c, row['recipient_id'], original['meeting_id']):
                event['title'] = 'Встреча (нет доступа к материалам)'
            message = EmailMessage(policy=SMTP)
            message['From'] = f"user-{row['organizer_id']}@demo.invalid"
            message['To'] = f"user-{row['recipient_id']}@demo.invalid"
            message['Subject'] = 'Приглашение: ' + event['title'].replace('\r', ' ').replace('\n', ' ')
            message['Date'] = store.parse_aware(event['created_at'])
            message['Message-ID'] = f"<{stamp_hash(event['uid'] + ':' + str(row['recipient_id']))}@focus.invalid>"
            message.set_content('Локальный файл приглашения. Письмо не отправлено.\n'
                                + service.local_label(store.parse_aware(event['start_at']), event['timezone'])
                                + '\n' + event['title'])
            message.add_attachment(ics.calendar([event]), maintype='text', subtype='calendar', filename='invitation.ics')
            store.audit(c, user['id'], 'calendar_invitation_download', object_type='calendar_invitation', object_id=invitation_id)
            return response(message.as_bytes(), 'message/rfc822', f'invitation-{invitation_id}.eml')

    return api
