"""Pitch regressions: server-controlled booking, no dependence on model fluency."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pytest
import storage
from prompts import load_agent
from agents.runtime import AgentRuntime, new_interaction
from services import customer_safety
from services.booking_service import BookingService
from tools.booking import booking_tools
from tools.handoff import handoff_tool


class NoModel:
    def complete(self,*_): pytest.fail('Structured booking must not depend on an LLM reply')


@pytest.fixture
def scenario(tmp_path,monkeypatch):
    monkeypatch.setenv('CALLWISE_CONVERSATION_SAFETY','true')
    monkeypatch.setattr(storage,'DB_PATH',tmp_path/'scenario.sqlite')
    storage.initialize_db()
    config=load_agent()
    # A synthetic schedule-backed catalog, not a live salon mutation.
    config.business.knowledge['availability_mode']='schedule_30m'
    state=new_interaction(config)
    customer_safety.consent(state,config,True,state['privacy']['version'])
    service=BookingService(config.business)
    runtime=AgentRuntime(config,NoModel(),[*booking_tools(service,config.fields),handoff_tool()])
    return runtime,state,service


def tomorrow(config):
    return (datetime.now(ZoneInfo(config.business.timezone))+timedelta(days=1)).date().isoformat()


@pytest.mark.parametrize('phrase',[
    'Я хочу записаться завтра на стрижку в пять часов',
    'Запишите меня на стрижку завтра в 17:00',
    'Завтра в 17:00 хочу записаться на стрижку',
    'Хочу записаться на стрижку в пять вечера завтра',
    'Хочу записаться завтра на окрашивание в 17:00',
])
def test_first_phrase_preserves_service_date_time_and_checks_calendar(scenario,phrase):
    runtime,state,_=scenario
    result=runtime.turn(state,phrase)
    assert result['text'].endswith('Как вас зовут?')
    assert state['booking_preferences']['time']=='17:00'
    events=state['tool_events']
    assert len(events)==1 and events[0]['name']=='check_slots'
    assert events[0]['arguments']['date']==tomorrow(runtime.config)
    assert not state['pending_action']


@pytest.mark.parametrize('service_name',['стрижку','лазерную эпиляцию','массаж','укладку'])
def test_unknown_service_cannot_be_substituted_or_sent_to_calendar(scenario,service_name):
    runtime,state,_=scenario
    runtime.config.business.knowledge['services']=[runtime.config.business.knowledge['services'][0]]
    result=runtime.turn(state,f'Хочу записаться завтра на {service_name} в 17:00')
    assert 'нет в опубликованном каталоге' in result['text']
    assert not state['tool_events'] and not state['pending_action']
    assert state['booking_preferences']['date']==tomorrow(runtime.config)
    # A replacement choice retains the already supplied date and time.
    result=runtime.turn(state,'Тогда маникюр')
    assert result['text'].endswith('Как вас зовут?')
    assert state['booking_preferences']['time']=='17:00'


def test_requested_time_unavailable_is_not_silently_changed(scenario):
    runtime,state,service=scenario
    day=tomorrow(runtime.config)
    service.repository.create({'id':'occupied','interaction_id':'setup','customer_name':'Тест','phone':'+375290000000',
        'service':'стрижка','employee':'Ольга','datetime':day+'T17:00:00+03:00','duration_minutes':60,
        'created_at':day,'structured_data':{}})
    answer=runtime.turn(state,'Хочу записаться завтра на стрижку в пять часов')['text']
    assert '17:00' in answer and 'свободного слота нет' in answer
    assert not state['pending_action']


def test_multi_fact_first_turn_then_contacts_and_confirmation(scenario):
    runtime,state,_=scenario
    runtime.turn(state,'Хочу записаться завтра на стрижку в 17:00. Меня зовут Алексей. Мой телефон +375291234567')
    assert state['status']=='awaiting_confirmation'
    assert state['pending_action']['arguments']['service']=='стрижка'
    assert state['pending_action']['arguments']['datetime'][11:16]=='17:00'
    with storage.connect() as db:assert db.execute('SELECT COUNT(*) FROM bookings').fetchone()[0]==0
    assert runtime.turn(state,'Да, подтверждаю')['status']=='completed'
    with storage.connect() as db:assert db.execute('SELECT COUNT(*) FROM bookings').fetchone()[0]==1


def test_correction_is_applied_before_confirming_new_proposal(scenario):
    runtime,state,_=scenario
    runtime.turn(state,'Запишите меня завтра на стрижку в 17:00. Меня зовут Алексей. Мой телефон +375291234567')
    assert state['status']=='awaiting_confirmation'
    runtime.turn(state,'Не в 17:00, а в 19:00')
    assert state['status']=='awaiting_confirmation'
    assert state['pending_action']['arguments']['datetime'][11:16]=='19:00'
    with storage.connect() as db:assert db.execute('SELECT COUNT(*) FROM bookings').fetchone()[0]==0


def test_multiple_services_require_choice(scenario):
    runtime,state,_=scenario
    result=runtime.turn(state,'Хочу записаться завтра на маникюр и стрижку в 17:00')
    assert 'С какой начнём' in result['text'] and not state['tool_events']
    assert runtime.turn(state,'На стрижку')['text'].endswith('Как вас зовут?')


def test_alias_is_configuration_not_guessed_synonym(scenario):
    runtime,state,_=scenario
    runtime.config.business.knowledge['service_aliases']={'стрижка':['подстричься']}
    result=runtime.turn(state,'Хочу завтра подстричься в 17:00')
    assert result['text'].endswith('Как вас зовут?')
    assert state['booking_preferences']['service']=='стрижка'


def test_ambiguous_clock_is_clarified_not_guessed(scenario):
    runtime,state,_=scenario
    runtime.config.business.schedule.clear()
    runtime.config.business.schedule.update({str(day):[{'start':'00:00','end':'24:00'}] for day in range(7)})
    result=runtime.turn(state,'Хочу записаться завтра на стрижку в пять часов')
    assert '05:00 или 17:00' in result['text']
    assert state['booking_flow']['step']=='time' and not state['pending_action']
    assert runtime.turn(state,'В пять вечера')['text'].endswith('Как вас зовут?')
    assert state['booking_preferences']['time']=='17:00'


def test_change_service_does_not_turn_service_name_into_customer_name(scenario):
    runtime,state,_=scenario
    runtime.turn(state,'Хочу записаться завтра на маникюр в 17:00')
    result=runtime.turn(state,'Лучше на стрижку')
    assert result['text'].endswith('Как вас зовут?')
    assert 'customer_name' not in state['collected_fields']
    assert state['booking_preferences']['service']=='стрижка'
    assert state['booking_preferences']['time']=='17:00'


def test_contacts_before_booking_facts_are_not_lost(scenario):
    runtime,state,_=scenario
    result=runtime.turn(state,'Меня зовут Алексей. Мой телефон +375291234567. Хочу записаться завтра на стрижку в 17:00')
    assert result['status']=='awaiting_confirmation'
    assert state['pending_action']['arguments']['datetime'][11:16]=='17:00'
    assert state['booking_flow']['step']=='confirmation'


def test_calendar_failure_cannot_be_reported_as_availability(scenario,monkeypatch):
    runtime,state,service=scenario
    def unavailable(*_):raise ValueError('Календарь временно недоступен')
    monkeypatch.setattr(service.repository,'for_date',unavailable)
    result=runtime.turn(state,'Хочу записаться завтра на стрижку в 17:00')
    assert 'Не удалось проверить расписание' in result['text']
    assert len(state['tool_events'])==2 and all('error' in event['result'] for event in state['tool_events'])
    assert not state['pending_action']


def test_slot_taken_before_final_consent_refreshes_calendar(scenario):
    runtime,state,service=scenario
    runtime.turn(state,'Хочу записаться завтра на стрижку в 17:00. Меня зовут Алексей. Мой телефон +375291234567')
    day=tomorrow(runtime.config)
    service.repository.create({'id':'race','interaction_id':'setup','customer_name':'Тест','phone':'+375290000000',
        'service':'стрижка','employee':'Ольга','datetime':day+'T17:00:00+03:00','duration_minutes':60,
        'created_at':day,'structured_data':{}})
    result=runtime.turn(state,'Да, подтверждаю')
    assert 'свободного слота нет' in result['text'] and not state['pending_action']
    assert state['status']!='completed'
    with storage.connect() as db:assert db.execute('SELECT COUNT(*) FROM bookings WHERE interaction_id=?',(state['id'],)).fetchone()[0]==0


def test_refusal_and_handoff_do_not_execute_a_booking(scenario):
    runtime,state,_=scenario
    runtime.turn(state,'Хочу записаться завтра на стрижку в 17:00. Меня зовут Алексей. Мой телефон +375291234567')
    assert runtime.turn(state,'Нет, не записывайте меня')['text'].startswith('Запись не создана')
    assert not state['pending_action']
    result=runtime.turn(state,'Хочу живого человека')
    assert result['complete'] and state['review_request']['reason']=='refused_ai'
    with storage.connect() as db:assert db.execute('SELECT COUNT(*) FROM bookings').fetchone()[0]==0


@pytest.mark.parametrize('phrase',[
    'Хочу записаться завтра на стрижку в семнадцать тридцать',
    'Хочу записаться завтра на стрижку в 17 часов 30 минут',
    'Хочу записаться завтра на стрижку в пять тридцать вечера',
])
def test_minutes_are_not_dropped(scenario,phrase):
    runtime,state,_=scenario
    assert runtime.turn(state,phrase)['text'].endswith('Как вас зовут?')
    assert state['booking_preferences']['time']=='17:30'


def test_alternative_dates_require_choice(scenario):
    runtime,state,_=scenario
    assert 'Уточните дату' in runtime.turn(state,'Хочу записаться завтра или послезавтра на стрижку в 17:00')['text']
    assert not state['tool_events']
    assert runtime.turn(state,'Завтра')['text'].endswith('Как вас зовут?')


def test_closed_day_does_not_create_slots(scenario):
    runtime,state,_=scenario
    runtime.config.business.schedule.clear()
    runtime.config.business.schedule.update({str(day):[] for day in range(7)})
    result=runtime.turn(state,'Хочу записаться завтра на стрижку в 17:00')
    assert 'слотов нет' in result['text'] and not state['pending_action']
    assert all(not event['result']['slots'] for event in state['tool_events'])


def test_unknown_service_keeps_spoken_time_until_catalog_choice(scenario):
    runtime,state,_=scenario
    runtime.config.business.knowledge['services']=[runtime.config.business.knowledge['services'][0]]
    runtime.turn(state,'Хочу записаться завтра на стрижку в пять часов')
    assert state['booking_preferences']['time_candidates']==['05:00','17:00']
    assert runtime.turn(state,'Маникюр')['text'].endswith('Как вас зовут?')
    assert state['booking_preferences']['time']=='17:00'


def test_refusal_precedes_booking_parser_and_new_request_can_resume(scenario):
    runtime,state,_=scenario
    runtime.turn(state,'Хочу записаться завтра на стрижку в 17:00. Меня зовут Алексей. Мой телефон +375291234567')
    assert runtime.turn(state,'Не хочу записаться, передумал')['text'].startswith('Запись не создана')
    assert not state['pending_action']
    assert runtime.turn(state,'Хочу снова записаться завтра на стрижку в 19:00')['status']=='awaiting_confirmation'
    assert state['pending_action']['arguments']['datetime'][11:16]=='19:00'
    with storage.connect() as db:assert db.execute('SELECT COUNT(*) FROM bookings').fetchone()[0]==0
