"""Google adapter over the existing validated REST transport; off by default.

No attendee addresses or source text are exported. Participant free/busy is
checked using owner-managed calendar bindings; invitations remain local EML.
"""
import os
import re
import json
from urllib.parse import quote

from integrations.providers import GoogleCalendar as Transport
from integrations.contracts import IntegrationError as TransportError
from meetings import access, store
from meetings.auth import has_capability
from meetings.connectors.contracts import IntegrationError
from meetings.connectors.mock import digest


class GoogleCalendar:
    name = 'google'

    def __init__(self, c, actor=None, *, transport=None):
        if os.getenv('MEETINGS_GOOGLE_ENABLED', '0') != '1':
            raise IntegrationError('disabled')
        self.c, self.actor = c, actor
        self.credentials_env = os.getenv('MEETINGS_GOOGLE_CREDENTIALS_ENV', 'CALLWISE_GOOGLE_CREDENTIALS')
        if not re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}', self.credentials_env):
            raise IntegrationError('config')
        self.transport = transport or Transport(self.credentials_env)

    def call(self, method, *args, **kwargs):
        try:
            return getattr(self.transport, method)(*args, **kwargs)
        except TransportError as error:
            raise IntegrationError(error.code, uncertain=error.uncertain) from None

    def mappings(self, ids):
        try:
            raw = os.getenv('MEETINGS_GOOGLE_CALENDAR_MAP', '{}')
            if len(raw) > 100000:
                raise ValueError()
            configured = json.loads(raw)
            if not isinstance(configured, dict):
                raise ValueError()
        except (ValueError, TypeError):
            raise IntegrationError('config') from None
        mappings = {}
        for uid in sorted(set(ids)):
            row = self.c.execute("SELECT x.external_id FROM user_external_ids x JOIN users u ON u.id=x.user_id "
                "WHERE x.connector='google' AND x.user_id=? AND u.active=1", (uid,)).fetchone()
            value = configured.get(str(uid), row[0] if row else None)
            if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_@.+-]{3,300}', value):
                raise IntegrationError('config')
            mappings[str(uid)] = value
        if len(set(mappings.values())) != len(mappings):
            raise IntegrationError('conflict')
        return mappings

    def proof(self, ids):
        return {'provider': self.name, 'mapping_hash': digest(self.mappings(ids)),
                'destination_hash': digest([self.credentials_env, os.getenv(self.credentials_env, '')])}

    def busy(self, ids, start, end):
        mappings = self.mappings(ids)
        raw = self.call('busy', list(mappings.values()), store.iso_utc(start), store.iso_utc(end))
        try:
            return [(store.parse_aware(p['start']), store.parse_aware(p['end']))
                    for key in mappings.values() for p in raw[key]]
        except (KeyError, TypeError, store.TimeError):
            raise IntegrationError('unavailable') from None

    def create_event(self, draft, idem):
        if not self.actor or not has_capability(self.actor, 'calendar.invite') or not access.object_decision(
                self.c, self.actor['id'], 'meeting', draft['meeting_id'], 'calendar.invite').allowed:
            raise IntegrationError('forbidden')
        mapping = self.mappings([p['id'] for p in draft['participants']])
        calendar = mapping[str(self.actor['id'])]
        event_id = 'c' + digest([calendar, idem])  # lowercase hex is valid base32hex
        event = {'id': event_id, 'summary': 'Встреча Фокус', 'visibility': 'private',
                 'start': {'dateTime': draft['start_at']}, 'end': {'dateTime': draft['end_at']},
                 'extendedProperties': {'private': {'callwise': digest(idem)}}}
        previous = self.call('get', calendar, event_id)
        if previous is not None:
            try:
                matches = all(store.parse_aware(previous[k]['dateTime']) == store.parse_aware(event[k]['dateTime'])
                              for k in ('start', 'end')) and previous.get('extendedProperties') == event['extendedProperties']
            except (KeyError, TypeError, store.TimeError):
                matches = False
            if not matches:
                raise IntegrationError('conflict')
            result = previous
        else:
            result = self.call('insert', calendar, event)
        if result.get('id') != event_id:
            raise IntegrationError('uncertain', uncertain=True)
        return {'ref': 'google:event:' + event_id}

    def owned(self, ref):
        if not self.actor or not re.fullmatch(r'google:event:c[0-9a-f]{64}', str(ref)):
            raise IntegrationError('forbidden')
        row = self.c.execute("SELECT e.meeting_id FROM calendar_provider_outbox o JOIN calendar_events e ON e.id=o.event_id "
            "WHERE o.user_id=? AND o.external_ref=? AND o.status='sent'", (self.actor['id'], ref)).fetchone()
        if not row or not access.object_decision(self.c, self.actor['id'], 'meeting', row[0], 'calendar.invite').allowed:
            raise IntegrationError('forbidden')
        calendar = self.mappings([self.actor['id']])[str(self.actor['id'])]
        return calendar, ref.rsplit(':', 1)[1]

    def get_event(self, ref):
        calendar, eid = self.owned(ref)
        row = self.call('get', calendar, eid)
        return {'ref': ref, 'exists': True} if row else None

    def cancel_event(self, ref):
        calendar, eid = self.owned(ref)
        # Called only by a separately confirmed cancellation operation.
        self.call('request', 'DELETE', 'calendars/' + quote(calendar, safe='') + '/events/' + eid + '?sendUpdates=none', write=True)
        return {'ref': ref, 'status': 'cancelled'}
