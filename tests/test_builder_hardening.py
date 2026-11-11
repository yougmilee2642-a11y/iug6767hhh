"""Iteration 2.1 contracts; real mapper/validator/calendar, isolated SQLite."""
import copy
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import pytest
import storage
from tests.test_builder import isolated, nova, draft, MockBuilder
from builder.models import BusinessInput, BuilderDraft
from builder.mapping import map_draft, stable_id
from builder.service import AgentBuilder
from agents.validation import validate_agent
from agents.models import AgentConfig
from providers.builder import GroqBuilderProvider, strict_schema
from services.booking_service import BookingService
from services.business_hours import potential_clocks
from tools.registry import ToolRegistry, ToolDefinition
from tools.handoff import handoff_tool


def mapped(duration=30, opening='16:00', closing='17:00'):
    business = nova()
    business['schedule'] = {str(d): [{'start': opening, 'end': closing}] for d in range(7)}
    business['services'] = [{'name': 'Консультация', 'price': 10, 'currency': 'BYN',
                             'duration_minutes': duration, 'employees': ['Анна']}]
    return map_draft(BusinessInput.model_validate(business), BuilderDraft.model_validate(draft()), 'test_agent')[0]


def slots(config):
    tomorrow = (datetime.now(ZoneInfo('Europe/Minsk')) + timedelta(days=1)).date().isoformat()
    return BookingService(config.business).check_slots(config.business.knowledge['services'][0]['id'], tomorrow)['slots']


@pytest.mark.parametrize('role', ['Менеджер по продажам', 'Администратор'])
def test_dynamic_role_identity_and_greeting(isolated, role):
    business = nova(); business['desired_role'] = role
    proposal = draft(); proposal['role_name'] = role
    result = AgentBuilder(MockBuilder(proposal)).generate(BusinessInput.model_validate(business))
    assert result['validation']['valid'], result['validation']
    config = result['config']
    assert config['role']['name'] == role and result['preview']['role'] == role
    assert config['role']['id'] == stable_id(role, 'role') != 'administrator'
    assert role in config['role']['description'] and role in config['greeting']
    assert 'AI-администратор' not in config['greeting']
    if role != 'Администратор': assert 'администратор' not in config['role']['description'].casefold()


def test_role_id_normalized_server_owned(isolated):
    assert stable_id(' Менеджер  по продажам ', 'role') == stable_id('МЕНЕДЖЕР ПО ПРОДАЖАМ', 'role')
    assert stable_id('Менеджер по продажам', 'role') != stable_id('Администратор', 'role')
    assert stable_id('Менеджер по продажам', 'role').islower()
    invalid = draft(); invalid['role_id'] = 'administrator'
    assert not AgentBuilder(MockBuilder(invalid)).generate(BusinessInput.model_validate(nova()))['validation']['valid']


def test_short_window_slots(isolated):
    c = mapped()
    assert validate_agent(c)['valid']
    assert [s['datetime'][11:16] for s in slots(c)] == ['16:00', '16:30']
    assert 'slot_times' not in c.business.knowledge


def test_duration_fits_entire_window(isolated):
    assert [s['datetime'][11:16] for s in slots(mapped(duration=60))] == ['16:00']


def test_early_start_not_legacy_times(isolated):
    clocks = [s['datetime'][11:16] for s in slots(mapped(opening='08:00', closing='17:00'))]
    assert clocks[:2] == ['08:00', '08:30'] and clocks[-1] == '16:30'
    assert '18:30' not in clocks and len(clocks) == 18


def test_existing_sqlite_booking_excludes_overlap(isolated):
    c = mapped(duration=45); service = BookingService(c.business)
    slot = slots(c)[0]
    service.repository.create({'id':'occupied', 'interaction_id':'test_occupancy', 'customer_name':'Тест', 'phone':'+375290000000',
        'service':slot['service'], 'employee':slot['employee'], 'datetime':slot['datetime'],
        'duration_minutes':30, 'created_at':datetime.now().isoformat(), 'structured_data':{}})
    assert slots(c) == []  # 16:00 occupied; 16:30 cannot fit 45 minutes before 17:00.


def test_booking_only_blocks_occupied_employee(isolated):
    c = mapped(); c.business.knowledge['services'][0]['employees'] = [e['id'] for e in c.business.knowledge['employees']]
    service = BookingService(c.business); slot = slots(c)[0]
    service.repository.create({'id':'occupied', 'interaction_id':'test_occupancy', 'customer_name':'Тест', 'phone':'+375290000000',
        'service':slot['service'], 'employee':slot['employee'], 'datetime':slot['datetime'],
        'duration_minutes':30, 'created_at':datetime.now().isoformat(), 'structured_data':{}})
    available = slots(c)
    assert not any(s['datetime']==slot['datetime'] and s['employee']==slot['employee'] for s in available)
    assert any(s['datetime']==slot['datetime'] and s['employee']!=slot['employee'] for s in available)
    assert any(s['datetime'][11:16]=='16:30' and s['employee']==slot['employee'] for s in available)


@pytest.mark.parametrize('closed', [False, True])
def test_impossible_booking_is_validation_error(isolated, closed):
    c = mapped(duration=120)
    if closed: c.business.schedule = {str(d): [] for d in range(7)}
    report = validate_agent(c)
    assert not report['valid'] and any('Консультация' in e['message'] and 'нет ни одного' in e['message'] for e in report['errors'])


