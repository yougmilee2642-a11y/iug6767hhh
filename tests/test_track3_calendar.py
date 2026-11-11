"""Test calendar: busy intervals, common free time, preview → confirm with local invitations only."""
import smtplib
import threading
import time as clock
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from meetings import store
from meetings.calendar import service
from test_meetings import env, login  # noqa: F401  (env is a fixture)

MINSK = ZoneInfo('Europe/Minsk')


def next_weekday(days_ahead=7) -> date:
    day = datetime.now(MINSK).date() + timedelta(days=days_ahead)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=MINSK)


def iso(value: datetime) -> str:
    return value.isoformat()


@pytest.fixture()
def cal(env, monkeypatch):
    def no_mail(*_args, **_kwargs):
        raise AssertionError('real e-mail must never be sent')
    monkeypatch.setattr(smtplib, 'SMTP', no_mail)
    monkeypatch.setattr(smtplib, 'SMTP_SSL', no_mail)
    day = next_weekday()
    with store.db() as connection:
        service.add_busy(connection, 1, at(day, 10), at(day, 11), 'Секретная встреча Ирины')
        service.add_busy(connection, 2, at(day, 11), at(day, 12), 'Личное Петра')
    return {**env, 'day': day, 'irina': login(env['app'], 'irina'), 'petr': login(env['app'], 'petr')}


def slots(client, day, duration=60, start=9, end=13, **extra):
    return client.post('/api/meet/calendar/slots', json={
        'participant_ids': [2], 'range_start': iso(at(day, start)), 'range_end': iso(at(day, end)),
        'duration_minutes': duration, 'timezone': 'Europe/Minsk', **extra})


def preview(client, meeting_id, start, duration=60, participants=(2,)):
    return client.post('/api/meet/calendar/preview', json={
        'meeting_id': meeting_id, 'participant_ids': list(participants), 'start_at': iso(start),
        'duration_minutes': duration})


def confirm(client, token, key='key-00000001'):
    return client.post('/api/meet/calendar/confirm', json={'confirmation_id': token, 'idempotency_key': key})


def events_count():
    with store.db() as connection:
        return (connection.execute('SELECT COUNT(*) FROM calendar_events').fetchone()[0],
                connection.execute('SELECT COUNT(*) FROM calendar_outbox').fetchone()[0])


def test_free_slots_skip_busy_and_allow_adjacent_intervals(cal):
    response = slots(cal['irina'], cal['day'])
    assert response.status_code == 200
    body = response.json()
    starts = [s['start_local'][11:16] for s in body['slots']]
    # Irina busy 10–11, Petr busy 11–12: 09:00–10:00 touches 10:00 and 12:00–13:00 touches 12:00 — both allowed
    assert starts == ['09:00', '12:00']
    assert body['timezone'] == 'Europe/Minsk' and body['slots'][0]['start_local'].endswith('+03:00')
    assert body['slots'][0]['start_at'] == iso(at(cal['day'], 9).astimezone(timezone.utc))
    assert 'Секретная' not in response.text and 'Личное' not in response.text  # never the titles of busy time
    half = [s['start_local'][11:16] for s in slots(cal['irina'], cal['day'], duration=30).json()['slots']]
    assert half[:2] == ['09:00', '09:15'] and '09:30' in half and '10:00' not in half and '11:30' not in half
    assert '12:00' in half


def test_slots_validate_time_zone_and_participants(cal):
    client, day = cal['irina'], cal['day']
    naive = client.post('/api/meet/calendar/slots', json={'participant_ids': [2], 'range_start': f'{day}T09:00',
                                                          'range_end': f'{day}T13:00', 'duration_minutes': 60})
    assert naive.status_code == 422 and naive.json()['code'] == 'naive_datetime'
    utc = client.post('/api/meet/calendar/slots', json={
        'participant_ids': [2], 'range_start': iso(at(day, 9).astimezone(timezone.utc)),
        'range_end': iso(at(day, 13).astimezone(timezone.utc)), 'duration_minutes': 60}).json()
    assert [s['start_local'][11:16] for s in utc['slots']] == ['09:00', '12:00']  # same instants given in UTC
    assert slots(client, day, timezone='Mars/Base').json()['code'] == 'invalid_timezone'
    unknown = client.post('/api/meet/calendar/slots', json={'participant_ids': [99], 'range_start': iso(at(day, 9)),
                                                            'range_end': iso(at(day, 13)), 'duration_minutes': 60})
    assert unknown.status_code == 422 and unknown.json()['code'] == 'unknown_participant'
    assert client.post('/api/meet/calendar/slots', json={'participant_ids': ['ivan@example.com'], 'range_start': iso(at(day, 9)),
                                                         'range_end': iso(at(day, 13)), 'duration_minutes': 60}).status_code == 422
    assert slots(client, day, start=13, end=9).json()['code'] == 'invalid_range'
    # a reader may look at availability (but not schedule)
    assert slots(cal['petr'], day).status_code == 200


