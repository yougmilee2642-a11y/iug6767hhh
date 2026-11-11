"""Owner workflow boundaries, isolated storage, no live AI or external channels."""
import pytest
import storage
from test_track1_quick import client, create_agent, call, request_count
from services.product_workspace import DraftInput
from services.track1_service import QuickInput


def test_draft_survives_reload_without_mutating_core_database(client):
    before=storage.get_config()
    first=client.get('/api/track1/draft').json()
    assert first == {'revision':0,'data':None,'updated_at':None}
    data=DraftInput(business_name='Черновик',qa=[{'question':'Вопрос без ответа'}]).model_dump()
    saved=client.put('/api/track1/draft',json={'expected_revision':0,'data':data})
    assert saved.status_code==200
    assert client.get('/api/track1/draft').json()['data']==data
    assert client.put('/api/track1/draft',json={'expected_revision':0,'data':data}).status_code==409
    assert storage.get_config()==before
    with storage.connect() as db:
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='owner_workspace_draft'").fetchone() is None


def test_review_bound_to_draft_revision_and_repeat_save_is_idempotent(client):
    data=DraftInput(business_name='Тест',city='').model_dump()
    draft=client.put('/api/track1/draft',json={'expected_revision':0,'data':data}).json()
    candidate=client.post('/api/track1/preview',json={**data,'draft_revision':draft['revision']}).json()
    client.put('/api/track1/draft',json={'expected_revision':1,'data':{**data,'facts':'Новый факт'}})
    confirmation={k:candidate[k] for k in ('candidate_id','review_token')}
    assert client.post('/api/track1/agents',json=confirmation).status_code==409
    assert client.post('/api/track1/preview',json={**data,'draft_revision':2}).status_code==409  # stale draft = revision conflict
    candidate=client.post('/api/track1/preview',json={**data,'facts':'Новый факт','draft_revision':2}).json()
    confirmation={k:candidate[k] for k in ('candidate_id','review_token')}
    first=client.post('/api/track1/agents',json=confirmation).json()
    second=client.post('/api/track1/agents',json=confirmation).json()
    assert first['id']==second['id']
    assert client.get('/api/track1/overview').json()['counts']['assistants']==1


def test_support_profile_has_no_contact_collection_or_write_tools(client,monkeypatch):
    from providers.base import ModelReply,ToolCall
    from agents.factory import create_runtime
    from agents.runtime import new_interaction
    from services.agent_service import AgentService
    import app
    class FAQProvider:
        def complete(self,messages,tools):
            assert [t.name for t in tools]==['transfer_to_human']
            assert 'Цена консультации — 50 BYN.' in messages[0].text
            return ModelReply('Цена консультации — 50 BYN.')
    monkeypatch.setattr(app,'get_provider',FAQProvider)
    aid=create_agent(client,role='support',qa=[{'question':'Сколько стоит консультация?','answer':'Цена консультации — 50 BYN.'}])
    config=AgentService().resolve(aid)
    assert config.fields==[] and config.business.schedule=={}
    cid=client.post('/api/conversations',json={'agent_id':aid}).json()['interaction_id']
    answer=call(client,cid,'Сколько стоит консультация?')
    assert answer['status']=='active' and answer['text']=='Цена консультации — 50 BYN.'
    assert storage.get_interaction(cid)['structured_data']=={}
    assert request_count()==0
    state=new_interaction(config)
    result,_=create_runtime(config,FAQProvider()).dispatch(ToolCall('bad','save_callback_request',{}),state)
    assert 'error' in result and state['pending_action'] is None
    stopped=client.post('/api/application',json={'interaction_id':cid}).json()
    assert stopped['result']=='Веб-тест завершён. Внешние действия не выполнялись.'
    assert not stopped['email_sent']


def test_support_handoff_does_not_promise_real_transfer(client):
    aid=create_agent(client,role='support')
    cid=client.post('/api/conversations',json={'agent_id':aid}).json()['interaction_id']
    reply=call(client,cid,'Хочу поговорить с человеком')
    assert reply['status']=='escalated' and 'Реального соединения' in reply['text']
    counts=client.get('/api/track1/overview').json()['counts']
    assert counts['human_requests']==1 and counts['confirmed']==0


def test_history_filters_before_limit_and_keeps_old_default(client):
    a=create_agent(client,business_name='Первый')
    b=create_agent(client,business_name='Второй')
    cid=client.post('/api/conversations',json={'agent_id':a}).json()['interaction_id']
    client.post('/api/application',json={'interaction_id':cid})
    for _ in range(3):client.post('/api/conversations',json={'agent_id':b})
    filtered=client.get('/api/applications',params={'limit':1,'agent_id':a,'status':'stopped'}).json()['items']
    assert len(filtered)==1 and filtered[0]['id']==cid
    assert client.get('/api/applications',params={'limit':1}).json()['items'][0]['agent_id']==b


@pytest.mark.parametrize('changes',[
    {'qa':[{'question':'Цена?','answer':'50'},{'question':' цена? ','answer':'60'}]},
    {'qa':[{'question':'Цена?','answer':' '}]},
    {'timezone':'Made/Up'}, {'role':'sales'}, {'tools':['create_booking']},
    {'facts':'a'*3000,'qa':[{'question':str(i),'answer':'b'*1000} for i in range(4)]},
])
def test_invalid_knowledge_and_unreviewed_capabilities_rejected(client,changes):
    assert client.post('/api/track1/preview',json={'business_name':'Тест',**changes}).status_code==422


def test_old_quick_input_defaults_roundtrip():
    data=QuickInput.model_validate({'business_name':'Старый помощник','facts':'Старый факт'})
    assert data.role=='secretary' and data.qa==[]


def test_over_limit_draft_is_kept_but_cannot_be_previewed(client):
    """P1-04: text above the knowledge limits must not be lost on reload, nor silently trimmed."""
    data=DraftInput(business_name='Тест',city='').model_dump()
    data['facts']='ф'*3500
    data['qa']=[{'question':'Цена?','answer':'а'*3100,'source':''}]
    saved=client.put('/api/track1/draft',json={'expected_revision':0,'data':data})
    assert saved.status_code==200
    loaded=client.get('/api/track1/draft').json()['data']
    assert len(loaded['facts'])==3500 and len(loaded['qa'][0]['answer'])==3100
    assert client.post('/api/track1/preview',json={**data,'draft_revision':saved.json()['revision']}).status_code==422
