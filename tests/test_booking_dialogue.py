from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pytest
import storage
from agents.runtime import AgentRuntime, new_interaction
from agents.fields import user_record_valid
from agents.prompts import build_system_prompt
from prompts import load_agent
from providers.base import ModelReply
from services.booking_service import BookingService
from tools.booking import booking_tools
from tools.handoff import handoff_tool


class BrokenProvider:
    def __init__(self):
        self.calls = 0

    def complete(self, messages, tools):
        self.calls += 1
        return ModelReply('Я понял. Давайте я сначала уточню, какое имя у вас есть? Скидка 10%, цена 45 BYN.')


@pytest.fixture
def dialogue(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'DB_PATH', tmp_path / 'calls.db')
    storage.initialize_db()
    config = load_agent()
    state = new_interaction(config)
    provider = BrokenProvider()
    runtime = AgentRuntime(config, provider, [*booking_tools(BookingService(config.business), config.fields), handoff_tool()])
    return runtime, state, provider


def select_slot(runtime, state):
    runtime.turn(state, 'Маникюр')
    answer = runtime.turn(state, 'Вообще пофиг, скажи что свободно')
    assert state['tool_events'] and 'доступны' in answer['text']
    slot = next(e for e in state['tool_events'] if e['result'].get('slots'))['result']['slots'][0]
    assert runtime.turn(state, slot['datetime'][11:16])['text'] == 'Как вас зовут?'
    return slot


def test_actual_failed_call_cannot_invent_pedicure(dialogue):
    runtime, state, provider = dialogue
    answer = runtime.turn(state, 'Меня интересует, братка, педикюр')
    assert 'нет в опубликованном каталоге' in answer['text']
    assert '50' not in answer['text'] and provider.calls == 0
    assert not state['tool_events']


def test_no_preference_queries_calendar_and_booking_finishes_with_consent(dialogue):
    runtime, state, provider = dialogue
    slot = select_slot(runtime, state)
    assert runtime.turn(state, 'Василий.')['text'] == 'Назовите телефон для связи.'
    result = runtime.turn(state, '+375291234567')
    assert result['status'] == 'awaiting_confirmation'
    assert state['pending_action']['arguments']['datetime'] == slot['datetime']
    assert provider.calls == 1
    assert runtime.turn(state, 'Да, подтверждаю')['status'] == 'completed'


def test_noise_is_not_a_name_and_price_interruption_does_not_lose_fields(dialogue):
    runtime, state, provider = dialogue
    select_slot(runtime, state)
    runtime.turn(state, 'Мария ' * 70)
    assert 'customer_name' not in state['collected_fields']
    runtime.turn(state, 'Василий.')
    result = runtime.turn(state, '50 дорого, можно скидку?')
    assert '50 BYN' in result['text'] and 'не могу назначить скидку' in result['text']
    assert '45' not in result['text'] and '10%' not in result['text']
    assert result['text'].endswith('Назовите телефон для связи.')
    assert state['collected_fields']['customer_name']['value'] == 'Василий'
    assert runtime.turn(state, '+375291234567')['status'] == 'awaiting_confirmation'


def test_yesterday_rejected_and_nearest_confirmation_recovers(dialogue):
    runtime, state, _ = dialogue
    runtime.turn(state, 'Маникюр вчера')
    assert 'прошедшую дату' in runtime.turn(state, 'вчера')['text']
    result = runtime.turn(state, 'Да')
    assert 'доступны' in result['text']
    slot = state['tool_events'][-1]['result']['slots'][0]
    assert runtime.turn(state, slot['datetime'][11:16])['text'] == 'Как вас зовут?'


def test_gender_is_not_guessed_and_accepting_any_master_persists(dialogue):
    runtime, state, _ = dialogue
    runtime.turn(state, 'Маникюр завтра')
    assert 'нет подтверждённых сведений' in runtime.turn(state, 'Мастер мужик')['text']
    assert 'доступны' in runtime.turn(state, 'Да')['text']
    slot = state['tool_events'][-1]['result']['slots'][0]
    assert runtime.turn(state, slot['datetime'][11:16])['text'] == 'Как вас зовут?'


