"""Run when the core branch is installed or selected by the documented namespace overlay."""
import importlib.util

import pytest

from meetings import store
from test_track3_knowledge_support import env, document, meeting, audit_rows

pytestmark = pytest.mark.skipif(importlib.util.find_spec('meetings.feedback') is None,
                               reason='Claude core/feedback integration required')


@pytest.mark.parametrize('scoped', [False, True], ids=['global', 'meeting'])
def test_feedback_rechecks_every_document_after_acl_revocation(env, scoped):
    doc_id, _ = document(env['irina'], 'Запуск проекта назначен на 1 декабря 2026 года.', shared='2')
    payload = {'question': 'Когда запуск проекта?'}
    if scoped:
        payload['meeting_id'] = meeting(env['irina'], (doc_id,), shared=(2,))
    answer = env['petr'].post('/api/meet/qa', json=payload).json()
    assert answer['status'] == 'grounded'
    feedback = {'target_type': 'qa_answer', 'target_id': answer['answer_id'], 'rating': 'useful'}
    assert env['petr'].post('/api/meet/feedback', json=feedback).status_code == 200
    with store.db() as connection:
        connection.execute('DELETE FROM document_access WHERE document_id=? AND user_id=2', (doc_id,))
    assert env['petr'].get('/api/meet/qa/' + str(answer['answer_id'])).status_code == 404
    assert env['petr'].post('/api/meet/feedback', json=feedback).status_code == 404


def test_core_registration_correlation_and_structured_audit(env):
    from fastapi import FastAPI
    from meetings.api import install
    installed = FastAPI()
    install(installed)
    assert {'/api/meet/qa', '/api/meet/overview', '/api/meet/sources/{kind}/{source_id}'} <= set(installed.openapi()['paths'])
    request_id = 'track3-integration-checked'
    response = env['irina'].post('/api/meet/qa', json={'question': 'Неизвестная выручка'}, headers={'X-Request-ID': request_id})
    assert response.status_code == 200 and response.headers['X-Request-ID'] == request_id
    assert audit_rows('qa.generate')[-1]['request_id'] == request_id
