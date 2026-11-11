"""Durable reservation + explicit synchronization. No automatic ambiguous CRM retries."""
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import storage
from integrations.contracts import IntegrationError
from integrations.providers import GoogleCalendar, BitrixCRM, instant
from integrations.settings import bindings, network_allowed


def now():
    return datetime.now(timezone.utc).isoformat()


def overlap(start, end, other_start, other_end):
    return instant(start) < instant(other_end) and instant(other_start) < instant(end)


def decode(row):
    if row is None: return None
    result = dict(row)
    payload = json.loads(result.pop('payload'))
    result.update(payload)
    return result


def get_booking(booking_id):
    with storage.connect() as db:
        return decode(db.execute('SELECT * FROM cloud_bookings WHERE id=?', (booking_id,)).fetchone())


def public_booking(row):
    # Administrative status API: no PII, calendar IDs, credentials or payload dump.
    return {key: row.get(key) for key in ('id', 'agent_id', 'interaction_id', 'calendar_status', 'crm_status',
                                         'crm_id', 'error_code', 'created_at', 'updated_at')}


class CloudBookingRepository:
    demo = False

    def __init__(self, agent_id, binding, business, calendar=None, crm=None):
        self.agent_id, self.binding, self.business = agent_id, binding, business
        self.calendar = calendar or GoogleCalendar(binding.google_credentials_env)
        self.crm = crm if crm is not None else BitrixCRM(binding.bitrix_webhook_env) if binding.bitrix_webhook_env else None
        self.tz = ZoneInfo(business.timezone)
        employees = {e for s in business.knowledge.get('services', []) for e in s['employees']}
        if not employees.issubset(binding.calendars) or any(not value.strip() for value in binding.calendars.values()):
            raise IntegrationError('config')

    def existing(self, interaction_id):
        with storage.connect() as db:
            return decode(db.execute('SELECT * FROM cloud_bookings WHERE agent_id=? AND interaction_id=?',
                                     (self.agent_id, interaction_id)).fetchone())

    def for_date(self, day):
        network_allowed()
        start = datetime.fromisoformat(day).replace(tzinfo=self.tz)
        end = start + timedelta(days=1)
        busy = self.calendar.busy(list(set(self.binding.calendars.values())), start.isoformat(), end.isoformat())
        with storage.connect() as db:
            reserved = [dict(row) for row in db.execute("SELECT * FROM cloud_bookings WHERE calendar_status != 'failed'")]
        result = []
        for employee, calendar_id in self.binding.calendars.items():
            intervals = list(busy[calendar_id])
            intervals += [{'start': r['start'], 'end': r['end']} for r in reserved
                          if r['calendar_id'] == calendar_id and overlap(start.isoformat(), end.isoformat(), r['start'], r['end'])]
            # Manual external changes need reconciliation; never silently free a confirmed local reservation.
            for interval in intervals:
                result.append({'employee': employee, 'datetime': interval['start'],
                               'duration_minutes': (instant(interval['end']) - instant(interval['start'])).total_seconds() / 60})
        return result

    def create(self, booking):
        network_allowed()
        from services.customer_safety import enabled, accepted
        if enabled():
            state = storage.get_interaction(booking['interaction_id'])
            if not state or not state.get('safety', {}).get('enabled') or not accepted(state):
                raise IntegrationError('consent')
        values = booking['structured_data']['values']
        for field in ('customer_name', 'phone', 'service', 'datetime', 'employee'):
            proof = booking['structured_data'].get('action_provenance', {}).get(field, {})
            if not proof.get('confirmed') or proof.get('value') != values.get(field):
                raise IntegrationError('conflict')
        booking_id = hashlib.sha256((self.agent_id + '\0' + booking['interaction_id']).encode()).hexdigest()
        booking = dict(booking, id=booking_id)
        start = instant(booking['datetime'])
        end = start.astimezone(timezone.utc) + timedelta(minutes=booking['duration_minutes'])
        calendar_id = self.binding.calendars[booking['employee']]
        stamp = now()
        with storage.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = decode(db.execute('SELECT * FROM cloud_bookings WHERE id=?', (booking_id,)).fetchone())
            if existing:
                self.verify_same(existing, booking)
                return existing
            for row in db.execute("SELECT start,end FROM cloud_bookings WHERE calendar_id=? AND calendar_status != 'failed'", (calendar_id,)):
                if overlap(start.isoformat(), end.isoformat(), row['start'], row['end']):
                    raise IntegrationError('conflict')
            db.execute('INSERT INTO cloud_bookings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (booking_id, self.agent_id, booking['interaction_id'], self.binding.fingerprint(), calendar_id,
                        start.isoformat(), end.isoformat(), json.dumps(booking, ensure_ascii=False),
                        'pending', 'pending' if self.crm else 'not_configured', None, None, 0, stamp, stamp))
        return self.sync(booking_id)

    def verify_same(self, existing, booking):
        if existing['binding_hash'] != self.binding.fingerprint() or existing['structured_data']['values'] != booking['structured_data']['values']:
            raise IntegrationError('conflict')

    def update(self, booking_id, **values):
        allowed = {'calendar_status', 'crm_status', 'crm_id', 'error_code'}
        if not set(values).issubset(allowed): raise ValueError('Invalid update')
        values['updated_at'] = now()
        with storage.connect() as db:
            db.execute('UPDATE cloud_bookings SET ' + ','.join(key + '=?' for key in values) + ' WHERE id=?',
                       (*values.values(), booking_id))

    def event(self, row):
        values = row['structured_data']['values']
        digest = hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return {'id': row['id'], 'summary': 'Callwise: ' + values['service'],
                'description': f"Клиент: {values['customer_name']}\nТелефон: {values['phone']}\nСотрудник: {values['employee']}",
                'start': {'dateTime': row['start'], 'timeZone': self.business.timezone},
                'end': {'dateTime': row['end'], 'timeZone': self.business.timezone},
                'visibility': 'private', 'transparency': 'opaque',
                'extendedProperties': {'private': {'callwise_id': row['id'], 'callwise_payload': digest}}}

    def verify_event(self, row, found):
        try:
            expected = self.event(row)
            if (found['id'] != row['id'] or found.get('status') != 'confirmed'
                    or found.get('extendedProperties') != expected['extendedProperties']
                    or instant(found['start']['dateTime']) != instant(row['start'])
                    or instant(found['end']['dateTime']) != instant(row['end'])):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise IntegrationError('conflict', uncertain=True) from None

    def sync(self, booking_id):
        network_allowed()
        row = get_booking(booking_id)
        if row is None or row['agent_id'] != self.agent_id or row['binding_hash'] != self.binding.fingerprint():
            raise IntegrationError('config')
        from services.customer_safety import enabled, accepted
        if enabled():
            state = storage.get_interaction(row['interaction_id'])
            if not state or not state.get('safety', {}).get('enabled') or not accepted(state):
                raise IntegrationError('consent')
        with storage.connect() as db:
            cursor = db.execute('UPDATE cloud_bookings SET lease_until=? WHERE id=? AND lease_until<?',
                                (time.time() + 180, booking_id, time.time()))
            if cursor.rowcount != 1: raise IntegrationError('busy')
        try:
            if row['calendar_status'] != 'confirmed':
                try:
                    found = self.calendar.get(row['calendar_id'], row['id'])
                    if found is not None:
                        self.verify_event(row, found)
                    elif row['calendar_status'] == 'unknown':
                        # A missing event after an ambiguous insert isn't proof that it was never created.
                        raise IntegrationError('uncertain', uncertain=True)
                    else:
                        if instant(row['start']) <= datetime.now(timezone.utc):
                            raise IntegrationError('conflict')
                        busy = self.calendar.busy([row['calendar_id']], row['start'], row['end'])[row['calendar_id']]
                        if any(overlap(row['start'], row['end'], i['start'], i['end']) for i in busy):
                            raise IntegrationError('conflict')
                        # Persist ambiguous state BEFORE network write; crash cannot cause blind duplication.
                        self.update(booking_id, calendar_status='unknown')
                        found = self.calendar.insert(row['calendar_id'], self.event(row))
                        self.verify_event(row, found)
                    self.update(booking_id, calendar_status='confirmed', error_code=None)
                except IntegrationError as error:
                    status = 'unknown' if error.uncertain or row['calendar_status'] == 'unknown' else 'failed'
                    self.update(booking_id, calendar_status=status, error_code=error.code)
                    return get_booking(booking_id)
            row = get_booking(booking_id)
            if self.crm and row['crm_status'] != 'synced':
                try:
                    # Do not export a cancelled or manually changed appointment as a fresh confirmed booking.
                    found_event = self.calendar.get(row['calendar_id'], row['id'])
                    if found_event is None: raise IntegrationError('conflict')
                    self.verify_event(row, found_event)
                    found = self.crm.find(row['id'])
                    if found is None:
                        if row['crm_status'] == 'unknown':
                            raise IntegrationError('uncertain', uncertain=True)
                        self.update(booking_id, crm_status='unknown')
                        found = self.crm.create(row)
                    self.update(booking_id, crm_status='synced', crm_id=found, error_code=None)
                except IntegrationError as error:
                    self.update(booking_id, crm_status='unknown' if error.uncertain or row['crm_status'] == 'unknown' else 'failed', error_code=error.code)
            return get_booking(booking_id)
        finally:
            with storage.connect() as db:
                db.execute('UPDATE cloud_bookings SET lease_until=0 WHERE id=?', (booking_id,))


def repository_for(config):
    binding = bindings().get(config.id)
    return CloudBookingRepository(config.id, binding, config.business) if binding else None
