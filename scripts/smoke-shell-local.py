"""Real loopback HTTP speech -> STT -> Ollama -> TTS -> persisted conversation."""
import io
import json
import os
import sys
import time
from pathlib import Path
import httpx
import av
from dotenv import load_dotenv
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
load_dotenv(ROOT/'.env')


def main():
    with httpx.Client(base_url='http://127.0.0.1:8000',timeout=120,trust_env=False) as client:
        def post(path,**kwargs):
            response=client.post(path,**kwargs);response.raise_for_status();return response
        health=client.get('/api/health').json()
        assert health['local_only'] and health['model']==os.environ['OLLAMA_MODEL']
        start=post('/api/shell/conversations',json={'id':'shell-smoke','name':'Синтетическая проверка оболочки',
            'company':'Тестовая команда','role':'Поддержка клиентов','greeting':'Здравствуйте! Чем могу помочь?',
            'knowledge':'Тестовый факт: кодовое слово команды — Парус. Не собирай личные данные.',
            'qa':[{'question':'Какое кодовое слово команды?','answer':'Кодовое слово команды — Парус.'}]}).json()
        cid=start['interaction_id'];times={}
        try:
            privacy=start.get('privacy',{})
            if privacy.get('status')=='pending':
                post('/api/conversations/'+cid+'/consent',json={'accepted':True,'version':privacy['version']})
            began=time.perf_counter();wav=post('/api/speech',json={'text':'Какое кодовое слово команды?'}).content;times['input_tts']=round(time.perf_counter()-began,2)
            # Browser-compatible WebM/Opus, not only a WAV service unit test.
            webm=io.BytesIO()
            with av.open(io.BytesIO(wav)) as source, av.open(webm,'w',format='webm') as output:
                stream=output.add_stream('libopus',rate=48000);stream.layout='mono'
                for frame in source.decode(audio=0):
                    for packet in stream.encode(frame):output.mux(packet)
                for packet in stream.encode(None):output.mux(packet)
            began=time.perf_counter();recognized=post('/api/transcribe',files={'file':('voice.webm',webm.getvalue(),'audio/webm')},
                data={'interaction_id':cid}).json()['text'];times['stt']=round(time.perf_counter()-began,2)
            assert 'слов' in recognized.casefold(),recognized
            began=time.perf_counter();reply=post('/api/chat',json={'interaction_id':cid,'text':recognized,'request_id':'shell-smoke-turn'}).json();times['llm']=round(time.perf_counter()-began,2)
            assert 'парус' in reply['text'].casefold(),reply['text']
            began=time.perf_counter();sound=post('/api/speech',json={'text':reply['text']}).content;times['output_tts']=round(time.perf_counter()-began,2)
            assert sound.startswith(b'RIFF')
        finally:
            stopped=post('/api/application',json={'interaction_id':cid}).json()
        history=client.get('/api/shell/interactions').json()['items']
        saved=next(item for item in history if item['id']==cid)
        assert saved['status']=='stopped' and any(m['role']=='user' for m in saved['transcript'])
        print(json.dumps({'status':'passed','model':health['model'],'recognized':recognized,'answer':reply['text'],
            'seconds':times,'input_format':'WebM/Opus','output_format':'WAV','saved_interaction':cid},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
