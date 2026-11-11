"""Single-owner gate, not multi-tenancy. Local-only when password is unset."""
import hashlib
import hmac
import os
import secrets
import threading
import time
from urllib.parse import urlsplit
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

COOKIE = 'callwise_owner'
_attempts, _lock = {}, threading.Lock()
PUBLIC_PATHS = {'/login','/api/access/login','/miniapp','/api/miniapp/profile','/api/miniapp/register'}


def password():
    return os.getenv('CALLWISE_OWNER_PASSWORD', '')


def signature(text):
    key = hashlib.sha256(('callwise-owner-session-v1\0' + password()).encode()).digest()
    return hmac.new(key,text.encode(),hashlib.sha256).hexdigest()


def _security_headers(response, path=''):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    if path != '/miniapp': response.headers['X-Frame-Options'] = 'DENY'
    return response


def _blocked(detail, status_code, path=''):
    return _security_headers(JSONResponse({'detail': detail}, status_code=status_code), path)


def authenticated(request):
    value = request.cookies.get(COOKIE,'')
    if not value or not password(): return False
    try:
        expiry,nonce,digest = value.split('.')
        return time.time() < int(expiry) <= time.time()+28800 and hmac.compare_digest(digest,signature(f'{expiry}.{nonce}'))
    except (ValueError,TypeError): return False


async def guard(request: Request, call_next):
    host = request.url.hostname
    peer = request.client.host if request.client else ''
    configured_origin = os.getenv('PUBLIC_ORIGIN','http://127.0.0.1:8000').rstrip('/')
    permitted = {'127.0.0.1','localhost','::1',urlsplit(configured_origin).hostname}
    if peer == 'testclient': permitted.add('testserver')
    mini_origin = urlsplit(os.getenv('TELEGRAM_MINIAPP_URL','')).hostname
    if mini_origin: permitted.add(mini_origin)
    if host not in permitted:
        return _blocked('Недопустимый Host.', 400, request.url.path)
    origin = request.headers.get('origin')
    public_navigation = request.method == 'GET' and (request.url.path in {'/miniapp','/login'} or request.url.path.startswith('/static/'))
    # Reject cross-site reads too: protects against local HTTP requests from other sites.
    if (request.headers.get('sec-fetch-site') == 'cross-site' and not public_navigation) or (origin and origin != str(request.base_url).rstrip('/') and not public_navigation):
        return _blocked('Cross-site запрос запрещён.', 403, request.url.path)
    public = request.url.path in PUBLIC_PATHS or request.url.path.startswith('/static/')
    local = peer in {'127.0.0.1','::1','testclient'} and host in {'127.0.0.1','localhost','::1','testserver'}
    if not local and request.url.scheme != 'https':
        return _blocked('Для удалённого доступа обязателен HTTPS.', 503, request.url.path)
    configured = password()
    if not public:
        if not configured and not local:
            return _blocked('Без пароля доступен только локальный стенд.', 503, request.url.path)
        if configured and (len(configured)<12 or not authenticated(request)):
            if request.url.path == '/': return _security_headers(RedirectResponse('/login',status_code=303), request.url.path)
            return _blocked('Требуется вход владельца.', 401, request.url.path)
    response = await call_next(request)
    return _security_headers(response, request.url.path)


class Login(BaseModel):
    password: str = Field(min_length=1,max_length=300)


def router():
    api = APIRouter()

    @api.post('/api/access/login')
    def login(payload: Login, request: Request):
        configured = password()
        if len(configured)<12:
            raise HTTPException(503,'Задайте CALLWISE_OWNER_PASSWORD длиной от 12 символов в .env и перезапустите сервер.')
        peer = request.client.host if request.client else 'unknown'
        with _lock:
            now = time.time()
            for address in list(_attempts):
                _attempts[address] = [t for t in _attempts[address] if t > now-300]
                if not _attempts[address]: del _attempts[address]
            if len(_attempts.get(peer,[]))>=5:
                raise HTTPException(429,'Слишком много попыток входа. Подождите 5 минут.')
            if not hmac.compare_digest(payload.password.encode(),configured.encode()):
                _attempts.setdefault(peer,[]).append(now)
                raise HTTPException(401,'Неверный пароль.')
            _attempts.pop(peer,None)
        value = f'{int(time.time()+28800)}.{secrets.token_hex(16)}'
        response = JSONResponse({'ok':True})
        response.set_cookie(COOKIE,value+'.'+signature(value),max_age=28800,httponly=True,samesite='strict',secure=request.url.scheme=='https')
        return response

    @api.get('/api/access/status')
    def status(): return {'mode':'single_owner' if password() else 'localhost_only'}

    @api.post('/api/access/logout')
    def logout():
        response = JSONResponse({'ok':True})
        response.delete_cookie(COOKIE)
        return response

    return api
