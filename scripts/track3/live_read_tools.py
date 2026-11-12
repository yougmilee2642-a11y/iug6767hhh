"""HOST ONLY: real Ollama selector paths, synthetic data, no business writes."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--allow-models',action='store_true');p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if not args.allow_models:p.error('Хост должен явно передать --allow-models. Агент inference не запускает.')
    if not args.output.is_absolute() or args.output.exists():p.error('--output: новый абсолютный JSON-путь.')
    os.environ.update(MEETINGS_SECRET='synthetic-read-tools',MEETINGS_AUDIO_PIPELINE_ENABLED='0',MEETINGS_CALL_TOPIC_MODEL='1',
                      MEETINGS_ASSISTANT_MODEL_ROUTER='1',MEETINGS_CALENDAR_PROVIDER='mock',MEETINGS_BITRIX_ENABLED='0')
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from meetings import store
    from meetings.api import install
    from meetings.llm import get_llm
    from scripts.track3.seed_fotoprint import seed
    from scripts.track3.evaluate import model_info
    report={'status':'failed','execution_kind':'host_live_selectors','quality':'requires_human_salience_topic_review'};began=time.perf_counter()
    try:
        report['model']=model_info(get_llm().model)
        with tempfile.TemporaryDirectory(prefix='focus-live-selectors-') as temp:
            ids=seed(str(Path(temp)/'meetings.db'));app=FastAPI();install(app)
            with TestClient(app) as c:
                c.post('/api/meet/login',json={'login':'prod_head','password':'prod_head-demo'}).raise_for_status()
                text='Положение,Правило\n'+''.join(f'Контроль {i},Проверить сроки изготовления и образцы переплёта перед запуском партии {i}.\n' for i in range(1,8))
                r=c.post('/api/meet/documents',files={'file':('synthetic.csv',text.encode(),'text/csv')});r.raise_for_status();did=r.json()['document']['id']
                with store.db() as db:before={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('tasks','calendar_events','calendar_outbox','integration_outbox','meetings','documents','calls')}
                t=time.perf_counter();r=c.get(f'/api/meet/documents/{did}/summary?semantic=true');r.raise_for_status()
                summary=r.json();report.update(summary=summary,summary_ms=round((time.perf_counter()-t)*1000))
                t=time.perf_counter();r=c.post('/api/meet/assistant/ask',json={'text':'Что просрочено?'});r.raise_for_status()
                report.update(assistant=r.json(),assistant_ms=round((time.perf_counter()-t)*1000))
                c.post('/api/meet/logout');c.post('/api/meet/login',json={'login':'sup_head','password':'sup_head-demo'}).raise_for_status()
                r=c.post('/api/meet/calls/preview',json={'direction':'in','agent_user_id':ids['users']['sup_agent'],
                    'consent':True,'started_at':store.now(),'segments':[{'speaker':'Оператор','text':'Здравствуйте, меня зовут Светлана. Предлагаю перепечатку.'},
                    {'speaker':'Клиент','text':'Брак переплёта Premium, нужен возврат.'}]});r.raise_for_status()
                r=c.post('/api/meet/calls/confirm',json={'confirmation_id':r.json()['confirmation_id'],'idempotency_key':'host-live-topics'});r.raise_for_status();cid=r.json()['call_id']
                t=time.perf_counter();r=c.get(f'/api/meet/calls/{cid}/topics');r.raise_for_status()
                report.update(topics=r.json(),topics_ms=round((time.perf_counter()-t)*1000))
                report['control_topic_found']=any(t['code']=='topic-00' for t in report['topics']['suggestions'])
                report['assistant_grounded']=report['assistant']['status']=='grounded' and bool(report['assistant'].get('claims'))
                with store.db() as db:after={table:db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in before}
                expected={**before,'meetings':before['meetings']+1,'calls':before['calls']+1}
                report['expected_manual_imports']={'meetings':1,'calls':1}
                report['no_hidden_actions']=expected==after
                report['status']='pipeline_passed' if expected==after and summary['claims'] and report['control_topic_found'] and report['assistant_grounded'] else 'failed'
            store.reset_cache()
    except Exception as error:report['error_type']=type(error).__name__
    report['elapsed_seconds']=round(time.perf_counter()-began,3)
    with args.output.open('x',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps({k:report.get(k) for k in ('status','summary_ms','assistant_ms','topics_ms')},ensure_ascii=False));return report['status']!='pipeline_passed'


if __name__=='__main__':raise SystemExit(main())
