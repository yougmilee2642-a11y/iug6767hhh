from datetime import timedelta
from pathlib import Path
import json
import re
import pytest
from fastapi.testclient import TestClient
from meetings import store
from tests.test_track3_briefing import env

ROOT=Path(__file__).resolve().parents[1]


def control(env):
    segments=[]
    for line in (ROOT/'demo/track3/transcripts/call_defect_timed.txt').read_text().splitlines():
        m=re.fullmatch(r'\[(\d+):(\d+)-(\d+):(\d+)\] ([^:]+): (.+)',line)
        assert m,line
        a,b=(int(m[1])*60+int(m[2]))*1000,(int(m[3])*60+int(m[4]))*1000
        segments.append({'speaker':m[5],'text':m[6],'start_ms':a,'end_ms':b})
    return {'direction':'in','agent_user_id':env['ids']['users']['sup_agent'],'consent':True,
            'started_at':store.now(),'duration_ms':40000,'segments':segments}


def create(env,body=None):
    body=body or control(env);p=env['sup_head'].post('/api/meet/calls/preview',json=body)
    assert p.status_code==200,p.text
    r=env['sup_head'].post('/api/meet/calls/confirm',json={'confirmation_id':p.json()['confirmation_id'],'idempotency_key':'control-call-'+p.json()['confirmation_id']})
    assert r.status_code==200,r.text
    return r.json()


def test_control_call_topics_checklist_triggers_timings_are_cited(env):
    result=create(env);r=env['sup_head'].get('/api/meet/calls/'+str(result['call_id']))
    assert r.status_code==200,r.text
    a=r.json();assert len(a['checklist'])==6 and a['checklist_passed'] and a['speaker_mapping_complete']
    assert 'topic-00' in {t['code'] for t in a['topics']} and a['risk']['flag']
    assert {'брак','жалоба','верните деньги','отзыв'}<={t['text'] for t in a['triggers']}
    assert a['overlap_ms']==1000 and a['long_pauses'] and a['talk_percent'] is not None
    assert a['next_steps'] and a['model'] is None
    sources=[s for i in [*a['topics'],*a['checklist'],*a['triggers'],a['risk'],*a['next_steps']] for s in i['sources']]
    for source in sources:
        actual=env['sup_head'].get('/api/meet/utterances/'+source['id'])
        assert actual.status_code==200 and source['quote'] in actual.json()['utterance']['text']
    with store.db() as c:assert not c.execute('SELECT 1 FROM tasks WHERE meeting_id=?',(result['meeting_id'],)).fetchone()


def test_preview_cancel_replay_and_scope(env):
    body=control(env);p=env['sup_head'].post('/api/meet/calls/preview',json=body);assert p.status_code==200,p.text
    token=p.json()['confirmation_id'];assert env['sup_head'].post(f'/api/meet/confirmations/{token}/cancel').status_code==200
    assert env['sup_head'].post('/api/meet/calls/confirm',json={'confirmation_id':token,'idempotency_key':'call-cancel'}).status_code==409
    with store.db() as c:assert not c.execute('SELECT 1 FROM calls').fetchone()
    p=env['sup_head'].post('/api/meet/calls/preview',json=body)
    token={'confirmation_id':p.json()['confirmation_id'],'idempotency_key':'call-replay'}
    r=env['sup_head'].post('/api/meet/calls/confirm',json=token);assert r.status_code==200,r.text
    cid=r.json()['call_id'];mid=r.json()['meeting_id']
    assert env['sup_head'].post('/api/meet/calls/confirm',json=token).json()['already_confirmed']
    assert env['operator'].get('/api/meet/calls/'+str(cid)).status_code==404
    assert env['operator'].get('/api/meet/meetings/'+str(mid)).status_code==404
    assert env['admin'].get('/api/meet/calls/'+str(cid)).status_code==403
    # A second employee in the same department cannot read another agent's call.
    with store.db() as c:
        c.execute("UPDATE users SET department_id=(SELECT id FROM departments WHERE code='SUP') WHERE login='operator'")
    assert env['operator'].get('/api/meet/calls/'+str(cid)).status_code==404
    assert env['operator'].get('/api/meet/meetings/'+str(mid)).status_code==404
    agent=TestClient(env['app'])
    assert agent.post('/api/meet/login',json={'login':'sup_agent','password':'sup_agent-demo'}).status_code==200
    assert agent.get('/api/meet/calls/'+str(cid)).status_code==200
    assert agent.get('/api/meet/calls').json()['count']==1
    assert env['operator'].get('/api/meet/calls').json()['count']==0
    agent.close()


