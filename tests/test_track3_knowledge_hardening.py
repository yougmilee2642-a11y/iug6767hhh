import json
import sqlite3

import pytest

from meetings import store
from test_track3_knowledge_support import env, document

FACT = 'Запуск проекта назначен на 1 декабря 2026 года.'


def generated(env):
    document(env['irina'], FACT)
    response = env['irina'].post('/api/meet/qa', json={'question': 'Когда запуск проекта?'})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize('column,value', [
    ('claims', '[{"text":"Запуск проекта назначен на 1 декабря 2026 года.","sources":[]}]'),
    ('claims', '{}'), ('claims', 'null'), ('claims', '{broken'),
    ('claims', '[{"text":42,"sources":[]}]'), ('claims', '[]'),
    ('source_ids', '{broken'), ('source_ids', '{}'), ('source_ids', '["F99999999999999999999999999999"]'),
])
def test_corrupt_saved_evidence_never_becomes_an_answer_or_500(env, column, value):
    result = generated(env)
    with store.db() as connection:
        # Column comes only from this fixed parametrization.
        connection.execute(f'UPDATE qa_answers SET {column}=? WHERE id=?', (value, result['answer_id']))
    response = env['irina'].get('/api/meet/qa/' + str(result['answer_id']))
    assert response.status_code == 409, response.text
    assert response.json()['code'] == 'stale_sources'
    assert FACT not in response.text


def test_saved_quote_is_invalidated_when_surrounding_context_changes(env):
    result = generated(env)
    fid = result['sources'][0]['id']
    with store.db() as connection:
        connection.execute('UPDATE fragments SET text=? WHERE id=?',
                           ('Следующее утверждение больше не действительно. ' + FACT, int(fid[1:])))
    response = env['irina'].get('/api/meet/qa/' + str(result['answer_id']))
    assert response.status_code == 409
    assert FACT not in response.text


@pytest.mark.parametrize('invalid', [{'question': 'x' * 2001}, {'question': 42}, {'question': 'Запуск?', 'meeting_id': 1.5}])
def test_invalid_input_has_safe_contract_error_and_correlation_id(env, invalid):
    response = env['irina'].post('/api/meet/qa', json=invalid)
    assert response.status_code == 422
    assert response.json()['code'] == 'invalid_request'
    assert isinstance(response.json()['detail'], str)
    assert response.headers['X-Request-ID']
    assert 'x' * 100 not in response.text


def test_audit_failure_does_not_turn_model_timeout_into_unhandled_error(env, monkeypatch):
    from providers.local_settings import LocalAIError
    document(env['irina'], FACT)
    env['model'].reply = LocalAIError('timeout')
    def unavailable(*args, **kwargs):
        raise sqlite3.OperationalError('sensitive backend detail')
    monkeypatch.setattr(store, 'audit', unavailable)
    response = env['irina'].post('/api/meet/qa', json={'question': 'Когда запуск проекта?'})
    assert response.status_code == 503 and response.json()['code'] == 'model_timeout'
    assert 'sensitive' not in response.text


def test_audit_failure_is_explicit_when_operation_itself_succeeded(env, monkeypatch):
    def unavailable(*args, **kwargs):
        raise sqlite3.OperationalError('sensitive backend detail')
    monkeypatch.setattr(store, 'audit', unavailable)
    response = env['irina'].post('/api/meet/qa', json={'question': 'Неизвестная выручка'})
    assert response.status_code == 503 and response.json()['code'] == 'audit_unavailable'


def test_persisted_proof_does_not_leak_internal_metadata_into_response(env):
    result = generated(env)
    with store.db() as connection:
        claims = json.loads(connection.execute('SELECT claims FROM qa_answers WHERE id=?', (result['answer_id'],)).fetchone()[0])
    assert claims[0]['_context_sha256']
    assert '_context_sha256' not in json.dumps(result)
    assert env['irina'].get('/api/meet/qa/' + str(result['answer_id'])).json() == result


def test_pdf_whitespace_and_adjacent_sentences_preserve_original_quote(env):
    text = 'Дата\u00a0запуска: 1 декабря 2026 года. Дата утверждена комитетом 21 октября 2026 года.'
    _, fid = document(env['irina'], text)
    proposed = text.replace('\u00a0', ' ')
    env['model'].reply = {'claims': [{'text': proposed, 'quote': proposed, 'fragment_id': fid}]}
    response = env['irina'].post('/api/meet/qa', json={'question': 'Когда запуск?'})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['status'] == 'grounded' and result['answer'] == text
    assert result['sources'][0]['quote'] == text
    assert env['irina'].get('/api/meet/qa/' + str(result['answer_id'])).json() == result


def test_whitespace_matching_cannot_drop_negation_or_insert_sentences(env):
    text = 'Запуск проекта не назначен на 1 декабря. Дата пока неизвестна.'
    _, fid = document(env['irina'], text)
    invented = text.replace('не ', '')
    env['model'].reply = {'claims': [{'text': invented, 'quote': invented, 'fragment_id': fid}]}
    result = env['irina'].post('/api/meet/qa', json={'question': 'Когда запуск проекта?'}).json()
    assert result['status'] == 'insufficient_data'


@pytest.mark.parametrize('other_project', ['Орбита', 'Вега Плюс'])
def test_named_project_in_question_cannot_be_answered_from_another_project(env, other_project):
    document(env['irina'], f'Бюджет проекта «{other_project}» составляет 4,2 млн рублей.', title='Бюджет')
    response = env['irina'].post('/api/meet/qa', json={'question': 'Какой бюджет проекта «Вега»?'})
    assert response.status_code == 200
    assert response.json()['status'] == 'insufficient_data'
    assert env['model'].calls == []


def test_excerpt_cannot_switch_to_other_project_mentioned_in_same_document(env):
    document(env['irina'], 'Бюджет проекта «Орбита» составляет 4,2 млн рублей.', title='Бюджет проекта «Вега»')
    result = env['irina'].post('/api/meet/qa', json={'question': 'Какой бюджет проекта «Вега»?'}).json()
    assert result['status'] == 'insufficient_data'


def test_named_project_can_be_grounded_by_document_title(env):
    fact = 'Бюджет проекта составляет 4,2 млн рублей.'
    document(env['irina'], fact, title='Бюджет проекта «Вега»')
    result = env['irina'].post('/api/meet/qa', json={'question': 'Какой бюджет проекта «Вега»?'}).json()
    assert result['status'] == 'grounded' and result['answer'] == fact
