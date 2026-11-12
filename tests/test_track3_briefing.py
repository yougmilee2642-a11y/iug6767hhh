"""Deterministic briefings never call models or mutate tasks/calendar/outbox."""
from datetime import datetime, timezone
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from meetings import briefing, llm, store, voice
from meetings.api import install
from scripts.track3.seed_fotoprint import seed

STAMP = datetime(2026,11,11,12,tzinfo=timezone.utc)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('MEETINGS_SECRET','briefing-test')
    ids = seed(str(tmp_path / 'briefing.db')); app = FastAPI(); install(app)
    monkeypatch.setattr(briefing,'utc_now',lambda:STAMP)
    monkeypatch.setattr(voice,'utc_now',lambda:STAMP)
    class NoModel:
        model = 'must-not-be-called'
        def json(self,*args,**kwargs): raise AssertionError('Daily briefing must be deterministic')
    llm.set_llm(NoModel())
    clients = {}
    for name in ['director','prod_head','operator','sup_head','designer','admin','auditor']:
        client=TestClient(app)
        assert client.post('/api/meet/login',json={'login':name,'password':name+'-demo'}).status_code==200
        clients[name]=client
    yield {'ids':ids,'app':app,**clients}
    for client in clients.values():client.close()
    llm.set_llm(None);store.reset_cache()


def get(env,who='director',day='2026-11-11'):
    result=env[who].get('/api/meet/briefing',params={'date':day})
    assert result.status_code==200,result.text
    return result.json()


def business_counts():
    with store.db() as c:
        return {t:c.execute(f'SELECT count(*) FROM {t}').fetchone()[0]
                for t in ['tasks','confirmations','calendar_events','calendar_outbox','integration_outbox','documents']}


def test_briefing_is_sourced_read_only_and_current(env):
    before=business_counts(); data=get(env)
    assert data['date']=='2026-11-11' and data['timezone']=='Europe/Minsk' and data['model'] is None
    assert data['deviations'] and len(data['deviations'])<=3
    assert all(claim['sources'] for claim in data['claims'])
    assert all(s['source_at'] for s in data['sources'])
    assert data['counts']['team_risks']>=1
    assert business_counts()==before
    again=get(env);assert again==data
    with store.db() as c:
        row=c.execute("SELECT source_ids,result FROM audit WHERE action='briefing.read' ORDER BY id DESC LIMIT 1").fetchone()
        assert json.loads(row['source_ids']) and row['result']=='grounded'


@pytest.mark.parametrize('who',['admin','auditor'])
def test_technical_roles_cannot_get_briefing_and_denial_is_durable(env,who):
    response=env[who].get('/api/meet/briefing')
    assert response.status_code==403
    with store.db() as c:
        assert c.execute("SELECT 1 FROM audit WHERE action='briefing.read' AND result='denied'").fetchone()


@pytest.mark.parametrize('day',['bad','20261111','2026-02-30','1969-12-31','9999-12-31','2026-11-11T00:00:00Z'])
def test_invalid_date_honestly_rejected(env,day):
    assert env['director'].get('/api/meet/briefing',params={'date':day}).status_code==422


def test_minsk_midnight_and_personal_membership(env):
    result=env['prod_head'].post('/api/meet/meetings',json={'title':'После минской полуночи','scheduled_at':'2026-11-11T21:30:00Z'})
    assert result.status_code==200,result.text
    mid=result.json()['meeting']['id']
    assert mid not in [m['id'] for m in get(env,'prod_head')['meetings']]
    data=get(env,'prod_head','2026-11-12')
    assert mid in [m['id'] for m in data['meetings']]
    assert any('текущего реестра' in w for w in data['warnings'])
    # Merely having department read access does not make someone an attendee.
    assert mid not in [m['id'] for m in get(env,'operator','2026-11-12')['meetings']]


def test_tasks_are_bound_to_user_ids_team_and_current_meeting_access(env):
    operator=env['ids']['users']['operator']; head=env['ids']['users']['prod_head']
    data=get(env,'operator')
    assert data['my_tasks'] and all(t['assignee_user_id']==operator for t in data['my_tasks'])
    assert data['team_risks']==[]
    head_data=get(env,'prod_head');assert head_data['team_risks']
    visible={t['id'] for t in head_data['team_risks']}
    with store.db() as c:
        assert all(c.execute('SELECT manager_id FROM users WHERE id=?',(t['assignee_user_id'],)).fetchone()[0]==head
                   for t in head_data['team_risks'])
        # Preserve a task but revoke its meeting, including department visibility.
        target=head_data['team_risks'][0]
        c.execute("UPDATE meetings SET owner_id=?,confidentiality='confidential' WHERE id=?",(env['ids']['users']['sup_head'],target['meeting_id']))
        c.execute('DELETE FROM meeting_access WHERE meeting_id=? AND user_id=?',(target['meeting_id'],head))
    assert target['id'] not in [t['id'] for t in get(env,'prod_head')['team_risks']]
    assert visible


def test_missing_due_high_priority_closed_and_id_assignment(env):
    operator=env['ids']['users']['operator']
    with store.db() as c:
        tid=c.execute('SELECT id FROM tasks WHERE assignee_user_id=? LIMIT 1',(operator,)).fetchone()[0]
        c.execute("UPDATE tasks SET status='open',due=NULL,priority='normal' WHERE id=?",(tid,))
    assert tid in [t['id'] for t in get(env,'prod_head')['team_risks']]
    assert tid not in [t['id'] for t in get(env,'operator')['my_tasks']]
    with store.db() as c:c.execute("UPDATE tasks SET due='2027-01-01',priority='urgent' WHERE id=?",(tid,))
    assert tid in [t['id'] for t in get(env,'prod_head')['team_risks']]
    with store.db() as c:c.execute("UPDATE tasks SET status='done' WHERE id=?",(tid,))
    assert tid not in [t['id'] for t in get(env,'prod_head')['team_risks']]
    with store.db() as c:c.execute("UPDATE tasks SET status='open',due='2026-11-10',assignee_user_id=NULL WHERE id=?",(tid,))
    assert tid not in [t['id'] for t in get(env,'operator')['my_tasks']]


