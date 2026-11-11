from fastapi import FastAPI
from fastapi.testclient import TestClient
from types import SimpleNamespace
from evaluation.api import router
from evaluation.report import explain, report_html


def data():
    result = {'status': 'FAIL', 'failure_reasons': ['conversation_loop / turn_limit_exceeded'],
              'assertions': [], 'trace': {'stop_reason': 'turn_limit_exceeded',
              'transcript': [{'role': 'user', 'content': '<script>alert(1)</script>'},
                             {'role': 'assistant', 'content': 'Назовите телефон.'}]}}
    case = {'id': 'refused', 'title': 'Отказ', 'expected_behavior': 'Не сохранять обращение.', 'result': result}
    return {'id': 'run-1', 'agent_id': 'agent-1', 'config_snapshot': {}, 'scenarios': [case]}


def test_report_explains_loop_and_escapes_untrusted_transcript():
    run = data()
    explanation = explain(run['scenarios'][0], run['scenarios'][0]['result'])
    assert 'зациклился' in explanation['reasons'][0]
    html = report_html(run)
    assert 'Ожидалось:' in html and 'Фактический ответ:' in html
    assert '<script>alert' not in html and '&lt;script&gt;' in html


def test_report_is_inline_html_and_summary_keeps_friendly_reasons_without_trace():
    class Repository:
        def get(self, rid, details=False):
            return data() if rid == 'run-1' else None
    app = FastAPI()
    app.include_router(router(lambda: SimpleNamespace(repository=Repository())))
    client = TestClient(app)
    response = client.get('/api/evaluations/run-1/report')
    assert response.status_code == 200 and response.headers['content-type'].startswith('text/html')
    assert response.headers['content-disposition'] == 'inline'
    assert client.get('/api/evaluations/missing/report').status_code == 404
    result = client.get('/api/evaluations/run-1').json()['scenarios'][0]['result']
    assert 'explanation' in result and 'trace' not in result


def test_comparison_shows_all_case_outcomes_and_original_reason():
    previous = data()
    current = data()
    current['scenarios'][0]['result']['status'] = 'PASS'
    current['scenarios'][0]['result']['failure_reasons'] = []
    current['scenarios'][0]['result']['trace']['stop_reason'] = 'user_finished'
    html = report_html(current, previous)
    assert 'Что изменилось после исправления' in html
    assert '<td>FAIL</td><td>PASS</td>' in html
    assert 'зациклился' in html
