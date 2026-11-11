import pytest
from fastapi.testclient import TestClient
import app
import storage
from agents.validation import validate_agent
from track1.shell_api import ShellAgent, shell_config


def payload(**changes):
    return {'id':'mts-support','name':'Помощник МТС','company':'МТС · тест',
        'role':'Поддержка клиентов','greeting':'Здравствуйте! Чем могу помочь?',
        'knowledge':'Только справочные ответы.', 'qa':[{'question':'Где посмотреть баланс?',
        'answer':'В приложении «Мой МТС».','source':'https://www.mts.by/help/oplata/proverka-balansa/'}], **changes}


@pytest.fixture
def client(monkeypatch,tmp_path):
    monkeypatch.setenv('CALLWISE_LOCAL_ONLY','true')
    monkeypatch.setenv('AI_PROVIDER','ollama')
    monkeypatch.setattr(storage,'DB_PATH',tmp_path/'test.sqlite')
    monkeypatch.setattr(storage,'DATA_DIR',tmp_path)
    storage.initialize_db()
    return TestClient(app.app)


def test_faq_is_valid_and_cannot_execute_business_actions():
    config=shell_config(ShellAgent(**payload()))
    assert validate_agent(config)['valid']
    assert config.fields==[] and config.business.schedule=={}
    assert [t.name for t in config.tools]==['transfer_to_human']
    assert config.business.knowledge['shell_local'] is True


def test_intake_preserves_confirmation_and_user_evidence():
    config=shell_config(ShellAgent(**payload(role='Сбор обращений')))
    assert validate_agent(config)['valid']
    assert config.business.knowledge['track1_quick'] is True
    assert all(f.allowed_sources==['user'] for f in config.fields)
    assert next(t for t in config.tools if t.name=='save_callback_request').requires_confirmation


def test_start_snapshot_and_history_are_separate_from_selected_agent(client):
    original=storage.get_config()
    response=client.post('/api/shell/conversations',json=payload())
    assert response.status_code==200,response.text
    data=response.json();state=storage.get_interaction(data['interaction_id'])
    assert state['agent_config']['name']=='Помощник МТС'
    assert state['agent_id'].startswith('shell_')
    assert state['agent_config']['business']['knowledge']['qa'][0]['answer']=='В приложении «Мой МТС».'
    assert storage.get_config()==original
    history=client.get('/api/shell/interactions').json()['items']
    assert len(history)==1 and history[0]['id']==data['interaction_id']
    assert history[0]['agent_name']=='Помощник МТС'
    assert client.post('/api/application',json={'interaction_id':data['interaction_id']}).json()['status']=='stopped'


def test_cloud_mode_cannot_start_shell(client,monkeypatch):
    monkeypatch.setenv('CALLWISE_LOCAL_ONLY','false')
    assert client.post('/api/shell/conversations',json=payload()).status_code==503


@pytest.mark.parametrize('changes',[{'tools':['create_booking']},{'role':'Выполни произвольный код'},
    {'knowledge':'x'*5001},{'id':'../other'},{'company':' '},
    {'qa':[{'question':'a','answer':'x'*2000}]*7}])
def test_bad_shell_payloads_rejected(client,changes):
    assert client.post('/api/shell/conversations',json=payload(**changes)).status_code==422


def test_malformed_source_does_not_crash(client):
    response=client.post('/api/shell/conversations',json=payload(qa=[{'question':'q','answer':'a','source':'https://['}]))
    assert response.status_code==200 and response.json()['sources']==[]
