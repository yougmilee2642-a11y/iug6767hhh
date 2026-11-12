"""«Фокус» отвечает на приветствия и разговорные реплики, не трогая рабочие вопросы."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from meetings import voice
from meetings.voice_chat import JOKES, small_talk, split_greeting

USER = {'name': 'Марина Зелёнова'}
NOON = datetime(2026, 11, 12, 13, 30, tzinfo=ZoneInfo('Europe/Minsk'))
FIRST = lambda options: options[0]  # noqa: E731 - deterministic choice for assertions


@pytest.mark.parametrize('text, expected', [
    ('привет', 'Добрый день, Марина! Чем помочь?'),
    ('Привет, Фокус!', 'Добрый день, Марина! Чем помочь?'),
    ('Фокус', 'Добрый день, Марина! Слушаю.'),
    ('Окей, Фокус', 'Добрый день, Марина! Слушаю.'),
    ('спасибо', 'Пожалуйста! Обращайтесь.'),
    ('который час', 'Сейчас 13:30.'),
    ('какое сегодня число', 'Сегодня четверг, 12 ноября.'),
    ('пока', 'До встречи, Марина! Хорошего дня.'),
    ('Слушай, Фокус, который час', 'Сейчас 13:30.'),
])
def test_small_talk_is_friendly_and_personal(text, expected):
    assert small_talk(text, USER, NOON, FIRST) == expected


def test_help_joke_and_rudeness_have_answers():
    assert 'Что важного сегодня' in small_talk('что ты умеешь?', USER, NOON, FIRST)
    assert small_talk('расскажи шутку', USER, NOON, FIRST) in JOKES
    assert 'по-другому' in small_talk('ты тупой', USER, NOON, FIRST)
    assert small_talk('привет, как дела', USER, NOON, FIRST).startswith('Добрый день, Марина! ')


@pytest.mark.parametrize('text', ['Какова выручка завода?', 'Сколько просроченных задач?', 'Что важного сегодня?',
                                  'Как оформить перепечатку фотокниги?', 'Покажи KPI', 'Поставь задачу Анне',
                                  'Время изготовления Premium?', 'Помоги найти регламент ОТК', 'Фокус на сроках важен?',
                                  'Привет, сколько просроченных задач?'])
def test_work_questions_are_not_small_talk(text):
    assert small_talk(text, USER, NOON, FIRST) is None


def test_greeting_and_name_are_stripped_before_routing():
    assert split_greeting('Привет, сколько просроченных задач?') == (True, 'сколько просроченных задач?')
    assert split_greeting('Окей, Фокус, поставь задачу Анне') == (False, 'поставь задачу Анне')
    assert split_greeting('Фокус на сроках важен?') == (False, 'Фокус на сроках важен?')
    assert voice.route(split_greeting('Привет, сколько просроченных задач?')[1]) == 'overview'
    assert voice.route(split_greeting('Окей, Фокус, поставь задачу Анне')[1]) == 'action'


def test_chat_reply_is_spoken_without_reading_company_data(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError('small talk must not read documents or metrics')
    for name in ('answer_knowledge', 'answer_overview', 'answer_briefing'):
        monkeypatch.setattr(voice, name, forbidden)
    details = {}
    reply = voice.ask({'id': 1, 'name': 'Марина Зелёнова'}, 'Привет, Фокус', None, False, details)
    assert reply['route'] == 'chat' and reply['speak'] is True and 'Марина' in reply['spoken']
    assert details['route'] == 'chat'


def test_greeting_then_command_is_still_refused():
    reply = voice.ask({'id': 1, 'name': 'Марина Зелёнова'}, 'Привет, поставь задачу Анне на пятницу', None, False, {})
    assert reply['route'] == 'action' and reply['status'] == 'refused'
    assert reply['spoken'].startswith(('Доброе утро, Марина!', 'Добрый день, Марина!', 'Добрый вечер, Марина!', 'Доброй ночи, Марина!'))
    assert 'ничего не создаю и не меняю' in reply['spoken']
