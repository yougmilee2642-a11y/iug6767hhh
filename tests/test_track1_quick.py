import json
import pytest
from fastapi.testclient import TestClient
import app as app_module
import storage
from agents.factory import create_runtime
from agents.runtime import new_interaction
from providers.base import ModelReply, ToolCall
from providers.errors import ProviderError
from services.track1_service import Track1Service, QuickInput, make_config
from services.agent_service import AgentService
from services.agent_repository import AgentRepository


class IntakeProvider:
    """Deterministic test double, not a live model quality check."""
    def complete(self, messages, tools):
        known = json.loads(next(m.text.split(': ', 1)[1] for m in reversed(messages)
                                if m.role == 'system' and m.text.startswith('Проверенные собранные поля: ')))
        for key, question in [('customer_name', 'Как к вам обращаться?'),
                              ('phone', 'Назовите номер телефона для обратного звонка.'),
                              ('request_details', 'Кратко расскажите, по какому вопросу вы звоните.')]:
            if key not in known:
                return ModelReply(question)
        return ModelReply(tool_calls=[ToolCall('intake-test', 'save_callback_request',
            {key: known[key]['value'] for key in ('customer_name', 'phone', 'request_details')})])


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'DB_PATH', tmp_path / 'test.sqlite')
    monkeypatch.setattr(storage, 'DATA_DIR', tmp_path)
    storage.initialize_db()
    monkeypatch.setattr(app_module, 'get_provider', IntakeProvider)
    def reject_delivery(*args):
        raise AssertionError('Quick agent must not send legacy email')
    monkeypatch.setattr(app_module, 'send_application_email', reject_delivery)
    return TestClient(app_module.app)


def create_agent(client, **changes):
    preview = client.post('/api/track1/preview', json={'business_name': 'Тестовая компания', **changes})
    assert preview.status_code == 200, preview.text
    candidate = preview.json()
    saved = client.post('/api/track1/agents', json={key: candidate[key] for key in ('candidate_id', 'review_token')})
    assert saved.status_code == 200, saved.text
    identifier = saved.json()['id']
    assert client.post('/api/agents/' + identifier + '/activate').status_code == 200
    return identifier


def call(client, identifier, text, request_id=None):
    response = client.post('/api/chat', json={'interaction_id': identifier, 'text': text, 'request_id': request_id})
    assert response.status_code == 200, response.text
    return response.json()


def request_count():
    with storage.connect() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='callback_requests'").fetchone():
            return 0
        return db.execute('SELECT COUNT(*) FROM callback_requests').fetchone()[0]


def test_quick_setup_without_services_or_llm(client, monkeypatch):
    monkeypatch.setattr(app_module, 'get_builder_provider', lambda: (_ for _ in ()).throw(AssertionError('No Builder LLM')))
    before = storage.get_config()
    aid = create_agent(client, facts='Разрабатываем сайты.')
    agent = AgentRepository().get(aid)
    assert agent['source'] == 'track1'
    assert agent['config']['language'] == 'ru'
    assert {f['id'] for f in agent['config']['fields']} == {'customer_name', 'phone', 'request_details'}
    assert 'create_booking' not in [t['name'] for t in agent['config']['tools']]
    assert agent['config']['business']['knowledge']['channel_status']['telegram'] == 'not_connected'
    assert storage.get_config() == before


def test_preview_is_not_an_active_agent(client):
    candidate = client.post('/api/track1/preview', json={'business_name': 'Тест'}).json()
    assert AgentRepository().get(candidate['config']['id']) is None
    assert client.post('/api/conversations', json={'agent_id': candidate['config']['id']}).status_code == 404


