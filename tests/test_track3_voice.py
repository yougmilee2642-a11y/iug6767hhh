"""Manager voice assistant: routing, no writes by voice, speaker privacy, honest refusal."""
import json

import pytest

from meetings import store, voice
from test_track3_knowledge_support import env, document, meeting, task, snapshot, audit_rows  # noqa: F401

FACT = 'Запуск проекта назначен на 1 декабря 2026 года.'


def say(env, text, who='irina', **extra):
    return env[who].post('/api/meet/voice/ask', json={'text': text, **extra})


def counts():
    with store.db() as connection:
        return {table: connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                for table in ('tasks', 'meetings', 'confirmations', 'calendar_events', 'calendar_outbox')}


@pytest.mark.parametrize('text,expected', [
    ('Когда запуск проекта?', 'knowledge'),
    ('Какой лимит оплаты по договору?', 'knowledge'),
    ('Что в регламенте сказано про брак?', 'knowledge'),
    ('Сколько у нас просроченных задач?', 'overview'),
    ('Какие задачи поставили вчера?', 'overview'),
    ('Какой процент брака за месяц?', 'overview'),
    ('Покажи KPI', 'overview'),
    ('Поставь задачу Анне на пятницу', 'action'),
    ('Пригласите Петра на встречу в четверг', 'action'),
    ('Можешь, пожалуйста, создать встречу с Петром?', 'action'),
    ('Надо перенести планёрку на завтра', 'action'),
    ('Отметь задачу 5 выполненной', 'action'),
])
def test_routing_is_deterministic(text, expected):
    assert voice.route(text) == expected


def test_knowledge_answer_spoken_with_source_and_date(env):
    document(env['irina'], FACT, shared='2')
    response = say(env, 'Когда запуск проекта?')
    assert response.status_code == 200, response.text
    reply = response.json()
    assert reply['route'] == 'knowledge' and reply['speak'] is True
    assert reply['spoken'].startswith(FACT)
    assert '«План запуска»' in reply['spoken'] and '2026' in reply['spoken']
    assert reply['answer']['claims'][0]['sources'][0]['quote'] == FACT
    logged = audit_rows('voice.ask')[-1]
    assert logged['route'] == 'knowledge' and logged['spoken'] is True
    assert FACT not in json.dumps(logged, ensure_ascii=False) and 'Когда' not in json.dumps(logged, ensure_ascii=False)


def test_private_document_is_shown_not_spoken_by_default(env):
    document(env['irina'], FACT)  # Пётр не видит документ
    reply = say(env, 'Когда запуск проекта?').json()
    assert reply['answer']['status'] == 'grounded'
    assert reply['speak'] is False and reply['spoken'] is None
    assert FACT in reply['display'] and 'не все участники' in reply['silent_reason']
    assert audit_rows('voice.ask')[-1]['private'] is True
    alone = say(env, 'Когда запуск проекта?', speak_private=True).json()
    assert alone['speak'] is True and alone['spoken'].startswith(FACT)


def test_meeting_audience_decides_privacy(env):
    doc, _ = document(env['irina'], FACT)
    solo = meeting(env['irina'], (doc,))
    reply = say(env, 'Когда запуск проекта?', meeting_id=solo).json()
    assert reply['speak'] is True, 'only Irina is in this meeting'
    shared = meeting(env['irina'], (doc,), shared=(2,))
    reply = say(env, 'Когда запуск проекта?', meeting_id=shared).json()
    assert reply['speak'] is False and reply['spoken'] is None


def test_foreign_meeting_is_not_found(env):
    closed = meeting(env['irina'])
    assert say(env, 'Когда запуск проекта?', who='petr', meeting_id=closed).status_code == 404
    assert say(env, 'Сколько просроченных задач?', who='petr', meeting_id=closed).status_code == 404


def test_honest_refusal_is_spoken(env):
    document(env['irina'], FACT, shared='2')
    reply = say(env, 'Какова выручка завода?').json()
    assert reply['route'] == 'knowledge' and reply['answer']['status'] == 'insufficient_data'
    assert reply['speak'] is True and 'оснований для ответа не найдено' in reply['spoken']
    assert env['model'].calls == []


