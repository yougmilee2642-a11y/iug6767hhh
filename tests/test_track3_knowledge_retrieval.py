import pytest

from meetings import store
from meetings.knowledge import service
from test_track3_knowledge_support import env, document


@pytest.mark.parametrize('question,text', [
    ('Подскажи, пожалуйста, когда запланирован запуск проекта?', 'Запуск проекта назначен на 1 декабря 2026 года.'),
    ('Какова сумма предоплаты?', 'Предоплата составляет 30 процентов стоимости заказа.'),
    ('Можешь рассказать о сроках сдачи макетов?', 'Срок сдачи макетов — 20 ноября 2026 года.'),
    ('Какие есть риски интеграции по платёжному шлюзу?', 'Задержка интеграции с платёжным шлюзом создаёт риск запуска.'),
    ('Когда состоится релиз проекта?', 'Запуск проекта назначен на 1 декабря 2026 года.'),
], ids=['polite-question', 'question-form', 'case-endings', 'gateway-cases', 'release-synonym'])
def test_natural_question_wording_finds_the_same_grounded_fact(env, question, text):
    document(env['irina'], text)
    response = env['irina'].post('/api/meet/qa', json={'question': question})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['status'] == 'grounded' and result['answer'] == text
    assert result['sources'][0]['quote'] == text


@pytest.mark.parametrize('ineligible', ['undated', 'oversized'])
def test_ineligible_fragments_cannot_displace_usable_evidence_from_candidate_limit(env, ineligible):
    fact = 'Запуск проекта назначен на 1 декабря 2026 года.'
    for index in range(service.MAX_CANDIDATES):
        doc_id, fid = document(env['irina'], fact)
        with store.db() as connection:
            if ineligible == 'undated':
                connection.execute("UPDATE documents SET created_at='unknown' WHERE id=?", (doc_id,))
            else:
                connection.execute('UPDATE fragments SET text=? WHERE id=?', (fact + ' filler' * 2000, int(fid[1:])))
    _, usable_fid = document(env['irina'], fact)
    response = env['irina'].post('/api/meet/qa', json={'question': 'Когда запуск проекта?'})
    assert response.status_code == 200
    assert response.json()['status'] == 'grounded'
    assert [source['id'] for source in response.json()['sources']] == [usable_fid]
    assert len(env['model'].calls[-1][1]['untrusted_documents']) == 1


def test_politeness_does_not_make_an_unrelated_question_relevant(env):
    document(env['irina'], 'Бюджет проекта составляет 4,2 млн рублей.')
    response = env['irina'].post('/api/meet/qa', json={'question': 'Подскажите, пожалуйста, какая температура в цехе?'})
    assert response.json()['status'] == 'insufficient_data'
    assert env['model'].calls == []


@pytest.mark.parametrize('identifier,expected', [('offered', 'grounded'), ('F999:E0', 'insufficient_data'),
                                             ('F1:E999', 'insufficient_data'), (None, 'insufficient_data')])
def test_model_can_select_only_offered_excerpts_and_cannot_add_display_text(env, identifier, expected):
    fact = 'Запуск проекта назначен на 1 декабря 2026 года.'
    _, fid = document(env['irina'], fact)
    if identifier == 'offered':
        identifier = fid + ':E0'
    env['model'].reply = {'claims': [{'excerpt_id': identifier, 'text': 'Непроверенный дополнительный вывод.'}]}
    response = env['irina'].post('/api/meet/qa', json={'question': 'Когда запуск проекта?'})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['status'] == expected
    assert 'дополнительный' not in result['answer']
    if expected == 'grounded':
        assert result['answer'] == fact and result['sources'][0]['quote'] == fact


def test_flat_selection_uses_original_abbreviations_not_model_wording(env):
    fact = 'Оплата ограничена суммой 50 тыс. рублей на операцию.'
    _, fid = document(env['irina'], fact)
    env['model'].reply = {'excerpt_ids': [fid + ':E0'], 'answer': 'Оплата ограничена суммой 50 тысяч рублей.'}
    result = env['irina'].post('/api/meet/qa', json={'question': 'Какой лимит оплаты?'}).json()
    assert result['status'] == 'grounded' and result['answer'] == fact


@pytest.mark.parametrize('text,cut,question', [
    ('Лимит оплаты — 50 тыс. рублей на операцию при предоплате.', 'Лимит оплаты — 50 тыс.', 'Какой лимит оплаты?'),
    ('Только при предоплате\nОтгрузка состоится 20 ноября.', 'Отгрузка состоится 20 ноября.', 'Когда отгрузка?'),
])
def test_excerpt_boundaries_cannot_drop_currency_or_newline_condition(env, text, cut, question):
    _, fid = document(env['irina'], text)
    env['model'].reply = {'claims': [{'fragment_id': fid, 'quote': cut, 'text': cut}]}
    result = env['irina'].post('/api/meet/qa', json={'question': question}).json()
    # A word-aligned partial quote is widened to the whole stored sentence (PR #8), so the currency or the
    # condition on the line above is shown with it; the cut itself is never the answer.
    assert result['status'] == 'grounded'
    assert result['answer'] == text and result['sources'][0]['quote'] == text
    choices = env['model'].calls[-1][1]['untrusted_documents'][0]['excerpts']
    assert cut not in [choice['text'] for choice in choices]


def test_invalid_selection_envelope_is_a_model_error(env):
    document(env['irina'], 'Запуск проекта назначен на 1 декабря 2026 года.')
    env['model'].reply = {'excerpt_ids': 'not-an-array'}
    response = env['irina'].post('/api/meet/qa', json={'question': 'Когда запуск проекта?'})
    assert response.status_code == 503 and response.json()['code'] == 'model_invalid_reply'
