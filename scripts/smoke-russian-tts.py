"""Check the running local speech endpoint; only synthetic test text is used."""
import argparse
import io
import json
import os
import sys
import time
import urllib.request
import wave
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
PHRASE='Здравствуйте! Я помощник МТС. Это тест связи. Наберите *100#. Ваш счёт ещё не пополнен.'


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--compare-voices',action='store_true',help='Render the same phrase with installed baya/kseniya voices')
    args=parser.parse_args()
    with urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=10) as response:
        health=json.load(response)
    assert health['local_only'] and health['ai_provider']=='Ollama', 'Not the local-only server'
    request=urllib.request.Request('http://127.0.0.1:8000/api/speech',
        data=json.dumps({'text':PHRASE}).encode('utf8'),
        headers={'Content-Type':'application/json'},method='POST')
    began=time.perf_counter()
    with urllib.request.urlopen(request,timeout=60) as response:
        assert response.headers.get_content_type()=='audio/wav'
        audio=response.read()
    elapsed=time.perf_counter()-began
    with wave.open(io.BytesIO(audio),'rb') as wav:
        rate=wav.getframerate()
        duration=wav.getnframes()/rate
        assert wav.getnchannels()==1 and wav.getsampwidth()==2 and duration>1
    directory=ROOT/'proof'/'tts-audit'
    directory.mkdir(parents=True,exist_ok=True)
    output=directory/'live-api.wav'
    output.write_bytes(audio)
    report={'text':PHRASE,'rate':rate,'audio_seconds':round(duration,2),
            'request_seconds':round(elapsed,3),'bytes':len(audio),'path':str(output)}
    (directory/'live-api.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False))
    if args.compare_voices:
        from dotenv import load_dotenv
        load_dotenv(ROOT/'.env')
        os.environ['HF_HUB_OFFLINE']='1'
        os.environ['TRANSFORMERS_OFFLINE']='1'
        from services import local_speech
        previous=os.environ.get('LOCAL_TTS_SPEAKER')
        try:
            for speaker in ['baya','kseniya']:
                os.environ['LOCAL_TTS_SPEAKER']=speaker
                path=directory/f'{speaker}-comparison.wav'
                path.write_bytes(local_speech.synthesize_local(PHRASE))
                print(json.dumps({'speaker':speaker,'path':str(path)},ensure_ascii=False))
        finally:
            if previous is None:os.environ.pop('LOCAL_TTS_SPEAKER',None)
            else:os.environ['LOCAL_TTS_SPEAKER']=previous


if __name__=='__main__':main()
