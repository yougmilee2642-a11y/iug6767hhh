"""Isolated browser QA: deterministic model, temporary SQLite, no outbound mail."""
import sys
import gc
import os
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['TELEGRAM_ENABLED'] = 'false'
os.environ['CALLWISE_OWNER_PASSWORD'] = ''
import storage


if __name__ == '__main__':
    import uvicorn
    from fastapi.responses import HTMLResponse
    with tempfile.TemporaryDirectory(prefix='focus-track1-browser-') as directory:
        storage.DATA_DIR = Path(directory)
        storage.DB_PATH = storage.DATA_DIR / 'smoke.sqlite'
        import app
        from test_track1_quick import IntakeProvider
        app.get_provider = IntakeProvider
        app.send_application_email = lambda *_: False

        @app.app.middleware('http')
        async def identify_test_provider(request, call_next):
            response = await call_next(request)
            if request.url.path == '/':
                body = b''.join([chunk async for chunk in response.body_iterator]).decode('utf-8')
                body = body.replace('<main class="workspace">', '<main class="workspace"><p class="track1-notice">СТЕНД QA: модель имитируется, данные синтетические, база временная. Это не проверка качества Groq.</p>')
                return HTMLResponse(body)
            return response

        uvicorn.run(app.app, host='127.0.0.1', port=8013)
        gc.collect()
