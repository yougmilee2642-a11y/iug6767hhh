"""Local series, reminder preferences and Google transport doubles only."""
from datetime import datetime,timedelta,timezone
import json
import httpx
import pytest
from integrations.providers import GoogleCalendar as GoogleTransport
from integrations.contracts import IntegrationError
from meetings import store,notifications,access
from meetings.calendar import providers
from meetings.calendar.google import GoogleCalendar
from tests.test_track3_briefing import env,business_counts
from tests.test_track3_calendar_providers import request_data


def configure_google(env,monkeypatch,handler):
    monkeypatch.setenv('MEETINGS_CALENDAR_PROVIDER','google');monkeypatch.setenv('MEETINGS_GOOGLE_ENABLED','1')
    # Only network policy is doubled. Requests still go through the real transport,
    # with an injected MockTransport and synthetic bearer; no real credential file.
    monkeypatch.setattr('integrations.providers.network_allowed',lambda:None)
    transport=GoogleTransport('SYNTHETIC_CREDENTIALS',client=httpx.Client(transport=httpx.MockTransport(handler)),token=lambda:'synthetic-token')
    monkeypatch.setattr('meetings.calendar.google.Transport',lambda _:transport)
    with store.db() as c:
        for uid in env['ids']['users'].values():
            c.execute("INSERT INTO user_external_ids VALUES (?,'google',?)",(uid,f'calendar-{uid}@example.invalid'))
    return transport


def test_google_uses_freebusy_and_one_durable_private_event(env,monkeypatch):
    writes=[]
    def handler(r):
        if r.url.path.endswith('/freeBusy'):
            return httpx.Response(200,json={'calendars':{p['id']:{'busy':[]} for p in json.loads(r.content)['items']}})
        if r.method=='GET':return httpx.Response(404,json={})
        assert r.method=='POST' and r.url.params['sendUpdates']=='none'
        event=json.loads(r.content);writes.append(event)
        assert 'attendees' not in event and event['summary']=='Встреча Фокус' and event['visibility']=='private'
        with store.db() as c:assert c.execute("SELECT status FROM calendar_provider_outbox").fetchone()[0]=='sending'
        return httpx.Response(200,json=event)
    transport=configure_google(env,monkeypatch,handler)
    body=request_data(env);p=env['prod_head'].post('/api/meet/calendar/preview',json=body);assert p.status_code==200,p.text
    assert 'example.invalid' not in json.dumps(p.json())
    token={'confirmation_id':p.json()['confirmation_id'],'idempotency_key':'google-calendar'}
    r=env['prod_head'].post('/api/meet/calendar/confirm',json=token);assert r.status_code==200,r.text
    assert r.json()['delivery_status']=='sent'
    assert env['prod_head'].post('/api/meet/calendar/confirm',json=token).json()['already_confirmed'] and len(writes)==1
    transport.client.close()


def test_google_gates_and_timeout_never_retry(env,monkeypatch):
    monkeypatch.setenv('MEETINGS_GOOGLE_ENABLED','0')
    with store.db() as c:
        with pytest.raises(IntegrationError) as exc:GoogleCalendar(c)
        assert exc.value.code=='disabled'
    writes=[]
    def handler(r):
        if r.url.path.endswith('/freeBusy'):return httpx.Response(200,json={'calendars':{p['id']:{'busy':[]} for p in json.loads(r.content)['items']}})
        if r.method=='GET':return httpx.Response(404,json={})
        writes.append(1);raise httpx.ReadTimeout('synthetic',request=r)
    transport=configure_google(env,monkeypatch,handler);body=request_data(env)
    p=env['prod_head'].post('/api/meet/calendar/preview',json=body);assert p.status_code==200,p.text
    token={'confirmation_id':p.json()['confirmation_id'],'idempotency_key':'google-timeout'}
    for _ in range(2):
        r=env['prod_head'].post('/api/meet/calendar/confirm',json=token)
        assert r.status_code==503 and r.json()['status']=='uncertain',r.text
    assert writes==[1]
    transport.client.close()


def series_data(env):
    start=(datetime.now(timezone.utc)+timedelta(days=40)).replace(hour=10,minute=0,second=0,microsecond=0)
    return {'title':'Повторяющаяся планёрка','start_at':start.isoformat(),'frequency':'weekdays','count':3,'smart':False,
            'participant_ids':[env['ids']['users']['operator']]}


