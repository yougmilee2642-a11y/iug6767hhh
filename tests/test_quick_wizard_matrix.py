"""Acceptance matrix for the short wizard: validation, roles, consent and safe unknowns."""
import pytest
from test_track1_quick import client, create_agent, call, request_count
from services.track1_service import QuickInput, make_config


@pytest.mark.parametrize('payload', [
    {'business_name': ' '},
    {'business_name': 'X'},
    {'business_name': 'Тест', 'role': 'sales'},
    {'business_name': 'Тест', 'tone': 'aggressive'},
    {'business_name': 'Тест', 'timezone': 'Mars/Olympus'},
    {'business_name': 'Тест', 'tools': ['create_booking']},
    {'business_name': 'Тест', 'qa': [{'question': 'Цена?', 'answer': '10'}, {'question': ' цена? ', 'answer': '20'}]},
    {'business_name': 'Тест', 'qa': [{'question': 'Цена?', 'answer': '   '}]},
])
def test_preview_rejects_invalid_or_unsupported_short_wizard_inputs(client, payload):
    assert client.post('/api/track1/preview', json=payload).status_code == 422


@pytest.mark.parametrize('role,expected_fields,expected_profile', [
    ('secretary', {'customer_name', 'phone', 'request_details'}, 'secretary'),
    ('support', set(), 'support'),
])
def test_role_contract_is_explicit_and_does_not_invent_schedule(client, role, expected_fields, expected_profile):
    aid = create_agent(client, role=role)
    settings = client.get(f'/api/track1/agents/{aid}/settings').json()
    assert settings['role'] == role
    from services.agent_service import AgentService
    config = AgentService().resolve(aid)
    assert {field.id for field in config.fields} == expected_fields
    assert config.business.schedule == {}
    assert config.business.knowledge['track1_profile'] == expected_profile
    assert config.business.knowledge['channel_status']['telephony'] == 'not_connected'


def test_secretary_requires_explicit_confirmation_before_persisting_request(client):
    aid = create_agent(client, role='secretary')
    cid = client.post('/api/conversations', json={'agent_id': aid}).json()['interaction_id']
    call(client, cid, 'Алексей')
    call(client, cid, '+375290000000')
    pending = call(client, cid, 'Нужен обратный звонок по сайту')
    assert pending['status'] == 'awaiting_confirmation'
    assert request_count() == 0
    declined = call(client, cid, 'Нет')
    assert request_count() == 0
    assert declined['status'] != 'completed'


def test_support_unknown_question_does_not_collect_contacts_or_persist_request(client):
    aid = create_agent(client, role='support', facts='Работаем с сайтами.')
    cid = client.post('/api/conversations', json={'agent_id': aid}).json()['interaction_id']
    answer = call(client, cid, 'Какая у вас цена ремонта самолёта?')
    assert answer['status'] == 'active'
    assert answer['interaction']['structured_data'] == {}
    assert request_count() == 0
    assert 'customer_name' not in answer['interaction']['structured_data']


def test_preview_never_persists_candidate_before_confirmation(client):
    import storage
    from services.agent_repository import AgentRepository
    before = storage.get_config()
    preview = client.post('/api/track1/preview', json={'business_name': 'Тестовый кандидат'}).json()
    assert AgentRepository().get(preview['config']['id']) is None
    assert storage.get_config() == before
