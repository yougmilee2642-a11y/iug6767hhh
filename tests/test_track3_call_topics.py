import json
import pytest
from meetings import llm,store
from tests.test_track3_briefing import env
from tests.test_track3_calls import create


def double(monkeypatch,callback):
    monkeypatch.setenv('MEETINGS_CALL_TOPIC_MODEL','1')
    class Double:
        model='scripted-call-topics'
        def json(self,system,user,schema,predict=1500):
            assert '<<<' in user and 'demo@example.invalid' not in user
            return callback(json.loads(user))
    llm.set_llm(Double())


def test_opt_in_model_topics_only_offer_citable_suggestions(env,monkeypatch):
    record=create(env);cid=record['call_id'];mid=record['meeting_id']
    with store.db() as c:c.execute("UPDATE utterances SET text=text || ' Контакт demo@example.invalid.' WHERE meeting_id=?",(mid,))
    double(monkeypatch,lambda data:{'topics':[{'code':'topic-00','utterance_ids':[data['utterances'][1]['id']]}]})
    r=env['sup_head'].get(f'/api/meet/calls/{cid}/topics');assert r.status_code==200,r.text
    a=r.json();assert a['status']=='suggested' and a['model']=='scripted-call-topics'
    source=a['suggestions'][0]['sources'][0]
    u=env['sup_head'].get('/api/meet/utterances/'+source['id']).json()['utterance']
    assert source['quote']==u['text']
    with store.db() as c:assert not c.execute('SELECT 1 FROM tasks WHERE meeting_id=?',(mid,)).fetchone()


@pytest.mark.parametrize('mode',['code','source','extra','duplicate'])
def test_model_cannot_forge_topic_or_quote(env,monkeypatch,mode):
    record=create(env)
    def callback(data):
        i=data['utterances'][0]['id']
        return {'code':{'topics':[{'code':'topic-99','utterance_ids':[i]}]},
                'source':{'topics':[{'code':'topic-00','utterance_ids':['U999999']}]},
                'extra':{'topics':[{'code':'topic-00','utterance_ids':[i],'quote':'Выдумано'}]},
                'duplicate':{'topics':[{'code':'topic-00','utterance_ids':[i,i]}]}}[mode]
    double(monkeypatch,callback)
    r=env['sup_head'].get(f"/api/meet/calls/{record['call_id']}/topics")
    assert r.status_code==503 and r.json()['code']=='model_invalid_reply'
    assert 'suggestions' not in r.json()


def test_disabled_foreign_and_mutation_paths_fail_safely(env,monkeypatch):
    record=create(env);cid=record['call_id']
    monkeypatch.setenv('MEETINGS_CALL_TOPIC_MODEL','0')
    assert env['sup_head'].get(f'/api/meet/calls/{cid}/topics').status_code==503
    calls=[]
    def mutate(data):
        calls.append(1)
        with store.db() as c:c.execute("UPDATE utterances SET text=text || ' Изменение.' WHERE meeting_id=?",(record['meeting_id'],))
        return {'topics':[{'code':'topic-00','utterance_ids':[data['utterances'][0]['id']]}]}
    double(monkeypatch,mutate)
    assert env['operator'].get(f'/api/meet/calls/{cid}/topics').status_code==404 and not calls
    r=env['sup_head'].get(f'/api/meet/calls/{cid}/topics');assert r.status_code==409,r.text


def test_secret_call_never_reaches_model_even_for_its_owner(env,monkeypatch):
    record=create(env);calls=[]
    double(monkeypatch,lambda data:calls.append(1))
    with store.db() as c:
        c.execute("UPDATE meetings SET owner_id=?,confidentiality='secret' WHERE id=?",(env['ids']['users']['sup_head'],record['meeting_id']))
    r=env['sup_head'].get(f"/api/meet/calls/{record['call_id']}/topics")
    assert r.status_code==404 and not calls