def test_series_preview_confirm_replay_and_separate_meetings(env):
    client=env['prod_head'];before=business_counts();p=client.post('/api/meet/calendar/series/preview',json=series_data(env))
    assert p.status_code==200,p.text
    with store.db() as c:assert c.execute('SELECT count(*) FROM meeting_series').fetchone()[0]==0
    assert business_counts()['calendar_events']==before['calendar_events']
    dates=p.json()['preview']['occurrences'];assert len(dates)==3
    assert all(store.parse_aware(item['start_at']).astimezone(store.zone('Europe/Minsk')).weekday()<5 for item in dates)
    token={'confirmation_id':p.json()['confirmation_id'],'idempotency_key':'local-series'}
    r=client.post('/api/meet/calendar/series/confirm',json=token);assert r.status_code==200,r.text
    mids=r.json()['meeting_ids'];assert len(mids)==3 and len(set(mids))==3
    assert client.post('/api/meet/calendar/series/confirm',json=token).json()['already_confirmed']
    listing=client.get('/api/meet/calendar/series').json()['series'];assert len(listing)==1 and len(listing[0]['meetings'])==3
    assert env['designer'].get('/api/meet/calendar/series').json()['series']==[]
    with store.db() as c:
        assert c.execute('SELECT count(*) FROM calendar_events WHERE meeting_id IN (?,?,?)',mids).fetchone()[0]==3
        assert c.execute('SELECT count(*) FROM protocols WHERE meeting_id IN (?,?,?)',mids).fetchone()[0]==0
        assert all(c.execute('SELECT series_id FROM meetings WHERE id=?',(mid,)).fetchone()[0]==r.json()['series_id'] for mid in mids)


def test_series_cancel_stale_busy_and_roles_leave_no_series(env):
    client=env['prod_head'];data=series_data(env)
    assert env['operator'].post('/api/meet/calendar/series/preview',json=data).status_code==403
    p=client.post('/api/meet/calendar/series/preview',json=data);assert p.status_code==200,p.text
    client.post('/api/meet/confirmations/'+p.json()['confirmation_id']+'/cancel')
    assert client.post('/api/meet/calendar/series/confirm',json={'confirmation_id':p.json()['confirmation_id'],'idempotency_key':'cancel-series'}).status_code==409
    p=client.post('/api/meet/calendar/series/preview',json=data)
    with store.db() as c:c.execute("UPDATE users SET name='Другое имя' WHERE login='operator'")
    assert client.post('/api/meet/calendar/series/confirm',json={'confirmation_id':p.json()['confirmation_id'],'idempotency_key':'stale-series'}).status_code==409
    p=client.post('/api/meet/calendar/series/preview',json=data);first=p.json()['preview']['occurrences'][0]
    with store.db() as c:
        from meetings.calendar.service import add_busy
        add_busy(c,env['ids']['users']['operator'],first['start_at'],first['end_at'])
    assert client.post('/api/meet/calendar/series/confirm',json={'confirmation_id':p.json()['confirmation_id'],'idempotency_key':'busy-series'}).status_code==409
    with store.db() as c:assert c.execute('SELECT count(*) FROM meeting_series').fetchone()[0]==0


def test_reminder_preference_confirm_and_tick_no_hidden_tasks(env):
    client=env['prod_head'];data=series_data(env)
    p=client.post('/api/meet/calendar/series/preview',json=data);assert p.status_code==200,p.text
    r=client.post('/api/meet/calendar/series/confirm',json={'confirmation_id':p.json()['confirmation_id'],'idempotency_key':'reminder-series'})
    assert r.status_code==200,r.text
    p=client.post('/api/meet/notification-settings/preview',json={'reminder_minutes':45})
    assert p.status_code==200,p.text
    assert client.post('/api/meet/notification-settings/confirm',json={'confirmation_id':p.json()['confirmation_id'],'idempotency_key':'reminder-settings'}).status_code==200
    with store.write_tx() as c:
        event=c.execute('SELECT * FROM calendar_events WHERE meeting_id=?',(r.json()['meeting_ids'][0],)).fetchone()
        now=store.parse_aware(event['start_at'])-timedelta(minutes=30);before=c.execute('SELECT count(*) FROM tasks').fetchone()[0]
        notifications.tick(c,now);notifications.tick(c,now)
        rows=c.execute("SELECT * FROM notifications WHERE kind='meeting_soon' AND object_id=? AND user_id=?",(str(event['meeting_id']),env['ids']['users']['prod_head'])).fetchall()
        assert len(rows)==1 and '45 минут' in rows[0]['message']
        assert c.execute('SELECT count(*) FROM tasks').fetchone()[0]==before
