"""Real localhost API smoke. Synthetic audio only; never submits a dialogue turn."""
import io
import json
import sys
import uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import requests
import soundfile as sf
from services.dual_asr import decode_audio

ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:8000'
client=requests.Session()
def post(path,**kwargs):
    result=client.post(BASE+path,timeout=60,**kwargs)
    result.raise_for_status()
    return result
def wav(audio):
    out=io.BytesIO();sf.write(out,audio,16000,format='WAV',subtype='PCM_16');return out.getvalue()

state=post('/api/conversations',json={}).json()
interaction=state['interaction_id']
try:
    privacy=state.get('privacy')
    if privacy and privacy.get('status')=='pending':
        post(f'/api/conversations/{interaction}/consent',json={'accepted':True,'version':privacy['version']})
    audio=decode_audio(post('/api/speech',json={'text':'Здравствуйте. Меня зовут Мария. Хочу маникюр в пятницу в пятнадцать часов.'}).content)
    stream=str(uuid.uuid4());partials=[]
    for sequence,start in enumerate(range(0,len(audio),14400)):
        result=post('/api/transcribe',files={'file':('chunk.wav',wav(audio[start:start+14400]),'audio/wav')},
            data={'interaction_id':interaction,'mode':'preview','stream_id':stream,'sequence':sequence}).json()
        assert result['cumulative'] and result['final'] is False
        partials.append(result['raw_text'])
    final=post('/api/transcribe',files={'file':('utterance.wav',wav(audio),'audio/wav')},
        data={'interaction_id':interaction,'mode':'final','stream_id':stream}).json()
    assert final['final'] and final['raw_text'] and final['speaker']['status']=='enrolled'
    summary={'interaction_id':interaction,'preview_requests':len(partials),'last_preview':partials[-1],
             'final':final,'health':client.get(BASE+'/api/health',timeout=10).json()['local_speech']}
    (ROOT/'data/asr-verification').mkdir(parents=True,exist_ok=True)
    (ROOT/'data/asr-verification/http-smoke.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=True),flush=True)
finally:
    post('/api/application',json={'interaction_id':interaction})