def test_invalid_and_stale_preview_rejected(client):
    assert client.post('/api/track1/preview', json={'business_name': ' '}).status_code == 422
    assert client.post('/api/track1/preview', json={'business_name': 'Тест', 'tools': ['refund']}).status_code == 422
    candidate = client.post('/api/track1/preview', json={'business_name': 'Тест'}).json()
    assert client.post('/api/track1/agents', json={'candidate_id': candidate['candidate_id'], 'review_token': 'wrong'}).status_code == 409
    assert client.post('/api/track1/agents', json={'candidate_id': 'missing', 'review_token': 'wrong'}).status_code == 409


def test_intake_confirmation_history_and_no_calendar(client):
    aid = create_agent(client)
    cid = client.post('/api/conversations', json={'agent_id': aid}).json()['interaction_id']
    reply = call(client, cid, 'Алексей')
    assert reply['interaction']['structured_data']['customer_name'] == 'Алексей'
    assert reply['text'] == 'Назовите номер телефона для обратного звонка.'
    call(client, cid, '+375290000000')
    proposal = call(client, cid, 'Хочу обсудить разработку сайта.')
    assert proposal['status'] == 'awaiting_confirmation'
    assert request_count() == 0
    final = call(client, cid, 'Да', 'confirm-once')
    assert final['complete'] and final['status'] == 'completed'
    assert 'Подтверждённое обращение' in final['interaction']['brief_summary']
    assert 'разработку сайта' in final['interaction']['brief_summary']
    assert 'доставка' in final['text'].lower()
    assert not final['interaction']['email_sent']
    duplicate = call(client, cid, 'Да', 'confirm-once')
    assert duplicate['interaction']['action_result']['callback_id'] == final['interaction']['action_result']['callback_id']
    assert request_count() == 1
    with storage.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM bookings').fetchone()[0] == 0
    history = client.get('/api/applications').json()['items']
    assert history[0]['brief_summary'] == final['interaction']['brief_summary']
    assert history[0]['transcript'][-1]['role'] == 'assistant'


def test_invalid_phone_requires_clarification(client):
    aid = create_agent(client)
    cid = client.post('/api/conversations', json={'agent_id': aid}).json()['interaction_id']
    call(client, cid, 'Алексей')
    answer = call(client, cid, 'abc')
    assert answer['text'] == 'Назовите номер телефона для обратного звонка.'
    assert 'phone' not in answer['interaction']['structured_data']
    assert request_count() == 0


def test_unconfirmed_call_can_be_stopped(client):
    aid = create_agent(client)
    cid = client.post('/api/conversations', json={'agent_id': aid}).json()['interaction_id']
    call(client, cid, 'Алексей')
    stopped = client.post('/api/application', json={'interaction_id': cid}).json()
    assert stopped['status'] == 'stopped'
    assert 'Незавершённое' in stopped['brief_summary']
    assert request_count() == 0


def test_explicit_human_request_needs_no_contact(client):
    aid = create_agent(client)
    cid = client.post('/api/conversations', json={'agent_id': aid}).json()['interaction_id']
    answer = call(client, cid, 'Соедините с оператором')
    assert answer['status'] == 'escalated'
    assert 'Реального соединения' in answer['text']
    assert request_count() == 0


def test_edited_config_only_applies_to_new_conversations(client):
    aid = create_agent(client, facts='Первый факт')
    old_cid = client.post('/api/conversations', json={'agent_id': aid}).json()['interaction_id']
    create_agent(client, agent_id=aid, facts='Новый факт')
    new_cid = client.post('/api/conversations', json={'agent_id': aid}).json()['interaction_id']
    assert storage.get_interaction(old_cid)['agent_config']['business']['knowledge']['notes'] == 'Первый факт'
    assert storage.get_interaction(new_cid)['agent_config']['business']['knowledge']['notes'] == 'Новый факт'
    assert client.get('/api/track1/agents/' + aid + '/settings').json()['facts'] == 'Новый факт'


