"""Execute installed speech models on CUDA with synthetic audio, no customer data."""
import json
import os
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ.update(LOCAL_STT_DEVICE='cuda',LOCAL_STT_COMPUTE_TYPE='int8_float16',LOCAL_TTS_DEVICE='cuda',
                  HF_HUB_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1')
from services import local_speech


def main():
    import torch
    assert torch.cuda.is_available(), 'Install CUDA PyTorch in the project venv first'
    local_speech.warm_up()
    times=[]
    for _ in range(3):
        began=time.perf_counter();wav=local_speech.synthesize_local('Какое кодовое слово команды?')
        tts=time.perf_counter()-began
        began=time.perf_counter();text=local_speech.transcribe_local(wav)
        stt=time.perf_counter()-began
        assert text.strip(), 'Speech round trip produced no transcript'
        times.append({'tts_seconds':round(tts,3),'stt_seconds':round(stt,3),'recognized':text})
    report={'torch':torch.__version__,'cuda':torch.version.cuda,'gpu':torch.cuda.get_device_name(0),
            'speech':local_speech.readiness(),'runs':times,'synthetic':True}
    assert report['speech']['stt_device']=='cuda' and report['speech']['tts_device']=='cuda'
    target=ROOT/'proof/phone-gpu/speech-check.json';target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
