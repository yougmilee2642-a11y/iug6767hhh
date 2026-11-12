"""Deterministic formulas, source proof, scope, reviewed outbox and delayed checks."""
from datetime import datetime,timedelta,timezone
import json
import pytest
from meetings import access,store,effect_checks
from meetings.management import advanced,advanced_api
from tests.test_track3_briefing import env,business_counts,STAMP


@pytest.fixture
def fixed(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return STAMP if tz else STAMP.replace(tzinfo=None)
    monkeypatch.setattr(advanced_api,'datetime',Clock)


def get(env,who='director'):
    r=env[who].get('/api/meet/advanced-overview');assert r.status_code==200,r.text
    return r.json()


def test_seasonal_formula_six_weeks_and_explicit_pickup_deadline(env,fixed):
    before=business_counts();data=get(env)
    forecast=data['seasonal_forecast'];assert len(forecast)==1
    f=forecast[0];assert f['moving_average']==75 and f['december_coefficient']==1.48 and len(f['points'])==6
    assert max(p['value'] for p in f['points'])==111 and max(p['deficit_percent'] for p in f['points'])==11
    assert data['pickup_orders'] and all(STAMP<=store.parse_aware(o['expires_at'])<=STAMP+timedelta(days=2) for o in data['pickup_orders'])
    assert business_counts()==before
    for metric in data['metrics']:
        r=env['director'].get('/api/meet/sources/insight/'+metric['source']['id']);assert r.status_code==200,r.text
        assert r.json()['data']['metric']==metric


def test_scopes_and_zero_capacity_never_invent_forecast(env,fixed):
    assert get(env,'prod_head')['seasonal_forecast']
    assert not get(env,'sup_head')['seasonal_forecast']
    assert not get(env,'prod_head')['pickup_orders']
    # LOG projection grants only order number/deadline; no customer/amount data.
    from fastapi.testclient import TestClient
    client=TestClient(env['app']);client.post('/api/meet/login',json={'login':'log_head','password':'log_head-demo'}).raise_for_status()
    data=client.get('/api/meet/advanced-overview').json();assert data['pickup_orders'] and not data['seasonal_forecast']
    assert 'client_ref' not in json.dumps(data['pickup_orders']) and 'amount_minor' not in json.dumps(data['pickup_orders'])
    client.close()
    with store.db() as c:c.execute('UPDATE seasonality_samples SET available_hours=0')
    data=get(env,'prod_head');assert not data['seasonal_forecast'] and data['warnings']
    assert env['admin'].get('/api/meet/advanced-overview').status_code==403


def test_signed_insight_does_not_survive_changed_data_or_foreign_scope(env,fixed):
    data=get(env,'prod_head');key=data['seasonal_forecast'][0]['source']['id']
    assert env['sup_head'].get('/api/meet/sources/insight/'+key).status_code==404
    with store.db() as c:c.execute('UPDATE seasonality_samples SET occupied_hours=occupied_hours+1')
    assert env['prod_head'].get('/api/meet/sources/insight/'+key).status_code==404


def test_pickup_action_is_only_a_draft_then_source_changes_fail_confirm(env,fixed):
    client=env['director'];data=get(env);proposal=data['pickup_orders'][0]['proposed_action']
    mid=client.post('/api/meet/meetings',json={'title':'Проверить сроки ПВЗ'}).json()['meeting']['id']
    action={**proposal,'meeting_id':mid,'assignee_user_id':env['ids']['users']['log_head']}
    p=client.post('/api/meet/assistant/actions/preview',json=action);assert p.status_code==200,p.text
    with store.db() as c:
        assert not c.execute('SELECT 1 FROM tasks WHERE meeting_id=?',(mid,)).fetchone()
        c.execute('UPDATE pickup_storage SET expires_at=? WHERE order_no=?',(store.iso_utc(STAMP+timedelta(days=5)),data['pickup_orders'][0]['order_no']))
    r=client.post('/api/meet/assistant/actions/confirm',json={'confirmation_id':p.json()['confirmation_id'],'idempotency_key':'pickup-stale'})
    assert r.status_code==409,r.text


def test_weekly_digest_cancel_confirm_replay_owner_and_stale_download(env):
    client=env['prod_head'];before=business_counts();p=client.post('/api/meet/briefing/weekly/preview',json={'period_end':'2026-11-11'})
    assert p.status_code==200,p.text
    assert p.json()['preview']['claims']
    client.post('/api/meet/confirmations/'+p.json()['confirmation_id']+'/cancel')
    assert client.post('/api/meet/briefing/weekly/confirm',json={'confirmation_id':p.json()['confirmation_id'],'idempotency_key':'weekly-cancel'}).status_code==409
    p=client.post('/api/meet/briefing/weekly/preview',json={'period_end':'2026-11-11'})
    token={'confirmation_id':p.json()['confirmation_id'],'idempotency_key':'weekly-confirm'}
    r=client.post('/api/meet/briefing/weekly/confirm',json=token);assert r.status_code==200,r.text
    assert client.post('/api/meet/briefing/weekly/confirm',json=token).json()['already_confirmed']
    assert client.get(r.json()['path']).status_code==200
    assert env['director'].get(r.json()['path']).status_code==404
    with store.db() as c:
        assert c.execute('SELECT count(*) FROM weekly_digest_outbox').fetchone()[0]==1
        c.execute("UPDATE tasks SET status='done',updated_at=? WHERE id=(SELECT min(id) FROM tasks)",(store.now(),))
    assert client.get(r.json()['path']).status_code==409
    after=business_counts();assert after['calendar_events']==before['calendar_events'] and after['tasks']==before['tasks']


def decision(env):
    client=env['prod_head'];mid=client.post('/api/meet/meetings',json={'title':'Вторая смена Premium'}).json()['meeting']['id']
    with store.db() as c:
        u=c.execute('INSERT INTO utterances(meeting_id,idx,speaker_label,text,original_text) VALUES (?,1,?,?,?)',(mid,'Марина','Решили ввести вторую смену.','Решили ввести вторую смену.')).lastrowid
        c.execute('INSERT INTO protocols(meeting_id,generated_at,model) VALUES (?,?,?)',(mid,store.now(),'synthetic'))
        pid=c.execute("INSERT INTO protocol_items(meeting_id,position,kind,text,quotes,confirmed_by,confirmed_at) VALUES (?,1,'decision',?,?,?,?)",
            (mid,'Ввести вторую смену',json.dumps([{'utterance_id':'U'+str(u),'text':'Решили ввести вторую смену.'}]),env['ids']['users']['prod_head'],store.now())).lastrowid
        c.execute('UPDATE production_metrics SET occupied_capacity=111,available_capacity=100')
    return pid


def test_effect_control_requires_new_fresh_metric_and_never_changes_task_status(env):
    client=env['prod_head'];pid=decision(env)
    p=client.post('/api/meet/effect-checks/preview',json={'protocol_item_id':pid,'metric_key':'capacity_utilization','target_value':100,'direction':'le','days':7})
    assert p.status_code==200,p.text
    assert p.json()['preview']['baseline']['value']==111
    token={'confirmation_id':p.json()['confirmation_id'],'idempotency_key':'effect-confirm'}
    r=client.post('/api/meet/effect-checks/confirm',json=token);assert r.status_code==200,r.text
    assert client.post('/api/meet/effect-checks/confirm',json=token).json()['already_confirmed']
    now=store.parse_aware(r.json()['check_at'])+timedelta(minutes=1)
    with store.write_tx() as c:
        tasks=[tuple(row) for row in c.execute('SELECT id,status FROM tasks ORDER BY id')]
        assert effect_checks.tick(c,now)==0
        assert c.execute('SELECT status FROM task_effect_checks').fetchone()[0]=='waiting_data'
        c.execute('UPDATE production_metrics SET occupied_capacity=96,as_of=?',(store.iso_utc(now-timedelta(hours=1)),))
        assert effect_checks.tick(c,now)==1
        row=c.execute('SELECT * FROM task_effect_checks').fetchone();result=json.loads(row['result_json'])
        assert row['status']=='evaluated' and result['before']==111 and result['after']==96 and result['reached']
        assert effect_checks.tick(c,now)==0 and [tuple(row) for row in c.execute('SELECT id,status FROM tasks ORDER BY id')]==tasks
    visible=client.get('/api/meet/effect-checks');assert visible.status_code==200,visible.text
    assert visible.json()['checks'][0]['result']['after']==96
    with store.db() as c:c.execute("UPDATE production_metrics SET confidentiality='secret'")
    assert client.get('/api/meet/effect-checks').json()['checks']==[]