def test_preview_confirm_creates_event_and_local_invitations(cal):
    irina, petr, day = cal['irina'], cal['petr'], cal['day']
    design = cal['design_meeting']
    response = preview(irina, design, at(day, 12))
    assert response.status_code == 200, response.text
    body = response.json()
    shown = body['preview']
    assert shown['provider'] == 'mock' and shown['start_local'] == f'{day}T12:00+03:00'
    assert [p['id'] for p in shown['participants']] == [1, 2] and shown['timezone'] == 'Europe/Minsk'
    assert [i['recipient_id'] for i in shown['invitations']] == [2] and shown['invitations'][0]['channel'] == 'local_outbox'
    assert body['confirmation_id'] and body['expires_at']
    assert events_count() == (0, 0)  # preview writes nothing to the calendar
    done = confirm(irina, body['confirmation_id'])
    assert done.status_code == 200, done.text
    result = done.json()
    assert result['already_confirmed'] is False and result['event']['start_at'] == iso(at(day, 12).astimezone(timezone.utc))
    assert result['invitations'][0]['status'] == 'queued_local' and result['invitations'][0]['recipient_id'] == 2
    assert irina.get(f'/api/meet/meetings/{design}').json()['meeting']['scheduled_at'] == result['event']['start_at']
    # the slot is now taken for both participants
    assert '12:00' not in [s['start_local'][11:16] for s in slots(irina, day).json()['slots']]
    assert [e['id'] for e in petr.get('/api/meet/calendar/events').json()['events']] == [result['event']['id']]
    assert petr.get('/api/meet/calendar/outbox').json()['invitations'][0]['subject'].startswith('Приглашение: ')
    trail = irina.get('/api/meet/audit').json()['events']
    assert {'calendar_preview', 'calendar_confirm'} <= {e['action'] for e in trail}
    assert all(e['confirmation_id'] == body['confirmation_id'] for e in trail if e['action'].startswith('calendar_'))


def test_cancel_publishes_nothing_and_kills_the_token(cal):
    irina, design = cal['irina'], cal['design_meeting']
    before = irina.get(f'/api/meet/meetings/{design}').json()['meeting']
    token = preview(irina, design, at(cal['day'], 9)).json()['confirmation_id']
    assert irina.post('/api/meet/calendar/cancel', json={'confirmation_id': token}).json()['status'] == 'cancelled'
    assert events_count() == (0, 0)
    after = irina.get(f'/api/meet/meetings/{design}').json()['meeting']
    assert after['scheduled_at'] == before['scheduled_at'] and after['version'] == before['version']
    late = confirm(irina, token)
    assert late.status_code == 409 and late.json()['code'] == 'confirmation_cancelled'
    assert events_count() == (0, 0)
    assert cal['petr'].post('/api/meet/calendar/cancel', json={'confirmation_id': token}).status_code == 404


def test_double_confirm_returns_the_same_event(cal):
    irina = cal['irina']
    token = preview(irina, cal['design_meeting'], at(cal['day'], 9)).json()['confirmation_id']
    first, second = confirm(irina, token).json(), confirm(irina, token).json()
    assert first['already_confirmed'] is False and second['already_confirmed'] is True
    assert first['event']['id'] == second['event']['id'] and events_count() == (1, 1)


