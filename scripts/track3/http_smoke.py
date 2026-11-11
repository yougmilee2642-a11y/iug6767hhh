"""Actual HTTP/restart acceptance with isolated DBs. No LLM double, no live-model claim.

Protocol task is explicitly human-authored from a stored quote. QA checks an unknown
2030 budget, which must refuse without inference. Grounded model QA is evaluate.py.
"""
import argparse
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))


def run():
    import httpx
    from scripts.track3.seed import seed
    events=[]
    with tempfile.TemporaryDirectory(prefix='track3-http-') as temp:
        db=Path(temp)/'smoke.db'
        ids=seed(str(db))
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        base=f'http://127.0.0.1:{port}'
        process=None
        def start():
            env={**os.environ,'CALLWISE_OWNER_PASSWORD':'','OLLAMA_BASE_URL':'http://127.0.0.1:1','MEETINGS_TIMEOUT':'1'}
            proc=subprocess.Popen([sys.executable,str(ROOT/'scripts/track3/start.py'),'--db',str(db),'--port',str(port)],
                                  cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                for _ in range(100):
                    if proc.poll() is not None: raise RuntimeError('Product server exited during startup')
                    try:
                        if httpx.get(base+'/meetings',trust_env=False,timeout=.2).status_code==200: return proc
                    except httpx.HTTPError: pass
                    time.sleep(.1)
                raise RuntimeError('Product server startup timeout')
            except BaseException:
                proc.terminate();proc.wait(timeout=10);raise
        def stop():
            nonlocal process
            if process:
                process.terminate()
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired: process.kill();process.wait(timeout=5)
                process=None
        try:
            process=start()
            with httpx.Client(base_url=base,trust_env=False,timeout=10) as i, httpx.Client(base_url=base,trust_env=False,timeout=10) as p:
                def req(client,method,url,expected=200,**kw):
                    r=client.request(method,url,**kw)
                    events.append({'method':method,'path':url,'status':r.status_code})
                    assert r.status_code==expected,(method,url,r.status_code,r.text)
                    return r.json()
                for c,who in ((i,'irina'),(p,'petr')):
                    req(c,'POST','/api/meet/login',json={'login':who,'password':who+'-demo'})
                assert req(i,'GET','/api/meet/me')['user']['access_role']=='manager'
                assert req(p,'GET','/api/meet/me')['user']['access_role']=='reader'
                mid=ids['meetings']['delay']
                req(p,'GET',f'/api/meet/meetings/{mid}',expected=404)
                req(p,'POST','/api/meet/meetings',expected=403,json={'title':'Should be denied'})
                assert any(e['action']=='access_denied' for e in req(i,'GET','/api/meet/audit?scope=my_objects')['events'])
                overview=req(i,'GET','/api/meet/overview?as_of=2026-11-11T12:00:00%2B00:00')
                values={m['key']:m['value'] for m in overview['metrics']}
                assert values['on_time_orders']==90 and values['defect_rate']==2 and values['capacity_utilization']==75
                assert values['open_tasks']==2 and values['overdue_tasks']==1
                assert req(p,'POST','/api/meet/qa',json={'question':'Какой бюджет Фотопринт на 2030 год?'})['status']=='insufficient_data'
                full=req(i,'GET',f'/api/meet/meetings/{mid}')
                u=full['utterances'][1]
                # No model is invoked: explicit manual protocol editing is part of product UX.
                manual=dict(kind='task',text='Проверить поставку ламината',assignee='Анна',due='2026-11-12',
                            due_text='до 12 ноября 2026 года',quotes=[{'utterance_id':u['id'],'text':u['text']}])
                protocol=req(i,'PUT',f'/api/meet/meetings/{mid}/protocol',json={'items':[manual]})['protocol']
                item=next(x for x in protocol['items'] if x['kind']=='task')
                confirmed=req(i,'POST',f'/api/meet/meetings/{mid}/protocol/confirm',json={'item_ids':[item['id']]})
                tid=confirmed['created'][0]['id']
                repeat=req(i,'POST',f'/api/meet/meetings/{mid}/protocol/confirm',json={'item_ids':[item['id']]})
                assert not repeat['created'] and len(repeat['already_confirmed'])==1
                change=req(i,'POST',f'/api/meet/tasks/{tid}/preview',json={'changes':{'status':'done'}})
                cid=change['confirmation_id']
                req(i,'POST',f'/api/meet/confirmations/{cid}/cancel')
                req(i,'POST',f'/api/meet/tasks/{tid}/confirm',expected=409,json={'confirmation_id':cid,'idempotency_key':'cancel-http-operation'})
                change=req(i,'POST',f'/api/meet/tasks/{tid}/preview',json={'changes':{'status':'in_progress'}})
                payload={'confirmation_id':change['confirmation_id'],'idempotency_key':'http-single-change'}
                req(i,'POST',f'/api/meet/tasks/{tid}/confirm',json=payload)
                assert req(i,'POST',f'/api/meet/tasks/{tid}/confirm',json=payload)['already_confirmed']
                # Dynamic future range; frozen transcript dates do not freeze the wall clock.
                day=datetime.now(timezone.utc).date()+timedelta(days=7)
                participants=[x['id'] for x in req(i,'GET','/api/meet/calendar/participants')['participants']]
                slots=req(i,'POST','/api/meet/calendar/slots',json={'participant_ids':participants,'range_start':f'{day}T09:00:00+03:00',
                     'range_end':f'{day+timedelta(days=3)}T18:00:00+03:00','duration_minutes':30,'timezone':'Europe/Minsk','include_weekends':True})['slots']
                data={'meeting_id':mid,'participant_ids':participants,'start_at':slots[0]['start_at'],'duration_minutes':30,'timezone':'Europe/Minsk'}
                preview=req(i,'POST','/api/meet/calendar/preview',json=data)
                req(i,'POST',f"/api/meet/confirmations/{preview['confirmation_id']}/cancel")
                assert not req(i,'GET','/api/meet/calendar/events')['events']
                preview=req(i,'POST','/api/meet/calendar/preview',json=data)
                payload={'confirmation_id':preview['confirmation_id'],'idempotency_key':'calendar-one-event'}
                calendar=req(i,'POST','/api/meet/calendar/confirm',json=payload)
                assert calendar['event']['provider']=='mock'
                assert req(i,'GET','/api/meet/calendar/outbox')['delivery']=='local_outbox_only'
                stop();process=start()
                assert req(i,'GET','/api/meet/me')['user']['login']=='irina'
                saved=req(i,'GET','/api/meet/tasks')['tasks']
                assert len([t for t in saved if t['id']==tid and t['status']=='in_progress'])==1
                req(p,'GET',f'/api/meet/meetings/{mid}',expected=404)
                return {'status':'passed','test_kind':'real HTTP + human-authored protocol; no model quality measurement',
                        'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                        'requests':events,'voice_weights_required':False,'torch_installed':importlib.util.find_spec('torch') is not None,
                        'restart_cookie_and_state':'passed','kpi_before_mutations':values}
        finally:
            stop()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);a=p.parse_args()
    start=time.perf_counter()
    try: result=run();code=0
    except Exception as e: result={'status':'failed','error_type':type(e).__name__,'detail':str(e)};code=1
    result['elapsed_seconds']=time.perf_counter()-start
    Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='requests'},ensure_ascii=False))
    return code


if __name__=='__main__': raise SystemExit(main())
