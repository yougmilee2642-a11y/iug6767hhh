import json
from datetime import date, timedelta
import httpx
import pytest
import storage
from agents.runtime import AgentRuntime, new_interaction
from integrations.booking import CloudBookingRepository
from integrations.contracts import IntegrationError
from integrations.providers import GoogleCalendar, BitrixCRM
from integrations.settings import Binding, public_status
from prompts import load_agent
from providers.base import ModelReply, ToolCall
from services.booking_service import BookingService
from tools.booking import booking_tools
from tools.handoff import handoff_tool


class Calendar:
    def __init__(self):
        self.events, self.intervals, self.writes = {}, [], 0
        self.fail = None
    def busy(self, ids, start, end):
        if self.fail == 'read': raise IntegrationError('unavailable')
        return {key: list(self.intervals) for key in ids}
    def get(self, calendar_id, event_id):
        return self.events.get((calendar_id, event_id))
    def insert(self, calendar_id, event):
        self.writes += 1
        if self.fail == 'unknown_missing': raise IntegrationError('unavailable', uncertain=True)
        result = dict(event, status='confirmed')
        self.events[(calendar_id, event['id'])] = result
        if self.fail == 'unknown_saved': raise IntegrationError('unavailable', uncertain=True)
        return result


class CRM:
    def __init__(self): self.rows, self.writes, self.fail = {}, 0, None
    def find(self, booking_id): return self.rows.get(booking_id)
    def create(self, row):
        self.writes += 1
        if self.fail == 'unknown_missing': raise IntegrationError('unavailable', uncertain=True)
        self.rows[row['id']] = '123'
        if self.fail == 'unknown_saved': raise IntegrationError('unavailable', uncertain=True)
        return '123'


class Provider:
    def __init__(self, *replies): self.replies = iter(replies)
    def complete(self, messages, tools): return next(self.replies)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'DB_PATH', tmp_path / 'test.db')
    monkeypatch.setattr(storage, 'DATA_DIR', tmp_path)
    monkeypatch.setenv('CALLWISE_CLOUD_INTEGRATIONS_ENABLED', 'true')
    monkeypatch.setenv('CALLWISE_INTEGRATIONS_FILE', '')
    storage.initialize_db()
    config = load_agent()
    binding = Binding(calendars={'Анна': 'anna@example.com', 'Мария': 'maria@example.com', 'Ольга': 'olga@example.com'}, bitrix_webhook_env='TEST_BITRIX')
    calendar, crm = Calendar(), CRM()
    repository = CloudBookingRepository(config.id, binding, config.business, calendar, crm)
    return config, repository, calendar, crm


def booking(interaction='interaction-one'):
    values = {'customer_name': 'Лёша', 'phone': '+375291234567', 'service': 'маникюр',
              'datetime': (date.today() + timedelta(days=1)).isoformat() + 'T18:30:00+03:00', 'employee': 'Анна'}
    return {'id': 'ignored', 'interaction_id': interaction, **values, 'duration_minutes': 60, 'created_at': 'unused',
            'structured_data': {'values': values, 'action_provenance': {key: {'value': value, 'confirmed': True} for key, value in values.items()}}}


def test_booking_calendar_then_crm_and_dedup(env):
    _, repo, calendar, crm = env
    row = repo.create(booking())
    assert row['calendar_status'] == 'confirmed' and row['crm_status'] == 'synced'
    assert calendar.writes == crm.writes == 1
    assert repo.create(booking())['id'] == row['id']
    repo.sync(row['id'])
    assert calendar.writes == crm.writes == 1
    assert repo.for_date(booking()['datetime'][:10])


def test_no_consent_no_external_write(env):
    repo = env[1]
    row = booking()
    row['structured_data']['action_provenance']['phone']['confirmed'] = False
    with pytest.raises(IntegrationError): repo.create(row)
    assert env[2].writes == env[3].writes == 0