@pytest.mark.parametrize('text', ['Поставь задачу Петру подготовить макет к пятнице',
                                  'Пригласи Петра на встречу завтра в 10',
                                  'Удали задачу про цветопробу', 'Можешь отменить встречу?'])
@pytest.mark.parametrize('who', ['irina', 'petr'])
def test_voice_never_writes(env, text, who):
    mid = meeting(env['irina'], shared=(2,))
    task(mid)
    before = counts()
    response = say(env, text, who=who)
    assert response.status_code == 200, response.text
    reply = response.json()
    supported=text.startswith(('Поставь','Пригласи'))
    assert reply['route'] == ('action_draft' if supported else 'action')
    assert reply['status'] == ('action_proposed' if supported else 'refused')
    assert 'на экране' in reply['spoken']
    assert ('Черновик готов' in reply['spoken']) if supported else ('ничего не создаю и не меняю' in reply['spoken'])
    assert reply['answer'] is None and counts() == before
    assert env['model'].calls == []
    assert audit_rows('voice.ask')[-1]['result'] == ('action_proposed' if supported else 'refused')


def test_overview_counts_spoken_only_when_everyone_sees_the_same(env):
    shared = meeting(env['irina'], shared=(2,))
    task(shared, due='2026-11-01')
    reply = say(env, 'Сколько просроченных задач?').json()
    assert reply['route'] == 'overview'
    assert 'открытых — 1, просроченных — 1' in reply['display']
    assert reply['speak'] is True
    hidden = meeting(env['irina'])
    task(hidden, due='2026-11-02')
    reply = say(env, 'Сколько просроченных задач?').json()
    assert 'просроченных — 2' in reply['display'] and reply['speak'] is False
    # In a meeting with only Irina the room hears her own numbers.
    assert say(env, 'Сколько просроченных задач?', meeting_id=hidden).json()['speak'] is True


def test_overview_metric_question_names_source_and_date(env):
    snapshot(shared=(2,))
    reply = say(env, 'Какой процент брака?').json()
    assert reply['route'] == 'overview'
    assert 'Производственная витрина на 11 ноября 2026: брак — 2 %.' == reply['display']
    assert reply['speak'] is True
    snapshot(source_id='print-2', scope='bind', values=(10, 10, 5, 100, 1, 2))  # only Irina
    assert say(env, 'Какой процент брака?').json()['speak'] is False


def test_long_quote_is_not_cut(env):
    long_fact = 'Запуск проекта назначен на 1 декабря 2026 года, ' + 'при условии предоплаты и согласования макета, ' * 6 + 'не раньше.'
    document(env['irina'], long_fact, shared='2')
    reply = say(env, 'Когда запуск проекта?').json()
    assert reply['answer']['status'] == 'grounded'
    assert reply['spoken'].startswith('Ответ длинный, он на экране.') and 'предоплаты' not in reply['spoken']


def test_validation_auth_and_extra_fields(env):
    assert say(env, '   ').status_code == 422
    assert say(env, 'Вопрос', confirm=True).status_code == 422
    env['irina'].post('/api/meet/logout')
    assert say(env, 'Когда запуск проекта?').status_code == 401


def test_transcribe_requires_login_and_local_asr(env, monkeypatch):
    wav = b'RIFF' + b'\0' * 64
    anonymous = env['irina'].post('/api/meet/logout')
    assert anonymous.status_code in (200, 204)
    assert env['irina'].post('/api/meet/voice/transcribe', files={'file': ('q.wav', wav)}).status_code == 401
    monkeypatch.setattr('providers.local_settings.uses_local_ai', lambda: False)
    response = env['petr'].post('/api/meet/voice/transcribe', files={'file': ('q.wav', wav)})
    assert response.status_code == 503 and response.json()['code'] == 'local_asr_required'
    monkeypatch.setattr('providers.local_settings.uses_local_ai', lambda: True)
    monkeypatch.setattr('services.local_speech.transcribe_local', lambda data, context='': '  Когда   запуск? ')
    response = env['petr'].post('/api/meet/voice/transcribe', files={'file': ('q.wav', wav)})
    assert response.status_code == 200 and response.json() == {'text': 'Когда запуск?'}
    assert response.headers['Cache-Control'] == 'no-store'
    assert env['petr'].post('/api/meet/voice/transcribe', files={'file': ('q.wav', b'')}).status_code == 422


