"""Real product HTTP/restart, synthetic roles and a scripted QA double; no live inference."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def server(db, port):
    from scripts.track3.start import configure
    from meetings import llm
    configure(Path(db))
    class Double:
        model = 'scripted-http-v2-not-live'
        def json(self, system, user, schema, predict=1500):
            if '48000' in user or '650000' in user:
                raise AssertionError('Forbidden source entered designer/model context')
            return {'excerpt_ids': []}
    llm.set_llm(Double())
    import app
    import uvicorn
    uvicorn.run(app.app, host='127.0.0.1', port=port)


def run():
    import httpx
    from scripts.track3.seed_fotoprint import seed
    events = []
    with tempfile.TemporaryDirectory(prefix='fotoprint-v2-http-') as temp:
        path = Path(temp) / 'demo.db'; ids = seed(str(path))
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        proc = None
        def start():
            child = subprocess.Popen([sys.executable, __file__, '--serve', str(path), '--port', str(port)], cwd=ROOT,
                                     env={**os.environ, 'MEETINGS_DEMO': '1', 'OLLAMA_BASE_URL': 'http://127.0.0.1:1'},
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if child.poll() is not None: raise RuntimeError('Product server exited')
                    try:
                        if httpx.get(base + '/meetings', trust_env=False, timeout=.2).status_code == 200: return child
                    except httpx.HTTPError: pass
                    time.sleep(.1)
                raise RuntimeError('Server startup timeout')
            except BaseException:
                child.terminate(); child.wait(timeout=10); raise
        def stop():
            nonlocal proc
            if proc:
                proc.terminate()
                try: proc.wait(timeout=10)
                except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=5)
                proc = None
        clients = {}
        try:
            proc = start()
            def request(login, method, route, expected=200, **kwargs):
                response = clients[login].request(method, '/api/meet' + route, **kwargs)
                events.append({'role': login, 'method': method, 'route': route, 'status': response.status_code})
                assert response.status_code == expected, (login, route, response.status_code, response.text)
                assert response.headers.get('X-Request-ID')
                return response.json()
            for login in ['director','prod_head','operator','designer','admin','auditor']:
                clients[login] = httpx.Client(base_url=base, trust_env=False, timeout=15)
                request(login, 'POST', '/login', json={'login': login, 'password': login + '-demo'})
                assert request(login, 'GET', '/me')['level']
            roles = request('director', 'GET', '/demo-profiles')['users']; assert len(roles) == 16
            did = ids['documents']['v2_budget']; mid = ids['meetings']['delay']
            for login in ['designer','admin','auditor','prod_head']:
                request(login, 'GET', f'/documents/{did}/download', expected=404)
            for login in ['admin','auditor','designer']:
                request(login, 'GET', f'/meetings/{mid}', expected=404)
            request('admin', 'GET', '/admin/users')
            overview = request('director', 'GET', '/overview?as_of=2026-11-11T12:00:00%2B00:00')
            metrics = {m['key']:m['value'] for m in overview['metrics']}
            assert metrics['on_time_orders'] == 97.6 and metrics['defect_rate'] == 1.8
            assert metrics['overdue_tasks'] == 3
            assert request('designer', 'POST', '/qa', json={'question':'Какой бюджет акции Premium?'})['status'] == 'insufficient_data'
            secret = request('director', 'POST', '/qa', json={'question':'Каков фонд оплаты труда?'})
            assert secret['status'] == 'insufficient_data' and 'закрыт для ассистента' in secret['answer']
            tasks = request('operator', 'GET', '/tasks')['tasks']; task = next(t for t in tasks if t['status'] == 'open')
            request('operator','POST','/crm/preview',expected=403,json={'action':'task.create','object_id':task['id']})
            crm = request('prod_head','POST','/crm/preview',json={'action':'task.create','object_id':task['id']})
            request('prod_head','POST',f"/confirmations/{crm['confirmation_id']}/cancel")
            request('prod_head','POST','/crm/confirm',expected=409,json={'confirmation_id':crm['confirmation_id'],'idempotency_key':'cancel-crm-http'})
            crm = request('prod_head','POST','/crm/preview',json={'action':'task.create','object_id':task['id']})
            crm_token = {'confirmation_id':crm['confirmation_id'],'idempotency_key':'send-crm-http'}
            crm_result = request('prod_head','POST','/crm/confirm',json=crm_token)
            assert crm_result['status']=='sent' and crm_result['mode']=='mock'
            assert request('prod_head','POST','/crm/confirm',json=crm_token)['already_confirmed']
            request('admin','POST','/integrations/check')
            route = f"/tasks/{task['id']}"
            cancelled = request('operator', 'POST', route + '/preview', json={'changes':{'status':'done'}})['confirmation_id']
            request('operator', 'POST', f'/confirmations/{cancelled}/cancel')
            request('operator', 'POST', route + '/confirm', expected=409,
                    json={'confirmation_id':cancelled,'idempotency_key':'cancel-v2'})
            cid = request('operator', 'POST', route + '/preview', json={'changes':{'status':'in_progress'}})['confirmation_id']
            payload = {'confirmation_id':cid, 'idempotency_key':'single-v2-task'}
            request('operator', 'POST', route + '/confirm', json=payload)
            assert request('operator', 'POST', route + '/confirm', json=payload)['already_confirmed']
            assert any(e['result']=='denied' for e in request('auditor','GET','/audit')['events'])
            stop(); proc = start()
            assert request('operator', 'GET', '/me')['user']['login'] == 'operator'
            assert request('prod_head','GET',f"/crm/tasks/{task['id']}")['outbox']['external_ref']==crm_result['external_ref']
            assert next(t for t in request('operator', 'GET', '/tasks')['tasks'] if t['id']==task['id'])['status']=='in_progress'
            request('designer', 'GET', f'/meetings/{mid}', expected=404)
            return {'status':'passed', 'model':'scripted double; live quality not measured', 'roles':6,
                    'requests':events, 'kpi_before_mutation':metrics, 'restart':'passed'}
        finally:
            stop()
            for client in clients.values(): client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve'); parser.add_argument('--port', type=int); parser.add_argument('--output')
    args = parser.parse_args()
    if args.serve: return server(args.serve, args.port)
    if not args.output: parser.error('--output required')
    started = time.perf_counter()
    try: result = run(); code = 0
    except Exception as error: result = {'status':'failed','error':type(error).__name__, 'detail':str(error)}; code = 1
    result['elapsed_seconds'] = time.perf_counter() - started
    result['working_tree_dirty'] = bool(subprocess.check_output(['git','status','--porcelain'], cwd=ROOT, text=True).strip())
    result['commit'] = subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip()
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='requests'}, ensure_ascii=False))
    return code

if __name__ == '__main__': raise SystemExit(main())
