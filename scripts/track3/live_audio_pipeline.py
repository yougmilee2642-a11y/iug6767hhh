"""HOST ONLY: opt-in real local ASR/diarization on a consented synthetic WAV.

The agent must not run this script with --allow-models. No Ollama/TTS/cloud call.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--allow-models',action='store_true',help='Explicit host permission to run local ASR/diarization')
    parser.add_argument('--synthetic-with-consent',action='store_true')
    parser.add_argument('--expected-speakers',type=int,default=2)
    args=parser.parse_args()
    if not args.allow_models or not args.synthetic_with_consent:
        parser.error('Нужны --allow-models и --synthetic-with-consent; агент не запускает inference.')
    if not args.audio.is_file() or args.audio.stat().st_size>64*1024*1024:parser.error('Нужен синтетический WAV не больше64МБ.')
    if not args.output.is_absolute() or args.output.exists():parser.error('--output: новый абсолютный JSON-путь.')
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from scripts.track3.seed_fotoprint import seed
    began=time.perf_counter()
    report={'status':'failed','execution_kind':'host_live_audio','live_quality':'requires_human_transcript_review',
            'cloud_accounts':'not_used','expected_speakers':args.expected_speakers,
            'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()}
    try:
        with tempfile.TemporaryDirectory(prefix='focus-live-audio-') as temp:
            os.environ.update(MEETINGS_SECRET='synthetic-audio-check',MEETINGS_AUDIO_PIPELINE_ENABLED='1',
                MEETINGS_CALENDAR_PROVIDER='mock',MEETINGS_BITRIX_ENABLED='0',CALLWISE_LOCAL_ONLY='true',
                TELEGRAM_ENABLED='false',CALLWISE_CLOUD_INTEGRATIONS_ENABLED='false')
            seed(str(Path(temp)/'meetings.db'))
            from meetings.api import install
            from meetings import store
            app=FastAPI();install(app)
            with TestClient(app) as client:
                client.post('/api/meet/login',json={'login':'prod_head','password':'prod_head-demo'}).raise_for_status()
                meeting=client.post('/api/meet/meetings',json={'title':'Синтетическая живая проверка аудио'}).json()['meeting']['id']
                uploaded=client.post(f'/api/meet/meetings/{meeting}/audio',data={'consent':'true'},
                                    files={'file':('synthetic.wav',args.audio.read_bytes(),'audio/wav')})
                report['upload_http_status']=uploaded.status_code
                data=uploaded.json();job=data.get('job')
                if not job:raise ValueError('upload_failed')
                final=client.get('/api/meet/media-jobs/'+str(job['id']));final.raise_for_status();job=final.json()['job']
                labels=sorted({s['speaker_label'] for s in job['segments']})
                report.update(job_status=job['status'],error_code=job['error_code'],duration_ms=job['duration_ms'],
                              utterance_count=len(job['segments']),speakers=labels)
                if job['status']=='done' and len(labels)==args.expected_speakers:
                    p=client.post(f"/api/meet/media-jobs/{job['id']}/import/preview",json={});p.raise_for_status()
                    confirmed=client.post(f"/api/meet/media-jobs/{job['id']}/import/confirm",json={
                        'confirmation_id':p.json()['confirmation_id'],'idempotency_key':'host-live-audio'})
                    confirmed.raise_for_status();report['confirmed_utterance_count']=len(confirmed.json()['utterance_ids'])
                    report['segments']=job['segments'];report['status']='pipeline_passed'
                store.reset_cache()
    except Exception as error:
        report['error_type']=type(error).__name__  # no provider/path/credential exception text
    report['elapsed_seconds']=round(time.perf_counter()-began,3)
    with args.output.open('x',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps({k:report.get(k) for k in ('status','utterance_count','speakers','elapsed_seconds')},ensure_ascii=False))
    return 0 if report['status']=='pipeline_passed' else 1


if __name__=='__main__':raise SystemExit(main())
