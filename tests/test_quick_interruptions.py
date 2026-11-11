import pytest
import storage
from agents.factory import create_runtime
from agents.runtime import new_interaction
from agents.quick_dialogue import CALLBACK_DECLINED
from services.track1_service import make_config, QuickInput, FAQInput
from providers.base import ModelReply, ToolCall
from evaluation.providers import ScriptedUserSimulator


class Agent:
    def complete(self, messages, tools):
        return ModelReply('Как к вам обращаться?')


@pytest.fixture
def reception(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'DB_PATH', tmp_path / 'test.db')
    storage.initialize_db()
    config = make_config(QuickInput(business_name='Ronin', greeting='Здравствуйте! Как к вам обращаться?',
                                   facts='Компания принимает обращения.',
                                   qa=[FAQInput(question='Можно забронировать столик?', answer='Да, уточните время.')]), 'ronin')
    return create_runtime(config, Agent()), new_interaction(config)


def test_identity_question_does_not_become_name(reception):
    runtime, state = reception
    result = runtime.turn(state, 'Представьтесь, назовите свою роль дословно и объясните, чем вы можете помочь.')
    assert runtime.config.role.name in result['text']
    assert 'Принимает обращения' in result['text']
    assert not state['collected_fields'] and not state['pending_collection']


def test_faq_before_name_is_answered_without_collection(reception):
    runtime, state = reception
    assert runtime.turn(state, 'Можно забронировать столик?')['text'] == 'Да, уточните время.'
    assert not state['collected_fields'] and not state['pending_collection']


@pytest.mark.parametrize('refusal', ['Нет', 'Нет, не записывайте меня.', 'Не сохраняйте обращение.'])
def test_refusal_remains_active_but_blocks_new_proposal_without_new_request(reception, refusal):
    runtime, state = reception
    runtime.turn(state, 'Меня зовут Анна. Мой телефон +375291112233')
    runtime.respond(state, 'Кратко расскажите, по какому вопросу вы звоните.')
    runtime.turn(state, 'доставка')
    args = {key: state['collected_fields'][key]['value'] for key in ('customer_name', 'phone', 'request_details')}
    _, proposal = runtime.dispatch(ToolCall('prepare', 'save_callback_request', args), state)
    runtime.respond(state, proposal)
    assert runtime.turn(state, refusal)['text'] == CALLBACK_DECLINED
    assert state['status'] == 'active' and not state['pending_action']
    assert runtime.turn(state, 'Мой телефон +375291112233')['text'] == CALLBACK_DECLINED
    result, _ = runtime.dispatch(ToolCall('malicious', 'save_callback_request', args), state)
    assert 'error' in result and not state['pending_action']
    runtime.turn(state, 'Хочу снова оформить обратный звонок')
    result, _ = runtime.dispatch(ToolCall('fresh', 'save_callback_request', args), state)
    assert result.get('confirmation_required')


def test_initial_cancel_is_respected(reception):
    runtime, state = reception
    result = runtime.turn(state, 'Хочу обратный звонок. Меня зовут Анна. Не сохраняйте обращение.')
    assert result['text'] == CALLBACK_DECLINED and not state['tool_events']


@pytest.mark.parametrize('text', ['Телефон сообщать не буду.', 'Не буду сообщать телефон.', 'Нет телефона.'])
def test_missing_contact_is_not_another_name_question(reception, text):
    runtime, state = reception
    answer = runtime.turn(state, text)
    assert 'Без контактного телефона' in answer['text']
    assert not state['pending_collection'] and not state['pending_action']
    assert not state['collected_fields']


def test_simulated_client_stops_after_refusal_even_if_answer_contains_phone():
    visible = {'transcript': [{'role': 'user', 'content': 'Нет, не записывайте меня.'},
                              {'role': 'assistant', 'content': 'Обращение не сохранено. Телефон ресторана +375291112233.'}], 'status': 'active'}
    answer = ScriptedUserSimulator().reply({'behavior': 'refuse', 'known_data': {}, 'opening': ''}, visible)
    assert answer['done'] and not answer['text']
