"""Token-protected gateway in front of the local Ollama, for teammates.

Ollama's API has no authentication, so it must never be exposed directly.
This gateway listens on a chosen address, checks `Authorization: Bearer <token>`
in constant time and forwards only the read/inference endpoints Фокус needs
to the loopback Ollama. Model management (pull/delete/create/push/copy) and
`:cloud` models are refused.

Run (usually through start-gateway.ps1):
    python scripts/llm_gateway.py --host 100.x.y.z --port 11500

The token is taken from CALLWISE_GATEWAY_TOKEN, else from secrets/llm_gateway.token
(created on first run; the secrets/ folder is git-ignored).
"""
import argparse
import asyncio
import contextlib
import hmac
import json
import os
import secrets
import sys
import time
from pathlib import Path

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

ROOT = Path(__file__).resolve().parent.parent
TOKEN_FILE = ROOT / 'secrets' / 'llm_gateway.token'
UPSTREAM = os.getenv('CALLWISE_GATEWAY_UPSTREAM', 'http://127.0.0.1:11434').rstrip('/')
MAX_BODY = int(os.getenv('CALLWISE_GATEWAY_MAX_BODY', str(4 * 1024 * 1024)))
TIMEOUT = float(os.getenv('CALLWISE_GATEWAY_TIMEOUT', '300'))
# Inference + read-only metadata. Everything else (pull, delete, create, push, copy, blobs) is refused.
ALLOWED = {('POST', '/api/chat'), ('POST', '/api/generate'), ('POST', '/api/embed'), ('POST', '/api/embeddings'),
           ('POST', '/api/show'), ('GET', '/api/tags'), ('GET', '/api/version'), ('GET', '/api/ps')}
MIN_TOKEN_LEN = 24


def load_token():
    token = os.getenv('CALLWISE_GATEWAY_TOKEN', '').strip()
    if token:
        if len(token) < MIN_TOKEN_LEN: sys.exit(f'CALLWISE_GATEWAY_TOKEN должен быть не короче {MIN_TOKEN_LEN} символов.')
        return token
    if TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text(encoding='utf-8').strip()
        if len(token) >= MIN_TOKEN_LEN: return token
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    TOKEN_FILE.write_text(token + '\n', encoding='utf-8')
    print(f'Создан новый ключ шлюза: {TOKEN_FILE}')
    return token


def error(status, message):
    return JSONResponse({'error': message}, status_code=status)


def authorized(request, token):
    header = request.headers.get('authorization', '')
    scheme, _, value = header.partition(' ')
    return scheme.lower() == 'bearer' and hmac.compare_digest(value.strip().encode(), token.encode())


def model_refused(body):
    try: data = json.loads(body or b'{}')
    except ValueError: return 'Некорректный JSON.'
    if not isinstance(data, dict): return 'Некорректный JSON.'
    model = data.get('model') or data.get('name') or ''
    if isinstance(model, str) and (model.endswith(':cloud') or '-cloud' in model): return 'Облачные модели через шлюз запрещены.'
    return None


def build_app(token, client=None):
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT, connect=5), trust_env=False, follow_redirects=False)

    async def proxy(request: Request):
        path = request.url.path
        if (request.method, path) == ('GET', '/healthz'): return JSONResponse({'ok': True})
        if not authorized(request, token):
            await asyncio.sleep(0.5)  # slow down guessing; the token itself is 256-bit
            return error(401, 'Нужен ключ шлюза (Authorization: Bearer ...).')
        if (request.method, path) not in ALLOWED: return error(403, 'Этот метод Ollama через шлюз недоступен.')
        if int(request.headers.get('content-length') or 0) > MAX_BODY: return error(413, 'Слишком большой запрос.')
        body = await request.body()
        if len(body) > MAX_BODY: return error(413, 'Слишком большой запрос.')
        if request.method == 'POST' and (refusal := model_refused(body)): return error(400, refusal)
        started = time.monotonic()
        try:
            upstream = client.build_request(request.method, UPSTREAM + path, content=body or None,
                                            headers={'content-type': 'application/json'} if body else None)
            response = await client.send(upstream, stream=True)
        except httpx.HTTPError:
            return error(502, 'Ollama на хосте недоступна. Запустите start-gateway.ps1 / Ollama.')
        client_ip = request.client.host if request.client else '?'
        print(f'{time.strftime("%H:%M:%S")} {client_ip} {request.method} {path} -> {response.status_code}', flush=True)

        async def body_iter():
            try:
                async for chunk in response.aiter_bytes(): yield chunk
            finally:
                await response.aclose()
                print(f'    {path} готово за {time.monotonic() - started:.1f} с', flush=True)

        return StreamingResponse(body_iter(), status_code=response.status_code,
                                 media_type=response.headers.get('content-type', 'application/json'))

    routes = [Route('/{path:path}', proxy, methods=['GET', 'POST', 'PUT', 'DELETE', 'HEAD', 'PATCH'])]

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        yield
        await client.aclose()

    return Starlette(routes=routes, lifespan=lifespan)


def main():
    parser = argparse.ArgumentParser(description='Шлюз Фокус к локальной Ollama с ключом.')
    parser.add_argument('--host', default='127.0.0.1', help='Адрес прослушивания (IP Tailscale или 127.0.0.1 для туннеля).')
    parser.add_argument('--port', type=int, default=11500)
    parser.add_argument('--show-token', action='store_true', help='Показать ключ и выйти.')
    args = parser.parse_args()
    token = load_token()
    if args.show_token:
        print(token)
        return
    if args.host in {'0.0.0.0', '::'}:
        print('Внимание: шлюз слушает все сетевые интерфейсы. Доступ защищён только ключом.')
    print(f'Шлюз LLM: http://{args.host}:{args.port} -> {UPSTREAM}')
    uvicorn.run(build_app(token), host=args.host, port=args.port, log_level='warning', proxy_headers=False)


if __name__ == '__main__':
    main()