def test_documents_secret_and_readiness_do_not_reveal_hidden_sources(env):
    response=env['director'].post('/api/meet/documents',files={'file':('briefing-secret.txt',b'synthetic private')},data={'confidentiality':'secret'})
    did=response.json()['document']['id']
    with store.db() as c:c.execute('UPDATE documents SET created_at=? WHERE id=?',(STAMP.isoformat(),did))
    assert did not in [d['id'] for d in get(env)['new_documents']]
    result=env['prod_head'].post('/api/meet/meetings',json={'title':'Материалы не доступны','scheduled_at':'2026-11-11T09:00:00+03:00'})
    mid=result.json()['meeting']['id']
    with store.db() as c:c.execute('INSERT INTO meeting_documents VALUES (?,?)',(mid,did))
    own=next(m for m in get(env,'prod_head')['meetings'] if m['id']==mid)
    assert not own['has_materials'] and own['readiness']=='materials_missing'
    text=json.dumps(get(env,'designer'),ensure_ascii=False)
    assert 'briefing-secret' not in text and '650000' not in text and '48000' not in text


def test_sources_recheck_access_after_briefing(env):
    data=get(env,'prod_head')
    target=next(t for t in data['team_risks'])
    route='/api/meet/sources/task/'+target['source']['id']
    assert env['prod_head'].get(route).status_code==200
    with store.db() as c:
        c.execute("UPDATE meetings SET owner_id=?,confidentiality='confidential' WHERE id=?",(env['ids']['users']['sup_head'],target['meeting_id']))
        c.execute('DELETE FROM meeting_access WHERE meeting_id=? AND user_id=?',(target['meeting_id'],env['ids']['users']['prod_head']))
    assert env['prod_head'].get(route).status_code==404


def test_unavailable_crm_and_zero_denominator_are_warned(env,monkeypatch):
    monkeypatch.setenv('MOCK_CRM_FAULT','down')
    with store.db() as c:c.execute('UPDATE production_metrics SET available_capacity=0,occupied_capacity=0')
    data=get(env)
    assert any('недоступен' in w for w in data['warnings'])
    assert all(m['value'] is not None for m in data['deviations'])
    assert any('0' in w or 'нул' in w for w in data['warnings'])


def test_stale_sources_are_not_presented_as_fresh(env,monkeypatch):
    monkeypatch.setattr(briefing,'utc_now',lambda:datetime(2026,12,1,12,tzinfo=timezone.utc))
    data=get(env,day='2026-12-01')
    assert any('устар' in w for w in data['warnings']) and 'предупреждения' in data['spoken']


def test_voice_briefing_keeps_audience_privacy_and_no_writes(env):
    before=business_counts()
    response=env['operator'].post('/api/meet/voice/ask',json={'text':'Что важного сегодня?'})
    assert response.status_code==200,response.text
    data=response.json();assert data['route']=='briefing' and data['spoken'] is None and not data['speak']
    alone=env['operator'].post('/api/meet/voice/ask',json={'text':'Брифинг дня','speak_private':True}).json()
    assert alone['speak'] and alone['spoken'] and alone['answer']['model'] is None
    assert business_counts()==before
    assert voice.route('Отправь брифинг всем')=='action'
    assert voice.route('Что в документе о брифинге?')=='knowledge'


def test_calendar_attendee_requires_current_meeting_access(env):
    result=env['prod_head'].post('/api/meet/meetings',json={'title':'Встреча по приглашению','access_user_ids':[env['ids']['users']['operator']]})
    mid=result.json()['meeting']['id']; person=env['ids']['users']['operator']
    with store.db() as c:
        eid=c.execute("INSERT INTO calendar_events(meeting_id,organizer_id,title,start_at,end_at,timezone,confirmation_id,created_at) VALUES (?,?,?,'2026-11-11T10:00:00+03:00','2026-11-11T10:30:00+03:00','Europe/Minsk','synthetic-briefing-attendance',?)",
                      (mid,env['ids']['users']['prod_head'],'Встреча по приглашению',STAMP.isoformat())).lastrowid
        c.execute('INSERT INTO calendar_event_participants VALUES (?,?)',(eid,person))
    assert mid in [m['id'] for m in get(env,'operator')['meetings']]
    with store.db() as c:c.execute('DELETE FROM meeting_access WHERE meeting_id=? AND user_id=?',(mid,person))
    assert mid not in [m['id'] for m in get(env,'operator')['meetings']]


def test_long_document_list_is_explicitly_truncated(env):
    with store.db() as c:
        for i in range(55):
            did=c.execute("INSERT INTO documents(owner_id,title,filename,kind,content,sha256,created_at) VALUES (?,?,'brief.txt','txt',X'78','synthetic',?)",
                          (env['ids']['users']['director'],f'Новый тестовый документ {i}',STAMP.isoformat())).lastrowid
            c.execute("INSERT INTO fragments(document_id,idx,location,text) VALUES (?,1,'абз. 1','Проверка документов брифинга.')",(did,))
    result=get(env)
    assert result['counts']['new_documents']>=55 and len(result['new_documents'])==50
    assert 'new_documents' in result['truncated']
