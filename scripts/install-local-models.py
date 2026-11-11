"""One-time download only. Runtime never downloads models automatically."""
import hashlib
import json
import os
import sys
import subprocess
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
os.environ['HF_HUB_DOWNLOAD_TIMEOUT']='180'
os.environ['HF_HUB_ETAG_TIMEOUT']='60'
# The installation stage is explicitly online, unlike the application runtime.
os.environ.pop('HF_HUB_OFFLINE',None)
os.environ.pop('TRANSFORMERS_OFFLINE',None)


def main():
    tts=ROOT/'models/silero/v5_ru.pt'
    tts.parent.mkdir(parents=True,exist_ok=True)
    if not tts.is_file():
        print('Downloading official Silero v5_ru weights...',flush=True)
        urllib.request.urlretrieve('https://models.silero.ai/models/tts/ru/v5_ru.pt',tts)
    print('Silero weights available',flush=True)
    subprocess.run([sys.executable,str(ROOT/'scripts/install_dual_asr.py')],check=True)
    print('T-one, GigaAM and speaker models available',flush=True)
    return 0


if __name__=='__main__':
    try: raise SystemExit(main())
    except Exception as exc:
        print('Model installation failed: '+type(exc).__name__,file=sys.stderr)
        raise SystemExit(1)
