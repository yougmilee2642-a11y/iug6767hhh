"""Opt-in synthetic text smoke, isolated DB, at most six real Groq HTTP attempts.

Run: python tests/live_track1_smoke.py
Never sends email, invokes TTS, or alters the working application database.
"""
import json
import gc
from contextlib import closing
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
import storage
from agents.runtime import new_interaction
from agents.factory import create_runtime
from providers.groq import GroqProvider
from providers.errors import ProviderError
from evaluation.providers import Budget
from services.track1_service import make_config, QuickInput


def main():
    load_dotenv(ROOT / '.env')
    if not os.getenv('GROQ_API_KEY', '').strip():
        print(json.dumps({'status': 'blocked', 'reason': 'missing_key'}))
        return 2
    budget = Budget(6)
    with tempfile.TemporaryDirectory(prefix='callwise-live-intake-') as directory:
        storage.DATA_DIR = Path(directory)
        storage.DB_PATH = storage.DATA_DIR / 'synthetic.sqlite'
        storage.initialize_db()
        config = make_config(QuickInput(business_name='Синтетический QA', facts='Создаём сайты.'), 'live_qa')
        provider = GroqProvider(budget=budget)
        runtime = create_runtime(config, provider)
        state = new_interaction(config)
        try:
            for text, expected in [('Алексей', 'in_progress'), ('+375290000000', 'in_progress'),
                                   ('Хочу обсудить создание сайта.', 'awaiting_confirmation'), ('Да', 'completed')]:
                runtime.turn(state, text)
                # Intermediate statuses are allowed to evolve; confirmation/completion are mandatory.
                if expected in {'awaiting_confirmation', 'completed'} and state['status'] != expected:
                    print(json.dumps({'status': 'failed', 'stage': expected,
                                      'actual_status': state['status'], 'requests': budget.requests}))
                    return 1
            with closing(storage.connect()) as db:
                count = db.execute('SELECT COUNT(*) FROM callback_requests').fetchone()[0]
            passed = count == 1 and not state.get('email_sent')
            print(json.dumps({'status': 'passed' if passed else 'failed', 'requests': budget.requests,
                              'callback_count': count, 'database': 'temporary', 'mode': 'live_text_only'}))
            return 0 if passed else 1
        except ProviderError as exc:
            print(json.dumps({'status': 'blocked', 'category': exc.category, 'requests': budget.requests}))
            return 2
        except RuntimeError:
            print(json.dumps({'status': 'failed', 'reason': 'runtime_or_request_limit', 'requests': budget.requests}))
            return 1
        finally:
            # sqlite context managers commit/rollback but do not close connections.
            # Collect temporary connection cycles before Windows removes the sandbox.
            gc.collect()


if __name__ == '__main__':
    raise SystemExit(main())
