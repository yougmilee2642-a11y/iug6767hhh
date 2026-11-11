import sys, os, json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv()
import numpy as np
import torch
from silero_vad import get_speech_timestamps
from services import local_speech as speech, dual_asr as asr
speech.load_models()
def say(text,speaker):
    os.environ['LOCAL_TTS_SPEAKER']=speaker
    return asr.decode_audio(speech.synthesize_local(text))
a=say('Здравствуйте. Меня зовут Мария. Хочу записаться на маникюр в пятницу в пятнадцать часов.','xenia')
b=say('Мне не нужна запись. Я разговариваю с другим человеком. Не записывайте меня.','aidar')
c=say('Да, всё правильно.','xenia')
asr.filter_speaker(a,'diagnostic')
audio=np.concatenate([a,np.zeros(16000,dtype=np.float32),b,np.zeros(16000,dtype=np.float32),c])
vad=get_speech_timestamps(torch.from_numpy(audio),speech._vad,sampling_rate=16000)
segments=asr._diarizer.process(audio).sort_by_start_time()
reference=asr._speakers['diagnostic'][0]
out,meta=asr.filter_speaker(audio,'diagnostic',vad)
record={'vad':vad,'segments':[(s.start,s.end,s.speaker) for s in segments],
        'vad_similarity':[(s,float(np.dot(reference,asr.speaker_embedding(audio[s['start']:s['end']])))) for s in vad if asr.speaker_embedding(audio[s['start']:s['end']]) is not None],
        'original_tail_length':len(c),'retained_tail_nonzero':int(np.count_nonzero(out[-len(c):])),
        'tail_difference':float(np.max(np.abs(out[-len(c):]-c))), 'metadata':meta}
print(json.dumps(record),flush=True)