@pytest.mark.parametrize('where', ['calendar', 'crm'])
@pytest.mark.parametrize('saved', [False, True])
def test_ambiguous_response_reconciles_never_blind_retry(env, where, saved):
    _, repo, calendar, crm = env
    provider = calendar if where == 'calendar' else crm
    provider.fail = 'unknown_saved' if saved else 'unknown_missing'
    row = repo.create(booking())
    assert row[where + '_status'] == 'unknown'
    if where == 'calendar': assert crm.writes == 0
    else: assert calendar.writes == 1
    provider.fail = None
    reconciled = repo.sync(row['id'])
    assert provider.writes == 1
    expected = ('confirmed' if where == 'calendar' else 'synced') if saved else 'unknown'
    assert reconciled[where + '_status'] == expected


def test_busy_recheck_blocks_booking(env):
    _, repo, calendar, crm = env
    row = booking()
    calendar.intervals = [{'start': row['datetime'], 'end': row['datetime'][:10] + 'T19:30:00+03:00'}]
    result = repo.create(row)
    assert result['calendar_status'] == 'failed'
    assert calendar.writes == crm.writes == 0


def test_unknown_blocks_overlapping_other_agent(env):
    config, repo, calendar, crm = env
    calendar.fail = 'unknown_missing'
    repo.create(booking())
    other = CloudBookingRepository('other-business', repo.binding, config.business, calendar, crm)
    with pytest.raises(IntegrationError): other.create(booking('other-interaction'))
    assert calendar.writes == 1


def test_changed_payload_or_binding_cannot_reuse_booking(env):
    _, repo, _, _ = env
    row = repo.create(booking())
    changed = booking()
    changed['structured_data']['values']['phone'] = '+375299999999'
    changed['structured_data']['action_provenance']['phone']['value'] = '+375299999999'
    with pytest.raises(IntegrationError): repo.create(changed)
    repo.binding.calendars['Анна'] = 'another@example.com'
    with pytest.raises(IntegrationError): repo.sync(row['id'])


def test_lease_prevents_parallel_sync(env):
    row = env[1].create(booking())
    import time
    with storage.connect() as db: db.execute('UPDATE cloud_bookings SET lease_until=? WHERE id=?', (time.time() + 30, row['id']))
    with pytest.raises(IntegrationError, match='обрабатывается'): env[1].sync(row['id'])


def test_local_only_and_simulation_block_network(env, monkeypatch, tmp_path):
    _, repo, calendar, crm = env
    monkeypatch.setenv('CALLWISE_LOCAL_ONLY', 'true')
    with pytest.raises(IntegrationError): repo.create(booking())
    monkeypatch.setenv('CALLWISE_LOCAL_ONLY', 'false')
    with storage.isolated_database(tmp_path / 'simulation.db'):
        storage.initialize_db()
        with pytest.raises(IntegrationError): repo.for_date(booking()['datetime'][:10])
    assert calendar.writes == crm.writes == 0


def test_runtime_confirmation_end_to_end(env):
    config, repo, calendar, crm = env
    values = booking()['structured_data']['values']
    provider = Provider(ModelReply(tool_calls=[ToolCall('slots', 'check_slots', {'service': 'маникюр', 'date': values['datetime'][:10], 'preferred_time': '18:00'})]),
                        ModelReply(tool_calls=[ToolCall('book', 'create_booking', values)]))
    runtime = AgentRuntime(config, provider, [*booking_tools(BookingService(config.business, repo), config.fields), handoff_tool()])
    state = new_interaction(config)
    runtime.turn(state, 'Хочу завтра после шести на маникюр')
    result = runtime.turn(state, 'На 18:30. Меня зовут Лёша. Мой телефон +375291234567')
    assert result['status'] == 'awaiting_confirmation'
    assert calendar.writes == crm.writes == 0
    result = runtime.turn(state, 'Да, подтверждаю')
    assert result['status'] == 'completed' and 'подтверждена календарём' in result['text']
    assert calendar.writes == crm.writes == 1
    assert state['tool_events'][-1]['result']['booking']['crm_status'] == 'synced'


