"""Run checks with temporary DBs, including app.py's import-time cabinet DB."""
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))


def main():
    os.chdir(ROOT)
    with tempfile.TemporaryDirectory(prefix='track3-check-') as temp:
        os.environ.update(MEETINGS_DB_PATH=str(Path(temp)/'meetings.db'), MEETINGS_SECRET='isolated-ci-not-production',
                          TELEGRAM_ENABLED='false', CALLWISE_CLOUD_INTEGRATIONS_ENABLED='false', TRACK3_REAL_OLLAMA='0')
        import storage
        storage.DB_PATH = Path(temp)/'cabinet.db'
        storage.DATA_DIR = Path(temp)
        import pytest
        return pytest.main(sys.argv[1:] or ['-q','tests/test_meetings.py','tests/test_meeting_voice.py',
                                           'tests/test_meeting_voice_mode.py','tests/test_llm_gateway.py','tests/test_track3_release__.py','tests/test_track3_llm__.py'])


if __name__ == '__main__':
    raise SystemExit(main())
