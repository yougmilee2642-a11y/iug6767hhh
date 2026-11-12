"""HOST ONLY: synthetic consented ASR -> read/action draft -> optional local TTS.

No Ollama request: unexpected knowledge routing stops before the question runs.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--audio',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--allow-models',action='store_true');p.add_argument('--synthetic-with-consent',action='store_true')
    p.add_argument('--tts-output',type=Path)
    args=p.parse_args()
    if not args.allow_models or not args.synthetic_with_consent:p.error('Нужны явные --allow-models --synthetic-with-consent.')
    if not args.audio.is_file() or args.audio.stat().st_size>4*1024*1024:p.error('Нужен синтетический WAV не больше4МБ.')
    if not args.output.is_absolute() or args.output.exists():p.error('--output: новый абсолютный JSON-путь.')
    if args.tts_output and (not args.tts_output.is_absolute() or args.tts_output.exists() or args.tts_output==args.output):p.error('--tts-output: отдельный новый абсолютный WAV-путь.')
    os.environ.update(CALLWISE_LOCAL_ONLY='true',TELEGRAM_ENABLED='false',CALLWISE_CLOUD_INTEGRATIONS_ENABLED='false',
        MEETINGS_SECRET='synthetic-voice-live',MEETINGS_AUDIO_PIPELINE_ENABLED='0',MEETINGS_CALENDAR_PROVIDER='mock',MEETINGS_BITRIX_ENABLED='0')
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from meetings import store,voice,voice_chat
    from meetings.api import install
    from scripts.track3.seed_fotoprint import seed
    report={'status':'failed','execution_kind':'host_live_voice','quality':'requires_human_audio_review',
            'models_run_by_agent':False,'ollama_called':False};began=time.perf_counter()
    try:
        with tempfile.TemporaryDirectory(prefix='focus-live-voice-') as temp:
            seed(str(Path(temp)/'meetings.db'));app=FastAPI();install(app)
            with TestClient(app) as c:
                c.post('/api/meet/login',json={'login':'prod_head','password':'prod_head-demo'}).raise_for_status()
                mid=c.post('/api/meet/meetings',json={'title':'Личная синтетическая проверка голоса'}).json()['meeting']['id']
                with store.db() as db:
                    before={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('tasks','calendar_events','calendar_outbox','confirmations','meetings','documents','integration_outbox','media_assets','calls')}
                t=time.perf_counter();r=c.post('/api/meet/voice/transcribe',files={'file':('synthetic.wav',args.audio.read_bytes(),'audio/wav')});r.raise_for_status()
                report['asr_ms']=round((time.perf_counter()-t)*1000);text=r.json()['text'];report['recognized_text']=text
                _,rest=voice_chat.split_greeting(text)
                candidate=voice.route(rest or text)
                if candidate=='knowledge' and not voice_chat.small_talk(text,{'name':'Марина'},voice.utc_now()):
                    raise ValueError('unexpected_knowledge_route')
                t=time.perf_counter();r=c.post('/api/meet/voice/ask',json={'text':text,'meeting_id':mid});r.raise_for_status()
                reply=r.json();report.update(route=reply['route'],reply_ms=round((time.perf_counter()-t)*1000),reply=reply)
                with store.db() as db:
                    after={table:db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in before}
                report['no_hidden_actions']=before==after
                if args.tts_output and reply.get('speak') and reply.get('spoken'):
                    from services.local_speech import synthesize_local
                    t=time.perf_counter();audio=synthesize_local(reply['spoken'],os.getenv('FOCUS_TTS_SPEAKER','aidar'))
                    with args.tts_output.open('xb') as f:f.write(audio)
                    report.update(tts_ms=round((time.perf_counter()-t)*1000),tts_bytes=len(audio),tts_output=str(args.tts_output))
                from services.local_speech import readiness
                report['readiness']=readiness()
                report['status']='pipeline_passed' if before==after else 'failed'
            store.reset_cache()
    except Exception as error:report['error_type']=type(error).__name__
    report['elapsed_seconds']=round(time.perf_counter()-began,3)
    with args.output.open('x',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps({k:report.get(k) for k in ('status','route','asr_ms','reply_ms','tts_ms')},ensure_ascii=False))
    return report['status']!='pipeline_passed'


if __name__=='__main__':raise SystemExit(main())
