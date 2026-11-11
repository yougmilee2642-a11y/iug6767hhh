import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv()
from services import local_speech,dual_asr
from benchmark_reson20 import align
ROOT=dual_asr.ROOT
entries=json.loads((ROOT/'data/reson-first20/selection.json').read_text(encoding='utf-8'))
results=[]
for number in (1,6,9,6):
    entry=entries[number-1]
    # Last replay uses the same enrolled identity as the first case 6.
    result=local_speech.transcribe_final((ROOT/'downloads/reson-first20'/entry['file_name']).read_bytes(),interaction_id=f'focus:{number}')
    score=align(entry['text'],result['raw_text'])
    row={'number':number,'wer':score['wer'],'hypothesis':result['raw_text'],'speaker':result.get('speaker')}
    results.append(row);print(json.dumps(row,ensure_ascii=True),flush=True)
    assert score['exact'],f'Focused case {number} regressed'
(ROOT/'data/reson-speaker-fix/focus.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