def test_stale_edit_and_foreign_source_rejected(client):
    aid = create_agent(client)
    candidate = client.post('/api/track1/preview', json={'business_name': 'Старые изменения', 'agent_id': aid}).json()
    create_agent(client, agent_id=aid, business_name='Другие изменения')
    assert client.post('/api/track1/agents', json={key: candidate[key] for key in ('candidate_id', 'review_token')}).status_code == 409
    demo = AgentService().demo()
    assert client.post('/api/track1/preview', json={'business_name': 'Тест', 'agent_id': demo.id}).status_code == 422
    assert client.get('/api/track1/agents/' + demo.id + '/settings').status_code == 404


@pytest.mark.parametrize('category,status', [('authentication',503),('rate_limit',429),('network',502),('timeout',502)])
def test_provider_errors_preserve_user_turn(client, monkeypatch, category, status):
    class Failed:
        def complete(self, *args):
            raise ProviderError('openai/gpt-oss-20b', 'agent', category)
    monkeypatch.setattr(app_module, 'get_provider', Failed)
    aid = create_agent(client)
    cid = client.post('/api/conversations', json={'agent_id': aid}).json()['interaction_id']
    response = client.post('/api/chat', json={'interaction_id': cid, 'text': 'Алексей'})
    assert response.status_code == status
    assert storage.get_interaction(cid)['transcript'][-1]['content'] == 'Алексей'


def test_hallucinated_contact_does_not_create_request(client):
    aid = create_agent(client)
    config = AgentService().resolve(aid)
    state = new_interaction(config)
    class Hallucinated:
        def complete(self, *args):
            return ModelReply(tool_calls=[ToolCall('bad', 'save_callback_request', {
                'customer_name':'Выдуманный', 'phone':'+375290000000', 'request_details':'Выдуманный запрос'})])
    response = create_runtime(config, Hallucinated()).turn(state, 'Алексей')
    assert response['complete'] is False
    assert state['status'] != 'completed'
    assert request_count() == 0


def test_greeting_binding_does_not_accept_tampered_question(client):
    config = make_config(QuickInput(business_name='Тест'), 'test')
    state = new_interaction(config)
    state['transcript'][0]['content'] = 'Подменённое приветствие. Как к вам обращаться?'
    create_runtime(config, IntakeProvider()).turn(state, 'Алексей')
    assert 'customer_name' not in state['collected_fields']


def test_unknown_hours_are_not_all_week_closed():
    from agents.validation import validate_agent
    config = make_config(QuickInput(business_name='Тест'), 'test')
    assert config.business.schedule == {}
    assert config.business.knowledge['hours_status'] == 'not_provided'
    config.business.capabilities.append('booking')
    assert any(e['code'] == 'invalid_hours' for e in validate_agent(config)['errors'])


def test_custom_greeting_does_not_repeat_name_question():
    config = make_config(QuickInput(business_name='Тест', greeting='Здравствуйте! Как к вам обращаться?'), 'test')
    assert config.greeting.count('Как к вам обращаться?') == 1


def test_quick_runtime_exposes_current_step_without_bypassing_confirmation(client):
    config = make_config(QuickInput(business_name='Тест'), 'step_test')
    state = new_interaction(config)
    seen = []
    class Recording(IntakeProvider):
        def complete(self, messages, tools):
            seen.append(messages[-1].text)
            return super().complete(messages, tools)
    runtime = create_runtime(config, Recording())
    runtime.turn(state, 'Алексей')
    assert seen[-1].endswith('это обратный звонок, не запись.')
    assert 'Назовите номер телефона для обратного звонка.' in seen[-1]
    runtime.turn(state, '+375290000000')
    assert 'Кратко расскажите, по какому вопросу вы звоните.' in seen[-1]
    reply = runtime.turn(state, 'Нужен сайт.')
    assert 'Сейчас вызови инструмент save_callback_request' in seen[-1]
    assert reply['status'] == 'awaiting_confirmation' and request_count() == 0
    assert runtime.turn(state, 'Да')['status'] == 'completed'
    assert request_count() == 1
