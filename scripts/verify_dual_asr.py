"""Real local model smoke; uses synthetic voices and upstream public demo audio only."""
import html
import io
import json
import os
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv()
os.environ['HF_HUB_OFFLINE']='1'
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly
from services import local_speech, dual_asr

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/asr-verification'
OUT.mkdir(exist_ok=True)

def wav(audio):
    out=io.BytesIO();sf.write(out,audio,16000,format='WAV',subtype='PCM_16');return out.getvalue()

def say(text,speaker='xenia'):
    os.environ['LOCAL_TTS_SPEAKER']=speaker
    return dual_asr.decode_audio(local_speech.synthesize_local(text))

def check(title,audio,session,expected,streaming=False):
    began=time.perf_counter(); preview='';partials=0
    if streaming:
        for i,start in enumerate(range(0,len(audio),14400)):
            response=local_speech.transcribe_preview(wav(audio[start:start+14400]),session,title,i)
            preview=response['raw_text'];partials+=1
        preview_seconds=round(time.perf_counter()-began,3)
    else:preview_seconds=None
    result=local_speech.transcribe_final(wav(audio),interaction_id=session,stream_id=title)
    row=dict(case=title,audio_seconds=round(len(audio)/16000,2),tone=preview,
             preview_processing_seconds=preview_seconds,partial_requests=partials,
             expected=expected,**result)
    if expected=='recognize':row['pass']=bool(result['raw_text']) and not result.get('speaker',{}).get('requires_repeat')
    elif expected=='reject':row['pass']=not result['raw_text']
    elif expected=='remove_background':
        row['pass']=('да все правильно' in result['raw_text'].lower().replace('ё','е')
                     and result.get('speaker',{}).get('removed_background_speakers',0)>0
                     and 'другим человеком' not in result['raw_text'])
    elif expected=='all_digits':
        from providers.language import normalize_transcript
        row['normalized_phone']=normalize_transcript(result['raw_text'],'Назовите номер телефона.','ru')
        row['pass']='375291234567' in row['normalized_phone']
    rows.append(row)
    print(json.dumps(row,ensure_ascii=True),flush=True)

local_speech.warm_up()
rows=[]
primary=say('Здравствуйте. Меня зовут Мария. Хочу записаться на маникюр в пятницу в пятнадцать часов.')
other=say('Мне не нужна запись. Я разговариваю с другим человеком. Не записывайте меня.','aidar')
phone=say('Мой номер телефона. Три семь пять. Два девять. Один два три. Четыре пять шесть семь.')
yes=say('Да, всё правильно.')
silence=np.zeros(16000,dtype=np.float32)
check('01 · Первая реплика и поток T-one',primary,'synthetic-main','recognize',True)
check('02 · Тот же голос и телефон с паузами',phone,'synthetic-main','all_digits',True)
check('03 · Короткое подтверждение',yes,'synthetic-main','recognize')
check('04 · Другой голос после регистрации',other,'synthetic-main','reject')
check('05 · Посторонняя речь между репликами',np.concatenate([primary,silence,other,silence,yes]),'synthetic-main','remove_background')
mixed=primary.copy();n=min(len(mixed),len(other));mixed[:n]=np.clip(mixed[:n]+other[:n]*.65,-1,1)
check('06 · Два голоса одновременно',mixed,'synthetic-main','reject')
check('07 · Тишина',silence,'synthetic-main','reject')
rng=np.random.default_rng(7)
check('08 · Шум без речи',rng.normal(0,.015,16000*3).astype(np.float32),'synthetic-main','reject')
human=dual_asr.decode_audio((ROOT/'tools/T-one/tone/demo/audio_examples/audio_short.flac').read_bytes())
check('09 · Полная запись демо T-one, проверка только ASR',human,'','recognize',True)
segments=dual_asr._diarizer.process(human).sort_by_start_time()
longest=max(segments,key=lambda s:s.end-s.start)
clean_human=human[max(0,int(longest.start*16000)):min(len(human),int(longest.end*16000))]
check('10 · Один говорящий из открытой записи',clean_human,'public-demo','recognize',True)
check('11 · Повтор человеческого голоса с тихим окончанием',np.concatenate([clean_human,np.zeros(16000*2,dtype=np.float32)]),'public-demo','recognize')
check('12 · Два человека в первой реплике',human,'public-multi','reject')
report={'readiness':local_speech.readiness(),'cases':rows,'passed':sum(r['pass'] for r in rows),'total':len(rows),
        'limits':'Синтетическая проверка и один открытый пример не заменяют тесты на ваших записях. Короткий ответ может быть принят без проверки личности. Наложенные голоса иногда не обнаруживаются сегментатором.'}
(OUT/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
from render_asr_report import render_report
destination=render_report(report)
(OUT/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(f'REPORT: {destination}',flush=True)