def test_no_consent_unknown_entities_and_stale_agent_do_not_import(env):
    body=control(env);body['consent']=False
    assert env['sup_head'].post('/api/meet/calls/preview',json=body).status_code==403
    body['consent']=True;body['order_no']='PP-2099-99999'
    assert env['sup_head'].post('/api/meet/calls/preview',json=body).status_code==404
    body.pop('order_no');p=env['sup_head'].post('/api/meet/calls/preview',json=body);assert p.status_code==200,p.text
    with store.db() as c:c.execute("UPDATE users SET manager_id=NULL WHERE id=?",(body['agent_user_id'],))
    r=env['sup_head'].post('/api/meet/calls/confirm',json={'confirmation_id':p.json()['confirmation_id'],'idempotency_key':'stale-call-agent'})
    assert r.status_code==409,r.text
    with store.db() as c:assert not c.execute('SELECT 1 FROM calls').fetchone()


def test_missing_timings_and_empty_transcript_are_honest(env):
    body=control(env);body['duration_ms']=None
    for segment in body['segments']:segment.pop('start_ms');segment.pop('end_ms')
    record=create(env,body);cid=record['call_id']
    a=env['sup_head'].get(f'/api/meet/calls/{cid}').json()
    assert a['talk_percent'] is None and a['overlap_ms'] is None and not a['long_pauses']
    with store.db() as c:c.execute('DELETE FROM utterances WHERE meeting_id=?',(record['meeting_id'],))
    a=env['sup_head'].get(f'/api/meet/calls/{cid}').json()
    assert not a['topics'] and not a['risk']['flag'] and not a['next_steps'] and not a['checklist_passed']


def test_current_access_is_rechecked_after_import(env):
    record=create(env)
    with store.db() as c:c.execute('DELETE FROM meeting_access WHERE meeting_id=? AND user_id=?',(record['meeting_id'],env['ids']['users']['sup_head']))
    assert env['sup_head'].get('/api/meet/calls/'+str(record['call_id'])).status_code==404
    assert env['sup_head'].get('/api/meet/calls').json()['count']==0


def test_original_frozen_call_is_preserved_and_analyzed_without_fake_timing(env):
    import hashlib
    original=ROOT/'demo/track3/transcripts/call_defect.txt'
    assert hashlib.sha256(original.read_bytes()).hexdigest()=='1124d4e1e55fe8e43828839f5f7315357be39e80a36e827ff7ef41198564d38e'
    body=control(env);body.pop('duration_ms');body['agent_speaker_label']='Светлана'
    body['segments']=[dict(zip(('speaker','text'),line.split(': ',1))) for line in original.read_text().splitlines()]
    record=create(env,body);data=env['sup_head'].get('/api/meet/calls/'+str(record['call_id'])).json()
    gold=json.loads((ROOT/'evaluation/track3/calls/expected.json').read_text())['legacy']
    assert {c['code'] for c in data['checklist'] if c['passed']}==set(gold['passed_checklist_codes'])
    assert set(gold['required_topics'])<={t['code'] for t in data['topics']}
    assert set(gold['required_triggers'])<={t['text'] for t in data['triggers']}
    assert data['talk_percent'] is None and data['overlap_ms'] is None and data['risk']['flag']==gold['risk']