def _parallel(calls):
    barrier = threading.Barrier(len(calls))
    results = [None] * len(calls)

    def run(index, call):
        barrier.wait()
        results[index] = call()
    threads = [threading.Thread(target=run, args=(i, c)) for i, c in enumerate(calls)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    return results


@pytest.fixture()
def slow_check(monkeypatch):
    """Widen the race window: the free-slot check inside confirm waits before answering."""
    original = service.is_free

    def slow(*args, **kwargs):
        clock.sleep(0.2)
        return original(*args, **kwargs)
    monkeypatch.setattr(service, 'is_free', slow)


def test_race_of_two_confirms_of_one_token_creates_one_event(cal, slow_check):
    token = preview(cal['irina'], cal['design_meeting'], at(cal['day'], 9)).json()['confirmation_id']
    clients = [login(cal['app'], 'irina'), login(cal['app'], 'irina')]
    results = _parallel([lambda c=c, k=k: confirm(c, token, k) for c, k in zip(clients, ('race-key-0001', 'race-key-0001'))])
    assert [r.status_code for r in results] == [200, 200]
    assert sorted(r.json()['already_confirmed'] for r in results) == [False, True]
    assert len({r.json()['event']['id'] for r in results}) == 1 and events_count() == (1, 1)


def test_race_of_two_tokens_for_the_same_slot_books_it_once(cal, slow_check):
    irina = cal['irina']
    other = irina.post('/api/meet/meetings', json={'title': 'Вторая встреча'}).json()['meeting']
    a = preview(irina, cal['design_meeting'], at(cal['day'], 9)).json()['confirmation_id']
    b = preview(irina, other['id'], at(cal['day'], 9, 30), duration=30).json()['confirmation_id']
    clients = [login(cal['app'], 'irina'), login(cal['app'], 'irina')]
    results = _parallel([lambda: confirm(clients[0], a, 'race-a-00001'), lambda: confirm(clients[1], b, 'race-b-00001')])
    codes = sorted(r.status_code for r in results)
    assert codes == [200, 409] and events_count()[0] == 1
    assert next(r for r in results if r.status_code == 409).json()['code'] == 'slot_taken'


def test_slot_taken_between_preview_and_confirm(cal):
    irina, day = cal['irina'], cal['day']
    token = preview(irina, cal['design_meeting'], at(day, 12)).json()['confirmation_id']
    with store.db() as connection:  # Petr's calendar fills 12:30–13:00 meanwhile
        service.add_busy(connection, 2, at(day, 12, 30), at(day, 13))
    response = confirm(irina, token)
    assert response.status_code == 409 and response.json()['code'] == 'slot_taken'
    assert events_count() == (0, 0)
    busy_now = preview(irina, cal['design_meeting'], at(day, 12))
    assert busy_now.status_code == 409 and busy_now.json()['code'] == 'slot_taken'


def test_stale_meeting_and_foreign_or_swapped_token(cal):
    irina, petr, design = cal['irina'], cal['petr'], cal['design_meeting']
    token = preview(irina, design, at(cal['day'], 9)).json()['confirmation_id']
    # someone else cannot confirm it, even with access to the meeting
    foreign = confirm(petr, token)
    assert foreign.status_code == 404 and foreign.json()['code'] == 'confirmation_not_found'
    # recipients/time cannot be replaced at confirm
    swapped = cal['irina'].post('/api/meet/calendar/confirm', json={
        'confirmation_id': token, 'idempotency_key': 'swap-key-001', 'participant_ids': [1]})
    assert swapped.status_code == 422
    irina.patch(f'/api/meet/meetings/{design}', json={'topic': 'Изменили после предпросмотра'})
    stale = confirm(irina, token)
    assert stale.status_code == 409 and stale.json()['code'] == 'stale'
    assert events_count() == (0, 0)


def test_roles_acl_and_revocation_on_calendar(cal):
    irina, petr, day = cal['irina'], cal['petr'], cal['day']
    reader = preview(petr, cal['design_meeting'], at(day, 9), participants=(1,))
    assert reader.status_code == 403 and reader.json()['code'] == 'forbidden_role'
    hidden = preview(petr, cal['launch_meeting'], at(day, 9), participants=(1,))
    assert hidden.status_code == 404 and 'Орбит' not in hidden.text
    # ACL revoked between preview and confirm (e.g. by an administrator): confirm re-checks and refuses
    token = preview(irina, cal['design_meeting'], at(day, 9)).json()['confirmation_id']
    with store.db() as connection:
        connection.execute('DELETE FROM meeting_access WHERE meeting_id=? AND user_id=1', (cal['design_meeting'],))
    assert confirm(irina, token).status_code == 404
    assert events_count() == (0, 0)


def test_invitee_without_meeting_access_gets_no_title(cal):
    irina, petr, launch = cal['irina'], cal['petr'], cal['launch_meeting']
    shown = preview(irina, launch, at(cal['day'], 9)).json()
    assert shown['preview']['invitations'][0]['subject'] == 'Приглашение на встречу'
    assert any('без названия' in w for w in shown['preview']['warnings'])
    confirm(irina, shown['confirmation_id'])
    event = petr.get('/api/meet/calendar/events').json()['events'][0]
    assert event['title'] == 'Встреча (нет доступа к материалам)' and event['meeting_id'] is None
    inbox = petr.get('/api/meet/calendar/outbox').json()
    assert 'Орбит' not in str(inbox) and inbox['delivery'] == 'local_outbox_only'
    assert petr.get(f'/api/meet/meetings/{launch}').status_code == 404  # an invitation is not an ACL grant


def test_preview_rejects_past_and_naive_start(cal):
    irina = cal['irina']
    past = preview(irina, cal['design_meeting'], datetime.now(timezone.utc) - timedelta(hours=1))
    assert past.status_code == 422 and past.json()['code'] == 'slot_in_past'
    naive = irina.post('/api/meet/calendar/preview', json={'meeting_id': cal['design_meeting'], 'participant_ids': [2],
                                                           'start_at': f"{cal['day']}T09:00", 'duration_minutes': 60})
    assert naive.status_code == 422 and naive.json()['code'] == 'naive_datetime'


def test_service_interval_rules():
    a, b = datetime(2027, 1, 4, 10, tzinfo=timezone.utc), datetime(2027, 1, 4, 11, tzinfo=timezone.utc)
    c = datetime(2027, 1, 4, 12, tzinfo=timezone.utc)
    assert not service.overlaps(a, b, b, c)  # [10,11) and [11,12) are adjacent, not overlapping
    assert service.overlaps(a, c, b, c)
    with pytest.raises(store.TimeError):
        store.parse_aware('2027-01-04T10:00')
    assert store.parse_aware('2027-01-04T10:00', 'Europe/Minsk') == datetime(2027, 1, 4, 7, tzinfo=timezone.utc)
