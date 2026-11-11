"""Real speech/models + callback smoke; block non-loopback Python connections."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['PYTHONUTF8']='1'
from dotenv import load_dotenv
load_dotenv(ROOT/'.env')
os.environ['CALLWISE_LOCAL_ONLY']='true'
os.environ['AI_PROVIDER']='ollama'
os.environ['HF_HUB_OFFLINE']='1'
os.environ['TRANSFORMERS_OFFLINE']='1'
os.environ['HF_HUB_DISABLE_TELEMETRY']='1'


def deny_external(event,args):
    if event=='socket.connect':
        address=args[1]
        if isinstance(address,tuple) and address[0] not in {'127.0.0.1','::1','localhost'}:
            raise RuntimeError('Non-loopback connection blocked in local smoke')


sys.addaudithook(deny_external)
import storage
from services.local_speech import synthesize_local,transcribe_local,load_models
from services.track1_service import make_config,QuickInput
from agents.runtime import new_interaction
from agents.factory import create_runtime
from providers.ollama import OllamaProvider


def main():
    # First load is measured separately, not hidden in steady-state latency.
    started=time.perf_counter();load_models();load=time.perf_counter()-started
    started=time.perf_counter();audio=synthesize_local('Здравствуйте. Хочу обсудить создание сайта.');tts=time.perf_counter()-started
    started=time.perf_counter();text=transcribe_local(audio);stt=time.perf_counter()-started
    if 'сайт' not in text.casefold(): raise AssertionError('Synthetic speech recognition did not preserve request topic')
    provider=OllamaProvider()
    answers=[]
    with tempfile.TemporaryDirectory(prefix='callwise-local-smoke-') as directory:
      with storage.isolated_database(Path(directory)/'smoke.sqlite'):
        storage.initialize_db()
        config=make_config(QuickInput(business_name='Синтетический IT-тест',facts='Разрабатываем сайты. Стоимость только после обсуждения.'),'local_smoke')
        state=new_interaction(config)
        runtime=create_runtime(config,provider)
        for phrase in ['Алексей','+375290000000','Хочу обсудить создание сайта.','Да']:
            start=time.perf_counter();reply=runtime.turn(state,phrase)
            answers.append({'status':reply['status'],'text':reply['text'],'seconds':round(time.perf_counter()-start,2)})
        if state['status']!='completed':
            print(json.dumps({'dialogue':answers,'state':state},ensure_ascii=False,default=str),flush=True)
            raise AssertionError('Callback not completed: '+state['status'])
        with storage.connect() as db:
            assert db.execute('SELECT COUNT(*) FROM callback_requests').fetchone()[0]==1
            assert db.execute('SELECT COUNT(*) FROM tg_outbox').fetchone()[0]==0
    print(json.dumps({'status':'passed','speech_load_seconds':round(load,2),'tts_seconds':round(tts,2),'stt_seconds':round(stt,2),
                      'synthetic_recognition':text,'dialogue':answers,'provider':provider.metadata(),
                      'external_python_connections':'blocked','database':'temporary'},ensure_ascii=False),flush=True)


if __name__=='__main__': main()
