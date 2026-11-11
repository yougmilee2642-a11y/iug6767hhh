"""Opt-in full-app HTTP smoke with real Ollama and a restart of the server process.

Run in a locally combined core + knowledge checkout with TRACK3_HTTP_SMOKE=1.
Uses temporary databases, loopback only, and never contacts external integrations.
"""
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
import time
from contextlib import contextmanager

import httpx
import pytest

ROOT = Path(os.getenv('TRACK3_HTTP_ROOT') or Path(__file__).resolve().parents[1]).resolve()
pytestmark = pytest.mark.skipif(
    os.getenv('TRACK3_HTTP_SMOKE') != '1' or not (ROOT / 'meetings' / 'migrations').is_dir(),
    reason='explicit HTTP/Ollama opt-in and combined core checkout required')

BOOTSTRAP = '''
import os, storage, uvicorn
from pathlib import Path
storage.DB_PATH = Path(os.environ['TRACK3_SMOKE_BUSINESS_DB'])
uvicorn.run('app:app', host='127.0.0.1', port=int(os.environ['TRACK3_SMOKE_PORT']), log_level='warning')
'''


@contextmanager
def running_server(environment, log_path):
    with log_path.open('wb') as output:
        process = subprocess.Popen([sys.executable, '-c', BOOTSTRAP], cwd=ROOT, env=environment,
            stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            base = 'http://127.0.0.1:' + environment['TRACK3_SMOKE_PORT']
            deadline = time.monotonic() + 25
            with httpx.Client(trust_env=False, timeout=1) as probe:
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        pytest.fail('Server stopped during startup: ' + log_path.read_text(encoding='utf-8', errors='replace')[-2000:])
                    try:
                        if probe.get(base + '/openapi.json').status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.05)
                else:
                    pytest.fail('Temporary loopback server did not become ready')
            yield base
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def test_real_http_restart_acl_and_overview(tmp_path):
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    database = tmp_path / 'meetings.db'
    environment = {**os.environ, 'MEETINGS_DB_PATH': str(database), 'MEETINGS_SECRET': secrets.token_hex(32),
        'MEETINGS_DEMO_USERS': 'true', 'MEETINGS_TIMEOUT': '60', 'CALLWISE_LOCAL_ONLY': 'false',
        'AI_PROVIDER': 'groq', 'TELEGRAM_ENABLED': 'false', 'CALLWISE_OWNER_PASSWORD': '',
        'CALLWISE_CLOUD_INTEGRATIONS_ENABLED': 'false', 'TRACK3_SMOKE_PORT': str(port),
        'TRACK3_SMOKE_BUSINESS_DB': str(tmp_path / 'business.db')}
    with httpx.Client(trust_env=False, timeout=75) as irina, httpx.Client(trust_env=False, timeout=75) as petr:
        with running_server(environment, tmp_path / 'first-start.log') as base:
            assert irina.get(base + '/api/meet/overview').status_code == 401
            for client, login in ((irina, 'irina'), (petr, 'petr')):
                response = client.post(base + '/api/meet/login', json={'login': login, 'password': login + '-demo'})
                assert response.status_code == 200, response.text
            fact = 'Запуск проекта назначен на 1 декабря 2026 года.'
            upload = irina.post(base + '/api/meet/documents', files={'file': ('plan.txt', fact.encode())},
                                data={'title': 'HTTP-план запуска', 'share_with': '2'})
            assert upload.status_code == 200, upload.text
            doc_id = upload.json()['document']['id']
            response = petr.post(base + '/api/meet/qa', json={'question': 'Когда запуск проекта?'},
                                 headers={'X-Request-ID': 'track3-real-http-smoke'})
            assert response.status_code == 200, response.text
            answer = response.json()
            assert answer['status'] == 'grounded' and answer['answer'] == fact
            assert response.headers['X-Request-ID'] == 'track3-real-http-smoke'
            assert response.headers['Cache-Control'] == 'no-store'
            answer_path = '/api/meet/qa/' + str(answer['answer_id'])
            assert petr.get(base + answer_path).json() == answer
            assert irina.get(base + answer_path).status_code == 404

        # Same DB and session secret; no login and no model call are needed to reopen.
        with running_server(environment, tmp_path / 'second-start.log') as base:
            assert petr.get(base + answer_path).json() == answer
            with sqlite3.connect(database) as connection:
                assert connection.execute('PRAGMA user_version').fetchone()[0] >= 8
                event = connection.execute("SELECT request_id,model FROM audit WHERE action='qa.generate' AND result='grounded'").fetchone()
                assert event[0] == 'track3-real-http-smoke' and event[1] == answer['model']
                # Isolated synthetic production data: director=10%, reader=100%.
                for source_id, scope, completed, on_time in [('http-private', 'private', 9, 0), ('http-shared', 'shared', 1, 1)]:
                    cursor = connection.execute('INSERT INTO production_metrics(source_id,owner_id,scope,period_start,period_end,as_of,'
                        'completed_orders,on_time_orders,produced_units,defective_units,available_capacity,occupied_capacity,created_at) '
                        'VALUES (?,1,?,?,?,?,?,?,1,0,1,1,?)',
                        (source_id, scope, '2026-11-01T00:00:00Z', '2026-12-01T00:00:00Z',
                         '2026-11-11T09:00:00Z', completed, on_time, '2026-11-11T09:00:00Z'))
                    if source_id == 'http-shared':
                        connection.execute('INSERT INTO production_metric_access(metric_id,user_id) VALUES (?,2)', (cursor.lastrowid,))
            for client, expected in ((irina, 10), (petr, 100)):
                response = client.get(base + '/api/meet/overview', params={'as_of': '2026-11-11T10:00:00Z'})
                assert response.status_code == 200, response.text
                metric = next(m for m in response.json()['metrics'] if m['key'] == 'on_time_orders')
                assert metric['value'] == expected
                assert client.get(base + '/api/meet/sources/metric/' + metric['source']['id']).status_code == 200
            assert petr.get(base + '/api/meet/sources/metric/http-private').status_code == 404
            with sqlite3.connect(database) as connection:
                connection.execute('DELETE FROM document_access WHERE document_id=? AND user_id=2', (doc_id,))
            assert petr.get(base + answer_path).status_code == 404
            assert petr.get(base + '/api/meet/fragments/' + answer['sources'][0]['id']).status_code == 404
            assert petr.post(base + '/api/meet/feedback', json={'target_type': 'qa_answer',
                'target_id': answer['answer_id'], 'rating': 'useful'}).status_code == 404
            refused = petr.post(base + '/api/meet/qa', json={'question': 'Когда запуск проекта?'}).json()
            assert refused['status'] == 'insufficient_data' and refused['model'] is None
