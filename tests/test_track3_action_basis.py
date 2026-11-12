import json
from meetings import store
from tests.test_track3_briefing import env
from tests.test_track3_calls import create


def metric(env):
    r=env['prod_head'].get('/api/meet/overview');assert r.status_code==200,r.text
    return r.json()['metrics'][0]['source']


def draft(env,basis,kind='meeting'):
    return env['prod_head'].post('/api/meet/assistant/actions/preview',json={
        'kind':kind,'text':'Проверить показатель производства','basis':{'kind':basis['kind'],'id':basis['id']},
        **({'meeting_id':env['ids']['meetings']['delay']} if kind=='task' else {})})


def test_metric_drilldown_action_requires_preview_cancel_and_idempotent_confirm(env):
    source=metric(env);r=draft(env,source);assert r.status_code==200,r.text
    token=r.json()['confirmation_id'];assert env['prod_head'].post(f'/api/meet/confirmations/{token}/cancel').status_code==200
    assert env['prod_head'].post('/api/meet/assistant/actions/confirm',json={'confirmation_id':token,'idempotency_key':'cancel-metric-action'}).status_code==409
    r=draft(env,source);assert r.status_code==200,r.text
    data={'confirmation_id':r.json()['confirmation_id'],'idempotency_key':'metric-meeting-action'}
    result=env['prod_head'].post('/api/meet/assistant/actions/confirm',json=data)
    assert result.status_code==200,result.text
    assert env['prod_head'].post('/api/meet/assistant/actions/confirm',json=data).json()['already_confirmed']
    with store.db() as c:
        row=c.execute("SELECT * FROM action_basis WHERE object_type='meeting' AND object_id=?",(result.json()['meeting_id'],)).fetchone()
        assert row['source_kind']=='metric' and row['source_id']==source['id']
        assert not c.execute('SELECT 1 FROM calendar_events WHERE meeting_id=?',(result.json()['meeting_id'],)).fetchone()


def test_changed_metric_never_creates_action(env):
    source=metric(env);r=draft(env,source);assert r.status_code==200,r.text
    with store.db() as c:
        before=c.execute('SELECT count(*) FROM meetings').fetchone()[0]
        c.execute("UPDATE tasks SET status='done',version=version+1 WHERE status NOT IN ('done','cancelled')")
    r=env['prod_head'].post('/api/meet/assistant/actions/confirm',json={'confirmation_id':r.json()['confirmation_id'],'idempotency_key':'stale-metric-action'})
    assert r.status_code==409,r.text
    with store.db() as c:assert c.execute('SELECT count(*) FROM meetings').fetchone()[0]==before


def test_missing_source_and_foreign_scope_are_not_actionable(env):
    assert draft(env,{'kind':'metric','id':'missing'}).status_code in (404,422)
    source=metric(env)
    r=env['designer'].post('/api/meet/assistant/actions/preview',json={'kind':'meeting','text':'Проверить чужой показатель','basis':{'kind':'metric','id':source['id']}})
    assert r.status_code in (403,404)


def test_call_problems_and_next_agenda_are_scoped_and_cited(env):
    call=create(env);r=env['sup_head'].get('/api/meet/calls/problems');assert r.status_code==200,r.text
    assert 1<=len(r.json()['problems'])<=3
    s=r.json()['problems'][0]['sources'][0]
    assert env['sup_head'].get('/api/meet/sources/call/'+s['id']).status_code==200
    assert env['operator'].get('/api/meet/calls/problems').json()['problems']==[]
    mid=env['sup_head'].post('/api/meet/meetings',json={'title':'Недельная поддержка'}).json()['meeting']['id']
    r=env['sup_head'].post(f'/api/meet/meetings/{mid}/next-agenda',json={'create_meeting':False})
    assert r.status_code==200,r.text
    assert any(i['kind']=='call' and i['sources'] for i in r.json()['context']['items'])
    with store.db() as c:
        assert not c.execute('SELECT 1 FROM tasks WHERE meeting_id=?',(mid,)).fetchone()
        c.execute('DELETE FROM meeting_access WHERE meeting_id=? AND user_id=?',(call['meeting_id'],env['ids']['users']['sup_head']))
    assert not env['sup_head'].get('/api/meet/calls/problems').json()['problems']
