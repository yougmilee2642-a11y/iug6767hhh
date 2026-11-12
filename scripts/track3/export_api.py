"""Export actual meeting routes without loading model weights or touching data/."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def schema():
    # Import the real product, not a second implementation of its API contract.
    with tempfile.TemporaryDirectory(prefix='fotoprint-openapi-') as temporary:
        path = Path(temporary).resolve() / 'schema.db'
        os.environ.update(MEETINGS_DB_PATH=str(path), MEETINGS_DEMO_USERS='false',
                          CALLWISE_LOCAL_ONLY='true', TELEGRAM_ENABLED='false',
                          CALLWISE_CLOUD_INTEGRATIONS_ENABLED='false', OLLAMA_API_KEY='',
                          OLLAMA_BASE_URL='http://127.0.0.1:1')
        from scripts.track3.start import configure
        configure(path)
        import app
        from fastapi.openapi.utils import get_openapi
        from meetings.auth import COOKIE
        result = get_openapi(title='Фокус — Track 3 v2', version='2.0-prototype',
                             description=f'Срез реальных /api/meet маршрутов; авторизация cookie {COOKIE}.',
                             routes=[route for route in app.app.routes
                                     if getattr(route, 'path', '').startswith('/api/meet/')])
        result['servers'] = [{'url': 'http://127.0.0.1:8000'}]
        from meetings import store
        store.reset_cache()
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = schema()
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'paths': len(result['paths']), 'output': args.output}))


if __name__ == '__main__':
    main()
