"""Legacy Orbita live probe; --track3 dispatches to frozen Photoprint evaluation.

Both use temporary DBs. Neither falls back to a scripted model.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    if '--track3' in sys.argv:
        sys.argv.remove('--track3')
        from scripts.track3.evaluate import main as evaluate
        return evaluate()
    with tempfile.TemporaryDirectory(prefix='orbita-live-') as temp:
        path=Path(temp)/'live.db'
        os.environ['MEETINGS_DB_PATH']=str(path)
        from scripts.track3.start import configure
        configure(path)
        from fastapi.testclient import TestClient
        from scripts.seed_meetings_demo import seed
        ids=seed(with_transcript=True)
        import app
        with TestClient(app.app) as c:
            login=c.post('/api/meet/login',json={'login':'irina','password':'irina-demo'})
            login.raise_for_status()
            ok=True
            for step in ('protocol/draft','prepare'):
                start=time.perf_counter()
                r=c.post(f"/api/meet/meetings/{ids['launch_meeting']}/{step}")
                print(json.dumps({'step':step,'status':r.status_code,'seconds':time.perf_counter()-start,'response':r.json()},ensure_ascii=False))
                ok=ok and r.status_code==200
            return 0 if ok else 2


if __name__=='__main__': raise SystemExit(main())