@pytest.mark.parametrize('text,question', [
    ('Привет, Фокус', ''),
    ('Окей, Фокус, сколько просроченных задач?', 'сколько просроченных задач?'),
    ('ок фокус какой бюджет', 'какой бюджет'),
    ('О кей, Фокус. Когда запуск?', 'Когда запуск?'),
])
def test_wake_phrases(text, question):
    assert voice.wake_match(text) == (True, question)


@pytest.mark.parametrize('text', ['Фокус на сроках', 'Давайте сделаем фокус на браке', 'Привет, Пётр',
                                  'Покажи фокус', 'Окей, фокусная группа согласна', 'Привет, фото',
                                  'Фотик, сколько задач?', 'Мы говорили: привет, фокус-группа', ''])
def test_everyday_speech_does_not_wake(text):
    assert voice.wake_match(text) == (False, '')


def wake_post(client, data=b'RIFF' + b'\0' * 64, **headers):
    return client.post('/api/meet/voice/wake', files={'file': ('s.wav', data)}, headers=headers)


def test_wake_endpoint_is_local_only_and_returns_nothing_else(env, monkeypatch):
    monkeypatch.setattr('providers.local_settings.uses_local_ai', lambda: True)
    heard = {'text': 'Фокус на сроках, коллеги'}
    monkeypatch.setattr('services.local_speech.transcribe_local', lambda data, context='': heard['text'])
    assert wake_post(env['irina']).json()['code'] == 'wake_local_only'  # TestClient is not a loopback client
    monkeypatch.setattr(voice, 'LOOPBACK', voice.LOOPBACK | {'testclient'})
    before = len(audit_rows('voice.wake')) + len(audit_rows('voice.ask'))
    response = wake_post(env['irina'])
    assert response.status_code == 200 and response.json() == {'wake': False, 'question': ''}
    assert 'сроках' not in response.text and response.headers['Cache-Control'] == 'no-store'
    assert len(audit_rows('voice.wake')) + len(audit_rows('voice.ask')) == before, 'room speech is not logged'
    heard['text'] = 'Привет, Фокус, сколько просроченных задач?'
    assert wake_post(env['petr']).json() == {'wake': True, 'question': 'сколько просроченных задач?'}
    assert wake_post(env['irina'], **{'X-Forwarded-For': '203.0.113.5'}).status_code == 403
    assert wake_post(env['irina'], data=b'\0' * (voice.MAX_WAKE_AUDIO + 1)).status_code == 413
    monkeypatch.setattr('providers.local_settings.uses_local_ai', lambda: False)
    assert wake_post(env['irina']).json()['code'] == 'local_asr_required'
    env['irina'].post('/api/meet/logout')
    assert wake_post(env['irina']).status_code == 401


def test_heading_quote_gets_a_full_stop_before_the_source():
    result = {'status': 'grounded', 'claims': [{'text': 'Гайд по бренду (подрядчик: студия «Линия»)', 'sources': [
        {'title': 'Гайд по бренду', 'source_at': '2026-11-11T14:34:00+00:00'}]}]}
    assert voice.knowledge_phrase(result) == ('Гайд по бренду (подрядчик: студия «Линия»). '
                                              'Источник: «Гайд по бренду», от 11 ноября 2026.')


@pytest.mark.parametrize('text',['Какие у меня задачи на сегодня?','Когда следующая встреча?',
                                'Кто будет на планёрке?','Статус заказа PP-2611-00042',
                                'Сколько обращений по браку за неделю?'])
def test_voice_v2_read_tool_route_is_not_a_model_write(text):
    assert voice.route(text)=='assistant_read'
