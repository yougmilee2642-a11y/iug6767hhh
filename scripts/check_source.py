"""Portable source checks in temporary storage, never the owner's business DB."""
import gc
import os
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));os.chdir(ROOT)
os.environ.update(CALLWISE_LOCAL_ONLY='false',AI_PROVIDER='groq',TELEGRAM_ENABLED='false',BUSINESS_EMAIL='')
for key in list(os.environ):
    if key.startswith('CALLWISE_LIVE') or key.startswith('RUN_LIVE'):
        os.environ.pop(key)


def no_external_network(event,args):
    if event=='socket.connect' and isinstance(args[1],tuple) and args[1][0] not in ('127.0.0.1','localhost','::1'):
        raise RuntimeError('External network is disabled in source checks')


if __name__=='__main__':
    sys.addaudithook(no_external_network)
    import storage
    with tempfile.TemporaryDirectory(prefix='focus-source-check-') as folder:
        storage.DATA_DIR=Path(folder);storage.DB_PATH=Path(folder)/'startup.sqlite'
        import pytest
        code=pytest.main(sys.argv[1:] or ['-q'])
        gc.collect()
    raise SystemExit(code)