def test_multiple_windows_midnight_and_non_round_opening():
    schedule = {'0':[{'start':'09:10','end':'10:10'}, {'start':'23:00','end':'24:00'}], '1':[]}
    assert potential_clocks(schedule, 0, 30) == ['09:10','09:40','23:00','23:30']
    assert potential_clocks(schedule, 0, 60) == ['09:10','23:00']
    assert potential_clocks(schedule, 1, 30) == []


def test_saved_iteration2_generated_catalog_uses_schedule(isolated):
    c = mapped(); c.business.knowledge.pop('availability_mode')
    c.business.knowledge['slot_times'] = ['10:00','12:00','15:00','18:30','19:30']
    assert [s['datetime'][11:16] for s in slots(c)] == ['16:00','16:30']


def test_employee_subsets_are_id_references(isolated):
    business = nova()
    business['services'][0]['employees'] = ['Анна']
    business['services'][1]['employees'] = ['Мария']
    result = AgentBuilder(MockBuilder()).generate(BusinessInput.model_validate(business))
    assert result['validation']['valid']
    k = result['config']['business']['knowledge']; by_name = {e['name']:e['id'] for e in k['employees']}
    assert k['services'][0]['employees'] == [by_name['Анна']]
    assert k['services'][1]['employees'] == [by_name['Мария']]
    assert by_name['Анна'].startswith('business_')


@pytest.mark.parametrize('employees', [[], ['Мария']])
def test_unknown_employee_names_service_and_person(isolated, employees):
    business = nova(); business['employees'] = employees; business['services'][0]['employees'] = ['Анна']
    result = AgentBuilder(MockBuilder()).generate(BusinessInput.model_validate(business))
    assert not result['validation']['valid']
    message = result['validation']['errors'][0]['message']
    assert 'Маникюр' in message and 'Анна' in message and 'каталоге сотрудников' in message
    assert AgentBuilder(MockBuilder()).repository.list() == []


def test_employee_case_and_spaces_merge(isolated):
    business = nova(); business['employees'] = ['Анна','анна',' Анна ']
    business['services'][0]['employees'] = [' АННА ']
    result = AgentBuilder(MockBuilder()).generate(BusinessInput.model_validate(business))
    assert result['validation']['valid']
    k = result['config']['business']['knowledge']
    assert len(k['employees']) == 1 and k['employees'][0]['name'] == 'Анна'
    assert k['services'][0]['employees'] == [k['employees'][0]['id']]


def capture_provider(monkeypatch, proposal, registry):
    import providers.builder as adapter
    captured = {}
    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(proposal)))])
    monkeypatch.setattr(adapter, 'groq_client', lambda:SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    return GroqBuilderProvider(), captured


def test_shared_custom_registry_provider_mapper_validator(isolated, monkeypatch):
    registry = ToolRegistry().register(ToolDefinition('transfer_to_human', lambda c:handoff_tool(),
        ('human_handoff','custom_support'), read_only=False, kind='escalation'))
    proposal = draft(); proposal.update(scenarios=['faq','human_handoff'], tools=['transfer_to_human'])
    provider, captured = capture_provider(monkeypatch, proposal, registry)
    builder = AgentBuilder(provider, registry=registry)
    result = builder.generate(BusinessInput.model_validate(nova()))
    assert builder.registry is provider.registry is registry
    assert result['validation']['valid'], result['validation']
    assert set(result['config']['business']['capabilities']) == {'human_handoff','custom_support'}
    schema = captured['response_format']['json_schema']['schema']
    assert schema['properties']['tools']['items']['enum'] == ['transfer_to_human']
    assert 'booking' not in schema['properties']['scenarios']['items']['enum']
    advertised = json.loads(captured['messages'][1]['content'])['catalog']
    assert advertised['tools'] == [{'name':'transfer_to_human','capabilities':['human_handoff','custom_support']}]
    assert 'booking' not in [s['id'] for s in advertised['scenarios']]
    assert 'create_booking' not in captured['messages'][0]['content']
    c = AgentConfig.model_validate(result['config'])
    assert validate_agent(c, registry)['valid'] and registry.resolve_for_agent(c)[0].name == 'transfer_to_human'
    assert not validate_agent(c, ToolRegistry())['valid']


def test_missing_registry_tool_not_advertised_and_cannot_map(isolated, monkeypatch):
    registry = ToolRegistry()
    assert strict_schema(registry)['properties']['tools']['items']['enum'] == []
    assert 'human_handoff' not in strict_schema(registry)['properties']['scenarios']['items']['enum']
    proposal = draft(); proposal.update(scenarios=['human_handoff'], tools=['transfer_to_human'])
    provider, captured = capture_provider(monkeypatch, proposal, registry)
    result = AgentBuilder(provider, registry=registry).generate(BusinessInput.model_validate(nova()))
    assert not result['validation']['valid']
    assert json.loads(captured['messages'][1]['content'])['catalog']['tools'] == []


def test_provider_registry_preserved_without_override(isolated):
    registry = ToolRegistry()
    provider = GroqBuilderProvider(registry)
    assert AgentBuilder(provider).registry is provider.registry is registry
