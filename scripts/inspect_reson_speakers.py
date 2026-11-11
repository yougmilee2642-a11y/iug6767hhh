"""Inspect acoustic speaker decisions without using reference text to select voices."""
import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv()
import numpy as np
import torch
from silero_vad import get_speech_timestamps
from services import local_speech,dual_asr as asr
local_speech.load_models()
rows=json.loads((asr.ROOT/'data/reson-first20/selection.json').read_text(encoding='utf-8'))
out=[]
for number in (1,6,9):
    audio=asr.decode_audio((asr.ROOT/'downloads/reson-first20'/rows[number-1]['file_name']).read_bytes())
    segments=asr._diarizer.process(audio).sort_by_start_time()
    groups={}
    for s in segments:groups.setdefault(s.speaker,[]).append(audio[int(s.start*16000):int(s.end*16000)])
    lengths={k:sum(len(p) for p in v)/16000 for k,v in groups.items()}
    main=max(lengths,key=lengths.get)
    # A long middle excerpt is diagnostic only, never reference-guided.
    main_wave=np.concatenate(groups[main])
    anchor=asr.speaker_embedding(main_wave[len(main_wave)//3:len(main_wave)//3+16000*3])
    whole=asr.speaker_embedding(main_wave)
    windows=[]
    for start in range(0,len(audio)-16000,8000):
        part=audio[start:start+24000]
        emb=asr.speaker_embedding(part)
        windows.append({'start':round(start/16000,2),'rms':round(float(np.sqrt(np.mean(part**2))),4),
            'anchor':round(float(np.dot(anchor,emb)),3),'whole':round(float(np.dot(whole,emb)),3)})
    vad=get_speech_timestamps(torch.from_numpy(audio.copy()),local_speech._vad,sampling_rate=16000)
    regions=[]
    for s in vad:
        part=audio[s['start']:s['end']];emb=asr.speaker_embedding(part)
        regions.append({'start':round(s['start']/16000,3),'end':round(s['end']/16000,3),
            'rms':round(float(np.sqrt(np.mean(part**2))),4),'similarity':None if emb is None else round(float(np.dot(whole,emb)),3)})
    result={'number':number,'durations':lengths,'segments':[(round(s.start,3),round(s.end,3),s.speaker) for s in segments],
            'vad':regions,
            'windows':windows}
    out.append(result);print(json.dumps(result),flush=True)
(asr.ROOT/'data/reson-first20/speaker-diagnostics.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
