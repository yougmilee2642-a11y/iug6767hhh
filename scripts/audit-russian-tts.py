"""Local audition files + independent Whisper proxy, not a human listening verdict."""
import argparse
import json
import os
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT/'.env')
os.environ['HF_HUB_OFFLINE']='1'
os.environ['TRANSFORMERS_OFFLINE']='1'
from services import local_speech
from services.russian_tts import prepare_russian_speech
PHRASES = [
    ('test','Это тест. Проведём тест связи. Тест завершён.'),
    ('brand','Здравствуйте! Я помощник МТС. Откройте приложение «Мой МТС».'),
    ('letters','МТС, СМС, SIM-карта, API и Wi-Fi.'),
    ('stress','Он звонит. Позвоните завтра. Откройте каталог и договор. Посмотрите тариф.'),
    ('yo','Всё готово. Ваш счёт ещё не пополнен. Мы ждём подтверждения.'),
    ('numbers','Наберите *100#. Номер телефона +375 29 123 45 67.')]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--voices',default='xenia,baya,kseniya');parser.add_argument('--transcribe',action='store_true');args=parser.parse_args()
    directory=ROOT/'proof'/'tts-audit';directory.mkdir(parents=True,exist_ok=True)
    import torch
    import soundfile as sf
    torch.set_num_threads(int(os.getenv('LOCAL_CPU_THREADS','6')))
    local_speech.load_models();model=local_speech._tts
    records=[]
    for speaker in args.voices.split(','):
        for mode in ['before','prepared']:
            rate=24000 if mode=='before' else 48000
            for name,phrase in PHRASES:
                prepared=phrase if mode=='before' else prepare_russian_speech(phrase)
                began=time.perf_counter()
                with torch.inference_mode():wave=model.apply_tts(text=prepared,speaker=speaker,sample_rate=rate,
                    put_accent=True,put_yo=True,put_stress_homo=True,put_yo_homo=True)
                path=directory/f'{speaker}-{mode}-{name}.wav';sf.write(path,wave.detach().cpu().numpy(),rate,subtype='PCM_16')
                item={'speaker':speaker,'mode':mode,'sample_rate':rate,'phrase':phrase,'spoken_text':prepared,
                      'seconds':round(time.perf_counter()-began,3),'audio_seconds':round(len(wave)/rate,2),'path':str(path)}
                if args.transcribe:
                    # No phrase hint: recognition is a weak proxy, not proof of pronunciation.
                    item['asr_proxy']=local_speech.transcribe_local(path.read_bytes())
                records.append(item);print(json.dumps(item,ensure_ascii=False),flush=True)
    (directory/'audit.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf8')
    print('Audition files: '+str(directory),flush=True)


if __name__=='__main__':main()