def test_prefixed_question_and_phone_plus_keep_verifiable_evidence(dialogue):
    runtime, state, _ = dialogue
    runtime.respond(state, 'Хорошо. Как вас зовут?')
    runtime.turn(state, 'Василий.')
    runtime.turn(state, 'Номер телефона плюс 375 29 123 45 67')
    for field in runtime.config.fields:
        if field.id in ('phone', 'customer_name'):
            assert user_record_valid(field, state['collected_fields'][field.id], state)
    assert state['collected_fields']['phone']['value'] == '+375291234567'


def test_caller_phone_is_not_invented_and_goodbye_stops(dialogue):
    runtime, state, _ = dialogue
    select_slot(runtime, state)
    runtime.turn(state, 'Василий')
    answer = runtime.turn(state, 'Нет телефона, звоню по тапку')
    assert 'недоступен' in answer['text'] and 'phone' not in state['collected_fields']
    assert runtime.turn(state, 'Отказываюсь от вашей услуги. До свидания')['complete']
    assert not state['pending_action']


def test_female_identity_is_in_system_prompt(dialogue):
    assert 'женском роде' in build_system_prompt(dialogue[0].config)


@pytest.mark.parametrize('phrase', ['хотел бы записаться на пятницу', 'пятница', 'в пятницу'])
def test_friday_checks_calendar_instead_of_repeating_date(dialogue, phrase):
    runtime, state, provider = dialogue
    runtime.turn(state, 'Маникюр')
    answer = runtime.turn(state, phrase)
    target = datetime.now(ZoneInfo(runtime.config.business.timezone)).date()
    target += timedelta(days=(4 - target.weekday()) % 7)
    assert state['tool_events'][-1]['arguments']['date'] == target.isoformat()
    assert 'Какой день вам подходит?' not in answer['text']
    assert state['tool_events'][-1]['name'] == 'check_slots'


@pytest.mark.parametrize('phrase,expected', [
    ('понедельник', '2026-10-19'), ('во вторник', '2026-10-20'),
    ('в среду', '2026-10-14'), ('четверг', '2026-10-15'),
    ('пятницу', '2026-10-16'), ('суббота', '2026-10-17'),
    ('в воскресенье', '2026-10-18'), ('на следующей неделе в пятницу', '2026-10-23'),
    ('на этой неделе в понедельник', '2026-10-12'),
])
def test_weekdays_and_week_boundaries(phrase, expected):
    from agents.booking_dialogue import weekday_date
    from datetime import date
    assert weekday_date(phrase, date(2026, 10, 14)).isoformat() == expected


def test_unsupported_pedicure_and_manicure_require_clear_choice(dialogue):
    runtime, state, provider = dialogue
    answer = runtime.turn(state, 'Здравствуйте! Пиди-кюр и маникюр.')
    assert 'Педикюра нет' in answer['text'] and 'Продолжить' in answer['text']
    assert not state['tool_events']
    runtime.turn(state, 'хотел бы записаться на пятницу')
    answer = runtime.turn(state, 'Да')
    assert state['tool_events'][-1]['arguments']['service'] == 'маникюр'
    assert 'доступны' in answer['text']


def test_multiple_supported_services_are_not_silently_reduced_to_one(dialogue):
    runtime, state, _ = dialogue
    assert 'С какой начнём' in runtime.turn(state, 'Маникюр и стрижка')['text']
    assert not state['tool_events']
    runtime.turn(state, 'Маникюр')
    assert 'доступны' in runtime.turn(state, 'в пятницу')['text']


def test_friday_is_remembered_after_repeat_and_confused_followup(dialogue):
    runtime, state, _ = dialogue
    runtime.turn(state, 'Маникюр')
    runtime.turn(state, 'хотел бы записаться на пятницу')
    runtime.turn(state, 'пятница')
    answer = runtime.turn(state, 'а я забыл, как')
    assert 'доступны' in answer['text']
    assert 'Какой день вам подходит?' not in answer['text']
    assert len([e for e in state['tool_events'] if e['name'] == 'check_slots']) == 1


@pytest.mark.parametrize('text', ['Стрижка волос на лобке', 'Интимная стрижка', 'Стрижка зоны бикини'])
def test_generic_haircut_does_not_authorize_unsupported_body_area(dialogue, text):
    runtime, state, provider = dialogue
    answer = runtime.turn(state, text)
    assert 'нет в опубликованном каталоге' in answer['text']
    runtime.turn(state, 'завтра')
    assert not state['tool_events'] and provider.calls == 0