@pytest.mark.parametrize('data', [{}, {'calendars': {'anna': {'errors': [{'reason': 'notFound'}], 'busy': []}}},
                                 {'calendars': {'anna': {'busy': [{'start': '2027-01-01T10:00:00', 'end': '2027-01-01T11:00:00'}]}}}])
def test_google_missing_or_invalid_busy_fails_closed(env, data):
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=data)))
    provider = GoogleCalendar('NONE', client, token=lambda: 'fake')
    with pytest.raises(IntegrationError): provider.busy(['anna'], '2027-01-01T00:00:00Z', '2027-01-02T00:00:00Z')
    client.close()


def test_google_request_fields_and_timeout_redaction(env):
    def handler(request):
        assert request.headers['authorization'] == 'Bearer fake'
        data = json.loads(request.content)
        assert data['items'] == [{'id': 'anna'}]
        return httpx.Response(200, json={'calendars': {'anna': {'busy': []}}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert GoogleCalendar('NONE', client, token=lambda: 'fake').busy(['anna'], '2027-01-01T00:00:00Z', '2027-01-02T00:00:00Z') == {'anna': []}


def test_google_read_timeout_is_not_unknown_write(env):
    def timeout(request): raise httpx.ReadTimeout('unsafe secret response', request=request)
    with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
        calendar = GoogleCalendar('NONE', client, token=lambda: 'fake')
        with pytest.raises(IntegrationError) as error:
            calendar.busy(['anna'], '2027-01-01T00:00:00Z', '2027-01-02T00:00:00Z')
        assert not error.value.uncertain and 'secret' not in str(error.value)
        with pytest.raises(IntegrationError) as error: calendar.insert('anna', {'id': 'fake-id'})
        assert error.value.uncertain


def test_bitrix_deal_matching_and_secret_redaction(env, monkeypatch, caplog):
    monkeypatch.setenv('TEST_BITRIX', 'https://test.bitrix24.by/rest/1/SECRET_TOKEN/')
    def handler(request):
        assert json.loads(request.content)['filter'] == {'=ORIGINATOR_ID': 'callwise', '=ORIGIN_ID': 'booking'}
        return httpx.Response(200, json={'result': [{'ID': '123', 'ORIGINATOR_ID': 'callwise', 'ORIGIN_ID': 'booking'}]})
    import logging
    with caplog.at_level(logging.INFO), httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert BitrixCRM('TEST_BITRIX', client).find('booking') == '123'
    assert 'SECRET_TOKEN' not in caplog.text


@pytest.mark.parametrize('url', ['http://localhost/rest/1/secret/', 'https://evil.com/rest/1/secret/', 'https://x.bitrix24.by.evil.com/rest/1/secret/'])
def test_bitrix_rejects_arbitrary_url_before_request(env, monkeypatch, url):
    monkeypatch.setenv('TEST_BITRIX', url)
    with pytest.raises(IntegrationError): BitrixCRM('TEST_BITRIX').find('abc')


def test_status_does_not_expose_secrets_or_probe_network(env):
    assert 'agents' in public_status()
    from integrations.booking import public_booking
    result = json.dumps(public_booking(env[1].create(booking())))
    assert '+375' not in result and 'calendar_id' not in result and 'binding_hash' not in result


def test_both_rest_adapters_end_to_end(env, monkeypatch):
    config, repo, _, _ = env
    monkeypatch.setenv('TEST_BITRIX', 'https://test.bitrix24.by/rest/1/SECRET_TOKEN/')
    events, deals, calls = {}, {}, []
    def handler(request):
        calls.append(request.url.path)
        body = json.loads(request.content) if request.content else {}
        if request.url.path.endswith('freeBusy'):
            return httpx.Response(200, json={'calendars': {item['id']: {'busy': []} for item in body['items']}})
        if request.method == 'GET':
            event = events.get(request.url.path.rsplit('/', 1)[1])
            return httpx.Response(200, json=event) if event else httpx.Response(404, json={})
        if request.url.path.endswith('/events'):
            assert request.url.params['sendUpdates'] == 'none'
            assert body['visibility'] == 'private' and body['transparency'] == 'opaque'
            assert body['start']['timeZone'] == 'Europe/Minsk'
            assert 'attendees' not in body
            event = dict(body, status='confirmed'); events[event['id']] = event
            return httpx.Response(200, json=event)
        if request.url.path.endswith('crm.deal.list.json'):
            item = deals.get(body['filter']['=ORIGIN_ID'])
            return httpx.Response(200, json={'result': [item] if item else []})
        if request.url.path.endswith('crm.deal.add.json'):
            assert events  # Calendar creation must precede CRM mutation.
            fields = body['fields']; deals[fields['ORIGIN_ID']] = dict(fields, ID='456')
            assert '+375291234567' in fields['COMMENTS']
            return httpx.Response(200, json={'result': 456})
        raise AssertionError('Unexpected request')
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        # Recreate after destination is set: booking snapshots must not change portal.
        repo = CloudBookingRepository(config.id, repo.binding, config.business,
                                      GoogleCalendar('NONE', client, token=lambda: 'fake'), BitrixCRM('TEST_BITRIX', client))
        row = repo.create(booking())
        assert row['calendar_status'] == 'confirmed' and row['crm_status'] == 'synced' and row['crm_id'] == '456'
        repo.sync(row['id'])
    assert sum(path.endswith('/events') for path in calls) == 1
    assert sum(path.endswith('crm.deal.add.json') for path in calls) == 1


def test_crm_retry_will_not_export_cancelled_event(env):
    _, repo, calendar, crm = env
    crm.fail = 'unknown_saved'
    row = repo.create(booking())
    calendar.events[(row['calendar_id'], row['id'])]['status'] = 'cancelled'
    crm.fail = None
    result = repo.sync(row['id'])
    assert result['crm_status'] == 'unknown' and result['error_code'] == 'conflict'
    assert crm.writes == 1


def test_resource_and_duration_integrity(env):
    config, repo, calendar, _ = env
    service = BookingService(config.business, repo)
    values = booking()['structured_data']['values']
    calendar.intervals = [{'start': values['datetime'][:10] + 'T19:00:00+03:00', 'end': values['datetime'][:10] + 'T19:01:00+03:00'}]
    # One minute of overlap excludes a whole 60-minute service, not just equal start times.
    assert not any(item['datetime'] == values['datetime'] for item in service.check_slots('маникюр', values['datetime'][:10], employee='Анна')['slots'])


def test_integrations_api_protects_status_and_reconcile(env, monkeypatch):
    from fastapi.testclient import TestClient
    from app import app
    with TestClient(app, raise_server_exceptions=False) as client:
        status = client.get('/api/integrations/status').json()
        assert status['agents'] == []
        assert client.get('/api/integrations/status', headers={'Origin': 'https://evil.example'}).status_code == 403
        assert client.post('/api/integrations/bookings/missing/reconcile').status_code == 404
        monkeypatch.setenv('CALLWISE_OWNER_PASSWORD', 'a-strong-owner-password')
        assert client.get('/api/integrations/bookings').status_code == 401


def test_parallel_overlapping_reservations_only_one_write(env):
    import concurrent.futures
    _, repo, calendar, _ = env
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(repo.create, booking('parallel-' + str(i))) for i in range(2)]
        results = []
        for future in futures:
            try: results.append(future.result())
            except IntegrationError as error: assert error.code == 'conflict'
    assert len(results) == 1 and calendar.writes == 1
