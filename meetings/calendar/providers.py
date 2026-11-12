"""Calendar boundaries: local by default, external transports are opt-in.

Public projections contain free/busy only. No foreign event titles or raw
provider bodies leave this module. Network writes belong to sending.py.
"""
from datetime import datetime, timedelta, timezone
import os
import re
from typing import Protocol

from meetings import access, store
from meetings.auth import has_capability
from meetings.connectors.bitrix24 import Bitrix24Connector
from meetings.connectors.contracts import IntegrationError
from meetings.connectors.mock import digest


class CalendarProvider(Protocol):
    name: str
    def busy(self, user_ids, start, end): ...
    def create_event(self, draft, idem): ...
    def get_event(self, ref): ...
    def cancel_event(self, ref): ...


def configured_name():
    name = os.getenv('MEETINGS_CALENDAR_PROVIDER', 'mock')
    if name not in ('mock', 'bitrix24', 'google'):
        raise IntegrationError('config')
    return name


class MockCalendar:
    name = 'mock'

    def __init__(self, c, actor=None): self.c, self.actor = c, actor

    def busy(self, user_ids, start, end):
        from meetings.calendar.service import local_busy_intervals
        return local_busy_intervals(self.c, user_ids, start, end)

    def proof(self, user_ids): return {'provider': self.name}

    def create_event(self, draft, idem):
        # Local event creation remains in service.create_event, in the same transaction.
        raise IntegrationError('config')

    def get_event(self, ref):
        row = self.c.execute('SELECT * FROM calendar_events WHERE id=? AND organizer_id=?',
                             (ref, self.actor['id'])).fetchone()
        if not row: return None
        from meetings.calendar.service import event_out
        return event_out(self.c, self.actor['id'], row)

    def cancel_event(self, ref):
        # Caller must use a human-confirmed operation; this adapter does not grant it.
        raise IntegrationError('disabled')


def _bitrix_time(value, zone, *, all_day=False):
    """DATE_*_TS_UTC is server-shifted, NOT a UTC instant (Bitrix docs).

    Use DATE_FROM/TO with their named timezones; ambiguous DST input fails closed.
    """
    parsed = None
    try: parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (ValueError, AttributeError): pass
    if parsed is None:
        for pattern in ('%d.%m.%Y %H:%M:%S', '%m/%d/%Y %I:%M:%S %p', '%d.%m.%Y', '%m/%d/%Y'):
            try: parsed = datetime.strptime(str(value).upper(), pattern); break
            except ValueError: continue
    if parsed is None: raise IntegrationError('unavailable')
    if parsed.tzinfo is None:
        if not zone: raise IntegrationError('unavailable')
        try:
            tz = store.zone(zone)
            a, b = parsed.replace(tzinfo=tz, fold=0), parsed.replace(tzinfo=tz, fold=1)
            if a.utcoffset() != b.utcoffset(): raise IntegrationError('unavailable')
            if a.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) != parsed:
                raise IntegrationError('unavailable')
            parsed = a
        except store.TimeError: raise IntegrationError('unavailable') from None
    return parsed.astimezone(timezone.utc)


