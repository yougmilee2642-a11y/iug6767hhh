"""Transport doubles only: no real account, model or external data."""
from datetime import datetime, timedelta, timezone
import json
import httpx
import pytest
from meetings import store
from meetings.calendar import providers, service
from meetings.connectors.bitrix24 import Bitrix24Connector
from meetings.connectors.contracts import IntegrationError
from tests.test_track3_briefing import env

WEBHOOK = 'https://portal.invalid/rest/1/synthetic-key-only/'


def configure(env, monkeypatch, handler):
    monkeypatch.setenv('MEETINGS_CALENDAR_PROVIDER', 'bitrix24')
    monkeypatch.setenv('MEETINGS_BITRIX_ENABLED', '1')
    with store.db() as c:
        for user in env['ids']['users'].values():
            c.execute("INSERT OR REPLACE INTO user_external_ids VALUES (?,'bitrix24',?)", (user, str(user+1000)))
    original = providers.Bitrix24Calendar
    monkeypatch.setattr(providers, 'Bitrix24Calendar', lambda c, actor=None: original(c, actor,
        connector=Bitrix24Connector(c,actor['id'] if actor else None,enabled=True,webhook=WEBHOOK,transport=httpx.MockTransport(handler))))


def request_data(env):
    r = env['prod_head'].post('/api/meet/meetings', json={'title':'Новая планёрка'})
    assert r.status_code==200, r.text
    start = (datetime.now(timezone.utc)+timedelta(days=20)).replace(hour=10,minute=0,second=0,microsecond=0)
    return {'meeting_id':r.json()['meeting']['id'], 'start_at':start.isoformat(), 'duration_minutes':30,
            'participant_ids':[env['ids']['users']['operator']]}


def empty_busy(request):
    data=json.loads(request.content)
    return httpx.Response(200,json={'result':{str(i):[] for i in data['users']}})


def test_calendar_confirmation_is_durable_idempotent_and_private(env, monkeypatch):
    calls=[]
    def handler(request):
        method=request.url.path.rsplit('/',1)[1]; calls.append(method)
        if method=='calendar.accessibility.get.json':return empty_busy(request)
        assert method=='calendar.event.add.json'
        fields=json.loads(request.content)
        assert fields['name']=='Встреча CallWise' and not fields['meeting']['notify']
        assert 'Новая планёрка' not in request.content.decode()
        with store.db() as c:
            assert c.execute("SELECT status FROM calendar_provider_outbox").fetchone()[0]=='sending'
            assert not c.execute('SELECT 1 FROM calendar_outbox').fetchone()
        return httpx.Response(200,json={'result':77})
    configure(env,monkeypatch,handler); body=request_data(env)
    preview=env['prod_head'].post('/api/meet/calendar/preview',json=body)
    assert preview.status_code==200,preview.text
    assert calls==['calendar.accessibility.get.json']
    token={'confirmation_id':preview.json()['confirmation_id'],'idempotency_key':'external-cal-1'}
    result=env['prod_head'].post('/api/meet/calendar/confirm',json=token)
    assert result.status_code==200,result.text
    assert result.json()['delivery_status']=='sent' and len(result.json()['invitations'])==1
    count=len(calls)
    again=env['prod_head'].post('/api/meet/calendar/confirm',json=token)
    assert again.status_code==200 and again.json()['already_confirmed'] and len(calls)==count


def test_timeout_no_retry_and_unknown_slot_remains_blocked(env,monkeypatch):
    writes=[]
    def handler(request):
        if request.url.path.endswith('calendar.accessibility.get.json'):return empty_busy(request)
        writes.append(1);raise httpx.ReadTimeout('synthetic',request=request)
    configure(env,monkeypatch,handler);body=request_data(env)
    p=env['prod_head'].post('/api/meet/calendar/preview',json=body);assert p.status_code==200,p.text
    token={'confirmation_id':p.json()['confirmation_id'],'idempotency_key':'external-uncertain'}
    for _ in range(2):
        r=env['prod_head'].post('/api/meet/calendar/confirm',json=token)
        assert r.status_code==503 and r.json()['status']=='uncertain',r.text
    assert len(writes)==1
    with store.db() as c:
        assert not c.execute('SELECT 1 FROM calendar_outbox').fetchone()
        assert c.execute('SELECT scheduled_at FROM meetings WHERE id=?',(body['meeting_id'],)).fetchone()[0] is None
        a=store.parse_aware(body['start_at'])
        assert service.local_busy_intervals(c,[env['ids']['users']['operator']],a,a+timedelta(minutes=30))


