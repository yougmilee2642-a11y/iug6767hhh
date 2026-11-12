"""Browser-origin guard and durable minute buckets; no credentials/IPs in audit."""
import hashlib
import os
import time
import uuid
from urllib.parse import urlsplit
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from meetings import store


def _limit(request,group):
    default=30 if group=='login' else 60
    try:limit=int(os.getenv('MEETINGS_RATE_LIMIT_'+group.upper(),str(default)))
    except ValueError:limit=default
    limit=max(1,min(limit,10000));bucket=int(time.time())//60
    key=hashlib.sha256((str(store.db_path().resolve())+'|'+str(request.client.host if request.client else '')+'|'+group).encode()).hexdigest()
    with store.write_tx() as c:
        c.execute('DELETE FROM security_limits WHERE bucket<?',(bucket-5,))
        c.execute('INSERT INTO security_limits VALUES (?,?,1) ON CONFLICT(key,bucket) DO UPDATE SET count=count+1',(key,bucket))
        count=c.execute('SELECT count FROM security_limits WHERE key=? AND bucket=?',(key,bucket)).fetchone()[0]
    return count<=limit


def install(app):
    @app.middleware('http')
    async def security(request,call_next):
        path=request.url.path
        protected=path.startswith('/api/meet/')
        response=None
        if protected and request.method not in ('GET','HEAD','OPTIONS'):
            origin=request.headers.get('origin')
            expected=os.getenv('MEETINGS_PUBLIC_ORIGIN','').rstrip('/') or str(request.base_url).rstrip('/')
            site=request.headers.get('sec-fetch-site','')
            # API/CLI callers without browser Origin/Fetch-Metadata remain supported.
            if site=='cross-site' or (origin and (origin.rstrip('/')!=expected or request.headers.get('x-focus-request')!='1')):
                response=JSONResponse({'code':'csrf_denied','detail':'Запрос не прошёл проверку источника. Обновите страницу.'},status_code=403)
                await run_in_threadpool(store.audit_independent,None,'csrf_denied',result='denied',object_type='web',error_code='csrf_denied')
        if protected and response is None and request.method=='POST':
            group='login' if path.endswith('/login') else 'qa' if path in ('/api/meet/qa','/api/meet/assistant/ask','/api/meet/voice/ask') else None
            if group and not await run_in_threadpool(_limit,request,group):
                response=JSONResponse({'code':'rate_limited','detail':'Слишком много запросов. Повторите через минуту.'},status_code=429,headers={'Retry-After':'60'})
                await run_in_threadpool(store.audit_independent,None,'rate_limited',result='denied',object_type='web',error_code='rate_limited')
        response=response if response is not None else await call_next(request)
        if protected:
            response.headers.setdefault('X-Request-ID',uuid.uuid4().hex)
        if protected or path=='/meetings':
            response.headers['X-Content-Type-Options']='nosniff'
            response.headers['Referrer-Policy']='same-origin'
            response.headers['X-Frame-Options']='DENY'
            response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
            response.headers['Cache-Control']='no-store'
        return response