class Bitrix24Calendar(MockCalendar):
    name = 'bitrix24'

    def __init__(self, c, actor=None, *, connector=None):
        super().__init__(c, actor)
        self.connector = connector or Bitrix24Connector(c, actor['id'] if actor else None, read_faults=False)
        if not self.connector.enabled: raise IntegrationError('disabled')

    def mappings(self, user_ids):
        result = {}
        for uid in sorted(set(user_ids)):
            row = self.c.execute("SELECT x.external_id FROM user_external_ids x JOIN users u ON u.id=x.user_id "
                                 "WHERE u.active=1 AND x.connector=? AND x.user_id=?", (self.name, uid)).fetchone()
            if not row or not re.fullmatch(r'[1-9]\d{0,17}', row[0]): raise IntegrationError('config')
            result[str(uid)] = row[0]
        if len(set(result.values())) != len(result): raise IntegrationError('conflict')
        return result

    def proof(self, user_ids):
        return {'provider': self.name, 'mappings': self.mappings(user_ids),
                'destination_hash': digest(self.connector.webhook)}

    def busy(self, user_ids, start, end):
        mappings = self.mappings(user_ids)
        zone = store.zone(store.DISPLAY_ZONE)
        raw = self.connector.call('calendar.accessibility.get', {
            'users': [int(v) for v in mappings.values()],
            'from': (start.astimezone(zone)-timedelta(days=1)).date().isoformat(),
            'to': (end.astimezone(zone)+timedelta(days=1)).date().isoformat()})
        if not isinstance(raw, dict): raise IntegrationError('unavailable')
        intervals = []
        for external in mappings.values():
            rows = raw.get(external)
            if not isinstance(rows, list): raise IntegrationError('unavailable')
            for row in rows:
                if not isinstance(row, dict): raise IntegrationError('unavailable')
                if row.get('ACCESSIBILITY') == 'free': continue
                if row.get('ACCESSIBILITY') not in ('busy', 'absent', 'quest'): raise IntegrationError('unavailable')
                a = _bitrix_time(row.get('DATE_FROM'), row.get('TZ_FROM'))
                b = _bitrix_time(row.get('DATE_TO'), row.get('TZ_TO'))
                if row.get('DT_SKIP_TIME') == 'Y': b += timedelta(days=1)
                if b <= a: raise IntegrationError('unavailable')
                if a < end and start < b: intervals.append((a, b))
        return intervals

    def create_event(self, draft, idem):
        if not self.actor or not has_capability(self.actor, 'calendar.invite'):
            raise IntegrationError('forbidden')
        if not access.object_decision(self.c, self.actor['id'], 'meeting', draft['meeting_id'], 'calendar.invite').allowed:
            raise IntegrationError('forbidden')
        mappings = self.mappings([p['id'] for p in draft['participants']])
        marker = 'CallWise:' + digest(idem)
        # No source text or PII, and no automatic provider mail/reinvites.
        result = self.connector.call('calendar.event.add', {
            'type': 'user', 'ownerId': int(mappings[str(self.actor['id'])]), 'auto_detect_section': 'Y',
            'name': 'Встреча CallWise', 'description': marker,
            'from': draft['start_at'], 'to': draft['end_at'], 'skip_time': 'N',
            'timezone_from': 'UTC', 'timezone_to': 'UTC', 'private_event': 'Y', 'accessibility': 'busy',
            'is_meeting': 'Y', 'attendees': [int(v) for v in mappings.values()],
            'meeting': {'notify': False, 'reinvite': False, 'allow_invite': False, 'hide_guests': True}}, write=True)
        if not re.fullmatch(r'[1-9]\d{0,17}', str(result)):
            raise IntegrationError('uncertain', uncertain=True)
        return {'ref': 'bitrix24:event:' + str(result)}

    def _owned_ref(self, ref):
        if not re.fullmatch(r'bitrix24:event:[1-9]\d{0,17}', str(ref)): raise IntegrationError('forbidden')
        row = self.c.execute('SELECT e.meeting_id FROM calendar_provider_outbox o JOIN calendar_events e ON e.id=o.event_id '
                             'WHERE o.external_ref=? AND o.user_id=? AND o.status=?', (ref, self.actor['id'], 'sent')).fetchone()
        if not row or not access.object_decision(self.c, self.actor['id'], 'meeting', row[0], 'calendar.invite').allowed:
            raise IntegrationError('forbidden')
        return int(ref.rsplit(':', 1)[1])

    def get_event(self, ref):
        result = self.connector.call('calendar.event.getbyid', {'id': self._owned_ref(ref)})
        if result is None: return None
        if not isinstance(result, dict): raise IntegrationError('unavailable')
        return {'ref': ref, 'exists': True}  # no provider title/attendee projection

    def cancel_event(self, ref):
        result = self.connector.call('calendar.event.delete', {'id': self._owned_ref(ref)}, write=True)
        if result is not True: raise IntegrationError('uncertain', uncertain=True)
        return {'ref': ref, 'status': 'cancelled'}


class CalDAVCalendar:
    """Explicit P2 boundary; no fake success or undocumented transport."""
    name = 'caldav'
    def __init__(self, *args, **kwargs): raise IntegrationError('disabled')


class ExchangeCalendar(CalDAVCalendar): name = 'exchange'


def provider(c, actor=None):
    name = configured_name()
    if name == 'mock': return MockCalendar(c, actor)
    if name == 'bitrix24': return Bitrix24Calendar(c, actor)
    # Google is added through the existing validated freeBusy/events boundary.
    raise IntegrationError('disabled')