def test_cancel_stale_mapping_and_no_rights_never_write(env,monkeypatch):
    calls=[]
    def handler(request):calls.append(request.url.path);return empty_busy(request)
    configure(env,monkeypatch,handler);body=request_data(env)
    assert env['operator'].post('/api/meet/calendar/preview',json=body).status_code in (403,404)
    p=env['prod_head'].post('/api/meet/calendar/preview',json=body);assert p.status_code==200,p.text
    token=p.json()['confirmation_id']
    assert env['prod_head'].post('/api/meet/calendar/cancel',json={'confirmation_id':token}).status_code==200
    r=env['prod_head'].post('/api/meet/calendar/confirm',json={'confirmation_id':token,'idempotency_key':'cancelled-cal'})
    assert r.status_code==409
    p=env['prod_head'].post('/api/meet/calendar/preview',json=body)
    with store.db() as c:
        c.execute("UPDATE user_external_ids SET external_id='998877' WHERE connector='bitrix24' AND user_id=?", (env['ids']['users']['operator'],))
    r=env['prod_head'].post('/api/meet/calendar/confirm',json={'confirmation_id':p.json()['confirmation_id'],'idempotency_key':'stale-cal'})
    assert r.status_code==409,r.text
    assert all('accessibility' in s for s in calls)


def test_busy_uses_named_timezone_not_misleading_utc_timestamp(env,monkeypatch):
    body=request_data(env);start=store.parse_aware(body['start_at'])
    def handler(request):
        data=json.loads(request.content)
        return httpx.Response(200,json={'result':{str(i):[{'NAME':'PRIVATE title', 'ACCESSIBILITY':'busy',
            'DATE_FROM':start.astimezone(store.zone('Europe/Minsk')).strftime('%d.%m.%Y %H:%M:%S'),
            'DATE_TO':(start+timedelta(minutes=30)).astimezone(store.zone('Europe/Minsk')).strftime('%d.%m.%Y %H:%M:%S'),
            'TZ_FROM':'Europe/Minsk','TZ_TO':'Europe/Minsk', 'DATE_FROM_TS_UTC':'0','DATE_TO_TS_UTC':'1'}] for i in data['users']}})
    configure(env,monkeypatch,handler)
    r=env['prod_head'].post('/api/meet/calendar/preview',json=body)
    assert r.status_code==409 and 'PRIVATE' not in r.text,r.text


@pytest.mark.parametrize('kind',['missing_mapping','down','malformed','missing_user'])
def test_missing_or_unavailable_calendar_fails_closed(env,monkeypatch,kind):
    def handler(request):
        if kind=='down':raise httpx.ConnectError('synthetic',request=request)
        if kind=='missing_user':return httpx.Response(200,json={'result':{}})
        data=json.loads(request.content)
        return httpx.Response(200,json={'result':{str(i):[{'ACCESSIBILITY':'busy','DATE_FROM':'bad'}] for i in data['users']}})
    configure(env,monkeypatch,handler);body=request_data(env)
    if kind=='missing_mapping':
        with store.db() as c:c.execute("DELETE FROM user_external_ids WHERE connector='bitrix24'")
    r=env['prod_head'].post('/api/meet/calendar/preview',json=body)
    assert r.status_code==503,r.text
    with store.db() as c:assert not c.execute('SELECT 1 FROM calendar_provider_outbox').fetchone()


def test_ambiguous_or_nonexistent_dst_is_not_guessed():
    for stamp in ['2026-10-25T02:30:00','2026-03-29T02:30:00']:
        with pytest.raises(IntegrationError):providers._bitrix_time(stamp,'Europe/Berlin')


def test_interrupted_send_never_reissues_network_write(env,monkeypatch):
    calls=[]
    def handler(request):
        if request.url.path.endswith('calendar.accessibility.get.json'):return empty_busy(request)
        calls.append(1);raise RuntimeError('simulated process interruption')
    configure(env,monkeypatch,handler);body=request_data(env)
    p=env['prod_head'].post('/api/meet/calendar/preview',json=body)
    token={'confirmation_id':p.json()['confirmation_id'],'idempotency_key':'crash-calendar'}
    with pytest.raises(RuntimeError):env['prod_head'].post('/api/meet/calendar/confirm',json=token)
    with store.db() as c:
        assert c.execute('SELECT status FROM calendar_provider_outbox').fetchone()[0]=='sending'
    r=env['prod_head'].post('/api/meet/calendar/confirm',json=token)
    assert r.status_code==503 and r.json()['status']=='uncertain' and calls==[1]
    data=env['prod_head'].get('/api/meet/calendar/export.ics').text
    assert 'STATUS:TENTATIVE' in data and 'STATUS:CONFIRMED' not in data
