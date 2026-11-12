"""Frozen deterministic call control; no model or external accounts are used."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
CONTROL=ROOT/'demo/track3/transcripts/call_defect_timed.txt'
LEGACY=ROOT/'demo/track3/transcripts/call_defect.txt'
EXPECTED=ROOT/'evaluation/track3/calls/expected.json'
FROZEN=ROOT/'evaluation/track3/calls/frozen.json'


def control():
    frozen=json.loads(FROZEN.read_text(encoding='utf-8'))
    for path in (CONTROL,LEGACY,EXPECTED):
        if hashlib.sha256(path.read_bytes()).hexdigest()!=frozen[str(path.relative_to(ROOT))]:
            raise ValueError('frozen_call_changed')
    segments=[]
    for line in CONTROL.read_text(encoding='utf-8').splitlines():
        m=re.fullmatch(r'\[(\d+):(\d+)-(\d+):(\d+)\] ([^:]+): (.+)',line)
        if not m:raise ValueError('invalid_control_format')
        segments.append({'speaker':m[5],'text':m[6],'start_ms':(int(m[1])*60+int(m[2]))*1000,
                         'end_ms':(int(m[3])*60+int(m[4]))*1000})
    return segments,json.loads(EXPECTED.read_text(encoding='utf-8'))


def evaluate():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from meetings import store
    from meetings.api import install
    from scripts.track3.seed_fotoprint import seed
    segments,gold=control()
    with tempfile.TemporaryDirectory(prefix='focus-call-eval-') as temp:
        os.environ.update(MEETINGS_SECRET='synthetic-call-eval',MEETINGS_AUDIO_PIPELINE_ENABLED='0',
                          MEETINGS_CALENDAR_PROVIDER='mock',MEETINGS_BITRIX_ENABLED='0')
        ids=seed(str(Path(temp)/'meetings.db'));app=FastAPI();install(app)
        with TestClient(app) as client:
            client.post('/api/meet/login',json={'login':'sup_head','password':'sup_head-demo'}).raise_for_status()
            p=client.post('/api/meet/calls/preview',json={'direction':'in','agent_user_id':ids['users']['sup_agent'],
                'consent':True,'duration_ms':40000,'started_at':store.now(),'segments':segments});p.raise_for_status()
            confirmation={'confirmation_id':p.json()['confirmation_id'],'idempotency_key':'call-evaluation'}
            result=client.post('/api/meet/calls/confirm',json=confirmation);result.raise_for_status()
            analysis=client.get('/api/meet/calls/'+str(result.json()['call_id']));analysis.raise_for_status();data=analysis.json()
            evidence=[s for group in [*data['topics'],*data['checklist'],*data['triggers'],data['risk'],*data['next_steps']] for s in group['sources']]
            citations_ok=True
            for s in evidence:
                source=client.get('/api/meet/utterances/'+s['id']);source.raise_for_status()
                citations_ok &= s['quote'] in source.json()['utterance']['text']
            checks={'topics':set(gold['required_topics'])<={t['code'] for t in data['topics']},
                    'checklist':data['checklist_passed']==gold['checklist_passed'],
                    'risk':data['risk']['flag']==gold['risk'],
                    'triggers':set(gold['required_triggers'])<={t['text'] for t in data['triggers']},
                    'overlap':data['overlap_ms']==gold['overlap_ms'],'quotes':citations_ok and bool(evidence),
                    'no_hidden_tasks':False}
            with store.db() as c:checks['no_hidden_tasks']=not c.execute('SELECT 1 FROM tasks WHERE meeting_id=?',(result.json()['meeting_id'],)).fetchone()
            replay=client.post('/api/meet/calls/confirm',json=confirmation);checks['replay']=replay.status_code==200 and replay.json()['already_confirmed']
            client.post('/api/meet/logout');client.post('/api/meet/login',json={'login':'operator','password':'operator-demo'})
            checks['foreign_scope']=client.get('/api/meet/calls/'+str(result.json()['call_id'])).status_code==404
            client.post('/api/meet/logout');client.post('/api/meet/login',json={'login':'sup_head','password':'sup_head-demo'})
            legacy_segments=[dict(zip(('speaker','text'),line.split(': ',1))) for line in LEGACY.read_text(encoding='utf-8').splitlines()]
            p=client.post('/api/meet/calls/preview',json={'direction':'in','agent_user_id':ids['users']['sup_agent'],
                'agent_speaker_label':'Светлана','consent':True,'started_at':store.now(),'segments':legacy_segments});p.raise_for_status()
            r=client.post('/api/meet/calls/confirm',json={'confirmation_id':p.json()['confirmation_id'],'idempotency_key':'legacy-call-evaluation'});r.raise_for_status()
            legacy=client.get('/api/meet/calls/'+str(r.json()['call_id']));legacy.raise_for_status();legacy=legacy.json();expected=gold['legacy']
            checks['legacy_topics']=set(expected['required_topics'])<={t['code'] for t in legacy['topics']}
            checks['legacy_checklist']={i['code'] for i in legacy['checklist'] if i['passed']}==set(expected['passed_checklist_codes'])
            checks['legacy_risk']=legacy['risk']['flag']==expected['risk']
            checks['legacy_triggers']=set(expected['required_triggers'])<={t['text'] for t in legacy['triggers']}
            checks['legacy_no_fabricated_timings']=legacy['talk_percent'] is None and legacy['overlap_ms'] is None
            legacy_sources=[s for group in [*legacy['topics'],*legacy['checklist'],*legacy['triggers'],legacy['risk'],*legacy['next_steps']] for s in group['sources']]
            checks['legacy_quotes']=bool(legacy_sources)
            for s in legacy_sources:
                u=client.get('/api/meet/utterances/'+s['id']);u.raise_for_status()
                checks['legacy_quotes'] &= s['quote'] in u.json()['utterance']['text']
            store.reset_cache()
            return {'status':'passed' if all(checks.values()) else 'failed','execution_kind':'deterministic_rules_control',
                    'live_model_quality':'not_measured','checks':checks,'analysis':data,'legacy_analysis':legacy,
                    'control_sha256':hashlib.sha256(CONTROL.read_bytes()).hexdigest()}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    if not args.output.is_absolute() or args.output.exists():p.error('Нужен новый абсолютный JSON-путь.')
    began=time.perf_counter();report=evaluate();report['elapsed_seconds']=round(time.perf_counter()-began,3)
    report['commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    report['working_tree_dirty']=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True))
    with args.output.open('x',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps({'status':report['status'],'checks':report['checks']},ensure_ascii=False));return report['status']!='passed'


if __name__=='__main__':raise SystemExit(main())
