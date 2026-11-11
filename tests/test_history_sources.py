import storage
from tests.test_track1_quick import client, create_agent
from agents.runtime import new_interaction
from services.agent_service import AgentService
from services.track1_service import QuickInput, make_config


def test_history_source_is_filtered_before_limit_and_labeled_by_server(client):
    aid=create_agent(client,role='support')
    own=new_interaction(AgentService().resolve(aid));own['created_at']='2000-01-01T00:00:00+00:00'
    storage.save_interaction(own)
    for _ in range(101):
        state=new_interaction(make_config(QuickInput(business_name='Архив',role='support'),'archived-agent'))
        storage.save_interaction(state)
    demo=new_interaction(make_config(QuickInput(business_name='Демо',role='support'),'shell_sample'))
    storage.save_interaction(demo)
    result=client.get('/api/applications?source=own&limit=100').json()['items']
    assert len(result)==1 and result[0]['id']==own['id'] and result[0]['origin']=='own'
    result=client.get('/api/applications?source=demo').json()['items']
    assert len(result)==1 and result[0]['origin']=='demo'
    assert all(row['origin']=='other' for row in client.get('/api/applications?source=other').json()['items'])
    assert client.get('/api/applications?source=unknown').status_code==422
