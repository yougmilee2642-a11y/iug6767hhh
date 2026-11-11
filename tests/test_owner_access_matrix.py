"""Security regression matrix for the single-owner local cabinet."""
import pytest
from fastapi.testclient import TestClient
import app
from services import owner_access


def _clear_attempts():
    with owner_access._lock:
        owner_access._attempts.clear()


@pytest.mark.parametrize('path,headers,status', [
    ('/api/config', {'host':'evil.example'}, 400),
    ('/api/config', {'origin':'https://evil.example'}, 403),
    ('/api/config', {'sec-fetch-site':'cross-site'}, 403),
])
def test_rejected_requests_have_no_store_and_security_headers(path, headers, status, monkeypatch):
    monkeypatch.setenv('CALLWISE_OWNER_PASSWORD','')
    response=TestClient(app.app).get(path,headers=headers)
    assert response.status_code==status
    assert response.headers.get('cache-control')=='no-store'
    assert response.headers.get('x-content-type-options')=='nosniff'
    assert response.headers.get('referrer-policy')=='no-referrer'
    assert response.headers.get('x-frame-options')=='DENY'


def test_owner_cookie_tamper_and_short_password_fail_closed(monkeypatch):
    monkeypatch.setenv('CALLWISE_OWNER_PASSWORD','synthetic-owner-password')
    _clear_attempts()
    client=TestClient(app.app)
    login=client.post('/api/access/login',json={'password':'synthetic-owner-password'})
    assert login.status_code==200
    assert client.get('/api/config').status_code==200
    cookie=client.cookies.get(owner_access.COOKIE)
    client.cookies.set(owner_access.COOKIE, cookie[:-1] + ('0' if cookie[-1] != '0' else '1'))
    assert client.get('/api/config').status_code==401
    client.cookies.clear()
    monkeypatch.setenv('CALLWISE_OWNER_PASSWORD','short')
    assert client.post('/api/access/login',json={'password':'short'}).status_code==503
    _clear_attempts()


def test_logout_expires_owner_cookie(monkeypatch):
    monkeypatch.setenv('CALLWISE_OWNER_PASSWORD','synthetic-owner-password')
    _clear_attempts()
    client=TestClient(app.app)
    assert client.post('/api/access/login',json={'password':'synthetic-owner-password'}).status_code==200
    assert client.post('/api/access/logout').status_code==200
    assert client.get('/api/config').status_code==401
    _clear_attempts()


def test_login_redirect_has_security_headers(monkeypatch):
    monkeypatch.setenv('CALLWISE_OWNER_PASSWORD','synthetic-owner-password')
    response=TestClient(app.app).get('/',follow_redirects=False)
    assert response.status_code==303 and response.headers['location']=='/login'
    assert response.headers['cache-control']=='no-store'
    assert response.headers['x-frame-options']=='DENY'
