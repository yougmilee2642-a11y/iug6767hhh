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
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def model_failure_code(error):
    # Windows may time out before a closed loopback port reports connection
    # refusal. Both are explicit 503 provider failures, never successful inference.
    assert isinstance(error, dict) and error.get('code') in ('model_unavailable', 'model_timeout'), error
    assert isinstance(error.get('detail'), str) and error['detail'].strip(), error
    return error['code']


def server(db, port, unavailable=False):
    from scripts.track3.start import configure
    from meetings import llm
    configure(Path(db))
    class Double:
        model = 'scripted-http-v2-not-live'
        def json(self, system, user, schema, predict=1500):
            if '48000' in user or '650000' in user:
                raise AssertionError('Forbidden source entered designer/model context')
            return {'excerpt_ids': []}
    if not unavailable:
        llm.set_llm(Double())
    import app
    import uvicorn
    uvicorn.run(app.app, host='127.0.0.1', port=port)


def run(unavailable=False):
    import httpx
    from scripts.track3.seed_fotoprint import seed
    events = []
    observed_model_errors = {}
    with tempfile.TemporaryDirectory(prefix='fotoprint-v2-http-') as temp:
        path = Path(temp) / 'demo.db'; ids = seed(str(path))
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        proc = None
        def start():
            command = [sys.executable, __file__, '--serve', str(path), '--port', str(port)]
            if unavailable:
                command.append('--unavailable')
            server_log = tempfile.TemporaryFile(mode='w+', encoding='utf-8', errors='replace')
            child = subprocess.Popen(command, cwd=ROOT,
                                     env={**os.environ, 'MEETINGS_DEMO': '1', 'OLLAMA_BASE_URL': 'http://127.0.0.1:1',
                                          'OLLAMA_API_KEY': '', 'MEETINGS_TIMEOUT': '1'},
                                     stdout=server_log, stderr=subprocess.STDOUT)
            child._track3_log = server_log
            try:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if child.poll() is not None:
                        server_log.seek(0)
                        raise RuntimeError('Product server exited: ' + '\n'.join(server_log.read().splitlines()[-15:]))
                    try:
                        if httpx.get(base + '/meetings', trust_env=False, timeout=.2).status_code == 200: return child
                    except httpx.HTTPError: pass
                    time.sleep(.1)
                raise RuntimeError('Server startup timeout')
            except BaseException:
                child.terminate(); child.wait(timeout=10); server_log.close(); raise
        def stop():
            nonlocal proc
            if proc:
                proc.terminate()
                try: proc.wait(timeout=10)
                except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=5)
                proc._track3_log.close()
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
            for login in ['director','prod_head','mod_lead','operator','designer','admin','auditor']:
                clients[login] = httpx.Client(base_url=base, trust_env=False, timeout=15)
                request(login, 'POST', '/login', json={'login': login, 'password': login + '-demo'})
                assert request(login, 'GET', '/me')['level']
            briefing_meeting = request('director','POST','/meetings',json={'title':'HTTP briefing source','scheduled_at':'2026-11-11T09:00:00+03:00'})['meeting']
            assert request('director','GET',f"/sources/meeting/{briefing_meeting['id']}")['data']['meeting']['id']==briefing_meeting['id']
            request('operator','GET',f"/sources/meeting/{briefing_meeting['id']}",expected=404)
            for login in ['director','prod_head','operator','designer']:
                briefing = request(login,'GET','/briefing?date=2026-11-11')
                assert briefing['timezone']=='Europe/Minsk' and briefing['model'] is None
                assert all(c['sources'] for c in briefing['claims'])
            for login in ['admin','auditor']:
                request(login,'GET','/briefing',expected=403)
            voice_briefing = request('operator','POST','/voice/ask',json={'text':'Брифинг дня'})
            assert voice_briefing['route']=='briefing' and voice_briefing['answer']['model'] is None
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
            found = request('director','GET','/search?q=%D0%BA%D0%B0%D1%80%D1%82%D0%BE%D0%BD')['results']
            assert found and all(row.get('source_at') for row in found)
            assert all(row['document_id'] != did for row in request('designer','GET','/search?q=%D0%B1%D1%8E%D0%B4%D0%B6%D0%B5%D1%82')['results'])
            assert request('designer', 'POST', '/qa', json={'question':'Какой бюджет акции Premium?'})['status'] == 'insufficient_data'
            secret = request('director', 'POST', '/qa', json={'question':'Каков фонд оплаты труда?'})
            assert secret['status'] == 'insufficient_data' and 'закрыт для ассистента' in secret['answer']
            # Exercise interchange through product HTTP without any external service.
            from meetings.calendar import ics
            start_at = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0) + timedelta(days=7)
            calendar_token = request('director','POST','/calendar/preview',json={
                'meeting_id':mid,'participant_ids':[ids['users']['operator']],
                'start_at':start_at.isoformat(),'duration_minutes':30})
            scheduled = request('director','POST','/calendar/confirm',json={
                'confirmation_id':calendar_token['confirmation_id'],'idempotency_key':'http-calendar-confirm-001'})
            exported = clients['director'].get('/api/meet/calendar/export.ics')
            assert exported.status_code == 200 and len(ics.parse(exported.content)) >= 1
            invitation = clients['director'].get(f"/api/meet/calendar/outbox/{scheduled['invitations'][0]['id']}/download.eml")
            assert invitation.status_code == 200 and b'invitation.ics' in invitation.content
            import_file = ics.calendar([{'uid':'http-import','created_at':start_at.isoformat(),
                'start_at':(start_at+timedelta(hours=3)).isoformat(),
                'end_at':(start_at+timedelta(hours=4)).isoformat(),'title':'Не сохранять название'}])
            imported = request('operator','POST','/calendar/import/preview',files={'file':('busy.ics',import_file,'text/calendar')})
            imported_result = request('operator','POST','/calendar/import/confirm',json={
                'confirmation_id':imported['confirmation_id'],'idempotency_key':'http-calendar-import-001'})
            assert imported_result['interval_count']==1
            subscription = request('director','POST','/calendar/subscriptions')
            # Do not put the bearer itself in reports; access logs redact the path.
            feed = clients['designer'].get(subscription['path'])
            assert feed.status_code==200 and 'SUMMARY:Занято' in feed.text
            smart = request('director','POST','/calendar/slots',json={
                'participant_ids':[ids['users']['prod_head']], 'optional_participant_ids':[ids['users']['operator']],
                'range_start':start_at.replace(hour=0).isoformat(),'range_end':start_at.replace(hour=23).isoformat(),
                'duration_minutes':30,'smart':True})
            assert smart['smart'] and smart['generated_at'] and len(smart['slots'])<=3
            if smart['slots']:
                candidate = request('director','POST','/calendar/preview',json={
                    'meeting_id':mid,'participant_ids':[ids['users']['prod_head']],
                    'optional_participant_ids':[ids['users']['operator']],
                    'start_at':smart['slots'][0]['start_at'],'duration_minutes':30,'smart':True})
                request('director','POST',f"/confirmations/{candidate['confirmation_id']}/cancel")
            if unavailable:
                # Exercise the real provider against an explicitly closed loopback port.
                # No Ollama process, gateway or scripted reply participates in this mode.
                before = request('director', 'GET', f'/meetings/{mid}')
                for route in [f'/meetings/{mid}/prepare', f'/meetings/{mid}/protocol/draft']:
                    error = request('director', 'POST', route, expected=503)
                    observed_model_errors[route] = model_failure_code(error)
                error = request('director', 'POST', '/qa', expected=503,
                                json={'question': 'Какие условия поставки картона 0,9 мм?'})
                observed_model_errors['/qa'] = model_failure_code(error)
                after = request('director', 'GET', f'/meetings/{mid}')
                assert before['utterances'] == after['utterances']
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
            assistant_result=request('prod_head','POST','/assistant/ask',json={'text':'Что просрочено?'})
            assert assistant_result['status']=='grounded' and assistant_result['claims']
            source=assistant_result['sources'][0]
            request('prod_head','GET','/sources/assistant/'+source['id'])
            request('designer','GET','/assistant/conversations/'+assistant_result['conversation_id'],expected=404)
            action_meeting=request('prod_head','POST','/meetings',json={'title':'HTTP assistant manual task'})['meeting']['id']
            proposed=request('prod_head','POST','/assistant/ask',json={'text':'Поставь задачу проверить картон','meeting_id':action_meeting})
            assert proposed['status']=='action_proposed'
            draft={'kind':'task','meeting_id':action_meeting,'text':'Ручная проверка картона HTTP','assignee_user_id':ids['users']['operator']}
            action_token=request('prod_head','POST','/assistant/actions/preview',json=draft)['confirmation_id']
            action_confirm={'confirmation_id':action_token,'idempotency_key':'http-assistant-manual-task'}
            manual=request('prod_head','POST','/assistant/actions/confirm',json=action_confirm)
            assert request('prod_head','POST','/assistant/actions/confirm',json=action_confirm)['already_confirmed']
            request('prod_head','POST',f"/tasks/{manual['task_id']}/comments",json={'text':'Проверен ручной источник.'})
            assert request('prod_head','GET',f"/tasks/{manual['task_id']}/comments")['comments']
            assert clients['prod_head'].get(f'/api/meet/meetings/{action_meeting}/protocol/export?format=html').status_code==200
            request('admin','GET','/retention')
            request('prod_head','GET','/retention',expected=403)
            request('admin','GET','/integrations/employees')
            request('operator','GET','/notifications')
            doc = request('director','POST','/documents',files={'file':('editions.txt','Учебный график версий: поставка картона 20 ноября.'.encode())},
                          data={'title':'HTTP проверка истории версий'})['document']
            version_route = f"/documents/{doc['id']}"
            upload = {'file':('edition2.txt','Учебный график версий: поставка картона 25 ноября.'.encode())}
            draft = request('director','POST',version_route+'/versions/preview',files=upload)
            request('director','POST',f"/confirmations/{draft['confirmation_id']}/cancel")
            request('director','POST',version_route+'/versions/confirm',expected=409,
                    json={'confirmation_id':draft['confirmation_id'],'idempotency_key':'http-version-cancel'})
            draft = request('director','POST',version_route+'/versions/preview',files=upload)
            version_token = {'confirmation_id':draft['confirmation_id'],'idempotency_key':'http-version-confirm'}
            edition = request('director','POST',version_route+'/versions/confirm',json=version_token)['document']
            assert request('director','POST',version_route+'/versions/confirm',json=version_token)['already_confirmed']
            assert request('director','GET',f"/documents/{edition['id']}/summary")['claims'][0]['text'].endswith('25 ноября.')
            assert request('director','GET',version_route+f"/compare/{edition['id']}")['changes']
            assert {row['document_id'] for row in request('director','GET','/search',params={'q':'Учебный график версий'})['results']}=={edition['id']}
            request('admin','GET',version_route+'/summary',expected=404)
            stop(); proc = start()
            assert request('operator', 'GET', '/me')['user']['login'] == 'operator'
            assert request('prod_head','GET',f"/crm/tasks/{task['id']}")['outbox']['external_ref']==crm_result['external_ref']
            assert clients['designer'].get(subscription['path']).status_code==200
            request('director','DELETE',f"/calendar/subscriptions/{subscription['id']}")
            assert clients['designer'].get(subscription['path']).status_code==404
            assert next(t for t in request('operator', 'GET', '/tasks')['tasks'] if t['id']==task['id'])['status']=='in_progress'
            request('designer', 'GET', f'/meetings/{mid}', expected=404)
            assert len(request('director','GET',version_route+'/versions')['versions'])==2
            assert request('director','POST',version_route+'/versions/confirm',json=version_token)['document']['id']==edition['id']
            return {'status':'passed', 'model':('unavailable loopback; no live inference' if unavailable else
                                               'scripted double; live quality not measured'), 'roles':len(clients),
                    'model_failure_path': 'passed' if unavailable else 'not_run',
                    'observed_model_errors':observed_model_errors,
                    'requests':events, 'kpi_before_mutation':metrics, 'restart':'passed', 'calendar_interchange':'passed',
                    'document_versions':'passed', 'daily_briefing':'passed',
                    'smart_calendar':{'slot_count':len(smart['slots']),'warnings':smart['warnings']}}
        finally:
            stop()
            for client in clients.values(): client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve'); parser.add_argument('--port', type=int); parser.add_argument('--output')
    parser.add_argument('--unavailable', action='store_true', help='Check real provider 503 at closed loopback port 1; never contact a model')
    args = parser.parse_args()
    if args.serve: return server(args.serve, args.port, args.unavailable)
    if not args.output: parser.error('--output required')
    started = time.perf_counter()
    try: result = run(args.unavailable); code = 0
    except Exception as error: result = {'status':'failed','error':type(error).__name__, 'detail':str(error)}; code = 1
    result['elapsed_seconds'] = time.perf_counter() - started
    result['working_tree_dirty'] = bool(subprocess.check_output(['git','status','--porcelain'], cwd=ROOT, text=True).strip())
    result['commit'] = subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip()
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='requests'}, ensure_ascii=False))
    return code

if __name__ == '__main__': raise SystemExit(main())
