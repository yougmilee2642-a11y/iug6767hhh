"""Run the existing product app with explicit isolated databases and no voice warmup."""
import argparse
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.track3.paths import explicit_db


def configure(path):
    os.environ.update(MEETINGS_DB_PATH=str(path), CALLWISE_LOCAL_ONLY='true', AI_PROVIDER='ollama',
                      TELEGRAM_ENABLED='false', CALLWISE_CLOUD_INTEGRATIONS_ENABLED='false')
    # .env cannot override these explicit environment values; main storage is redirected
    # before app.py's import-time initialize_db. No source app/provider file is modified.
    import storage
    storage.DB_PATH = path.with_name(path.stem+'.cabinet.db')
    storage.DATA_DIR = path.parent
    if not os.getenv('MEETINGS_SECRET'):
        key = path.with_suffix('.session.key')
        if not key.exists():
            key.write_text(secrets.token_hex(32))
            key.chmod(0o600)
        os.environ['MEETINGS_SECRET'] = key.read_text().strip()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',required=True)
    p.add_argument('--port',type=int,default=8000)
    a = p.parse_args()
    path = explicit_db(a.db)
    marker = Path(str(path)+'.track3.json')
    if not path.is_file() or not marker.is_file():
        p.error('Run scripts/track3/seed.py --db first')
    configure(path)
    import app
    import uvicorn
    uvicorn.run(app.app,host='127.0.0.1',port=a.port)


if __name__ == '__main__':
    main()