@pytest.mark.parametrize('text', ['15.00', '15:00', '1500', '15-0-0', 'на три часа', 'три часа', 'в три дня', 'в пятнадцать', 'пятнадцать', 'пятнадцать часов', '15', '15 часов'])
def test_common_time_formats_advance_to_name(dialogue, text):
    runtime, state, _ = dialogue
    runtime.turn(state, 'Маникюр')
    runtime.turn(state, 'в пятницу на следующей неделе')
    answer = runtime.turn(state, text)
    assert answer['text'].endswith('Как вас зовут?')
    assert state['booking_preferences']['time'] == '15:00'


@pytest.mark.parametrize('text', ['а можно записаться к Марии', 'к Марии', 'мастер Мария'])
def test_master_must_offer_selected_service(dialogue, text):
    runtime, state, _ = dialogue
    runtime.turn(state, 'Стрижка')
    runtime.turn(state, 'завтра')
    answer = runtime.turn(state, text)
    assert 'не оказывает услугу' in answer['text'] and 'Ольга' in answer['text']
    runtime.turn(state, 'к Ольге')
    assert runtime.turn(state, '15.00')['text'] == 'Как вас зовут?'


def test_unknown_master_is_not_silently_ignored(dialogue):
    runtime, state, _ = dialogue
    runtime.turn(state, 'Стрижка')
    assert 'Такого мастера нет' in runtime.turn(state, 'к Пете')['text']
    runtime.turn(state, 'к Ольге')
    runtime.turn(state, 'завтра')
    assert runtime.turn(state, '15:00')['text'] == 'Как вас зовут?'


def test_full_ordered_haircut_flow_after_unsupported_request(dialogue):
    runtime, state, _ = dialogue
    runtime.turn(state, 'стрижка волос на лобке')
    assert not state['tool_events']
    assert 'Какой день' in runtime.turn(state, 'обычная стрижка')['text']
    assert 'доступны' in runtime.turn(state, 'завтра')['text']
    assert 'не оказывает' in runtime.turn(state, 'к Марии')['text']
    runtime.turn(state, 'к Ольге')
    assert runtime.turn(state, 'на три часа')['text'] == 'Как вас зовут?'
    assert runtime.turn(state, 'Алексей')['text'] == 'Назовите телефон для связи.'
    result = runtime.turn(state, '+375290000000')
    assert result['status'] == 'awaiting_confirmation'
    assert state['pending_action']['arguments']['employee'] == 'Ольга'
    assert state['pending_action']['arguments']['datetime'][11:16] == '15:00'
    assert runtime.turn(state, 'Да')['status'] == 'completed'


def test_booking_refusal_does_not_create_a_new_proposal(dialogue):
    runtime, state, _ = dialogue
    select_slot(runtime, state)
    runtime.turn(state, 'Василий')
    runtime.turn(state, '+375290000000')
    assert runtime.turn(state, 'Нет')['text'].startswith('Запись не создана')
    assert runtime.turn(state, 'а я забыл, как')['text'].startswith('Запись не создана')
    assert not state['pending_action']


def test_bare_inflected_master_choice_after_incompatible_master(dialogue):
    runtime, state, _ = dialogue
    runtime.turn(state, 'Стрижка')
    runtime.turn(state, 'завтра')
    runtime.turn(state, 'к марии')
    assert 'доступны' in runtime.turn(state, 'Ольга')['text']
    assert runtime.turn(state, '15.00')['text'] == 'Как вас зовут?'


@pytest.mark.parametrize('text', ['после шести', 'после 18:00', 'после трёх'])
def test_lower_bound_uses_actual_later_slot(dialogue, text):
    runtime, state, _ = dialogue
    runtime.turn(state, 'Маникюр')
    runtime.turn(state, 'в пятницу на следующей неделе')
    assert runtime.turn(state, text)['text'] == 'Как вас зовут?'
    assert state['booking_preferences']['time'] == '18:30'


def test_spaced_phone_with_hhmm_digits_is_still_a_phone(dialogue):
    runtime, state, _ = dialogue
    select_slot(runtime, state)
    runtime.turn(state, 'Василий')
    answer = runtime.turn(state, '+375 29 1515 000')
    assert answer['status'] == 'awaiting_confirmation'
    assert state['collected_fields']['phone']['value'] == '+375291515000'
