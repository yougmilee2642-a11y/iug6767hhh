"""P1-02: access matrix for the single-owner gate. This is NOT tenant isolation: one owner, one password.

Every rejected request must leave draft, applications and conversations unchanged (no side effects).
"""
import logging
import re
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as app_module
import storage
from services import owner_access

PASSWORD = 'correct-horse-battery'
ROOT = Path(__file__).resolve().parents[1]
GUARDED_GET = ['/api/track1/draft', '/api/applications', '/api/config', '/api/agent']


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'DB_PATH', tmp_path / 'access.sqlite')
    monkeypatch.setattr(storage, 'DATA_DIR', tmp_path)
    storage.initialize_db()
    monkeypatch.setattr(app_module, 'send_application_email', lambda *_: False)
    owner_access._attempts.clear()
    yield monkeypatch
    owner_access._attempts.clear()


def locked(env):
    env.setenv('CALLWISE_OWNER_PASSWORD', PASSWORD)
    return TestClient(app_module.app)


def login(client, password=PASSWORD):
    return client.post('/api/access/login', json={'password': password})


def snapshot(client):
    """State read as the owner; a fresh authenticated client so the checked client keeps its own cookies."""
    owner = TestClient(app_module.app)
    assert login(owner).status_code == 200
    return owner.get('/api/track1/draft').json()['revision'], owner.get('/api/applications').json()


def test_without_password_stand_is_local_only_and_login_is_unavailable(env):
    client = TestClient(app_module.app)
    assert client.get('/api/access/status').json() == {'mode': 'localhost_only'}
    assert login(client).status_code == 503


def test_password_set_every_guarded_route_needs_a_cookie(env):
    client = locked(env)
    assert client.get('/api/access/status').status_code == 401  # status itself needs the cookie once a password is set
    for path in GUARDED_GET:
        assert client.get(path).status_code == 401, path
    assert client.get('/', follow_redirects=False).status_code == 303


def test_login_logout_cycle(env):
    client = locked(env)
    assert login(client, 'wrong-password').status_code == 401 and not client.cookies.get(owner_access.COOKIE)
    assert login(client).status_code == 200 and client.cookies.get(owner_access.COOKIE)
    assert client.get('/api/track1/draft').status_code == 200
    client.post('/api/access/logout'); client.cookies.clear()
    assert client.get('/api/track1/draft').status_code == 401


def test_tampered_expired_and_overlong_cookies_are_rejected(env):
    client = locked(env)
    assert login(client).status_code == 200
    good = client.cookies.get(owner_access.COOKIE)
    forged = good[:-1] + ('0' if good[-1] != '0' else '1')
    expired = f'{int(time.time()) - 10}.' + 'a' * 32
    overlong = f'{int(time.time()) + 90000}.' + 'b' * 32
    for value in (forged, expired + '.' + owner_access.signature(expired), overlong + '.' + owner_access.signature(overlong), 'garbage'):
        client.cookies.clear(); client.cookies.set(owner_access.COOKIE, value)
        assert client.get('/api/track1/draft').status_code == 401


def test_login_attempts_are_limited_even_for_the_right_password(env):
    client = locked(env)
    for _ in range(5):
        assert login(client, 'nope-nope-nope').status_code == 401
    assert login(client).status_code == 429


def test_wrong_host_cross_site_and_foreign_origin_are_blocked(env):
    client = locked(env)
    assert login(client).status_code == 200
    assert client.get('/api/track1/draft', headers={'host': 'evil.example'}).status_code == 400
    assert client.get('/api/applications', headers={'sec-fetch-site': 'cross-site'}).status_code == 403
    assert client.get('/api/applications', headers={'origin': 'http://evil.example'}).status_code == 403


def test_remote_plain_http_is_refused(env):
    env.setenv('PUBLIC_ORIGIN', 'http://owner.example')
    env.setenv('CALLWISE_OWNER_PASSWORD', PASSWORD)
    remote = TestClient(app_module.app, base_url='http://owner.example')
    assert remote.get('/api/access/status').status_code == 503


def test_rejected_writes_have_no_side_effects(env):
    client = locked(env)
    before = snapshot(client)
    draft = {'expected_revision': 0, 'data': {'business_name': 'Чужой'}}
    # 1) no cookie  2) valid cookie but foreign Origin  3) valid cookie but cross-site
    assert client.put('/api/track1/draft', json=draft).status_code == 401
    assert client.post('/api/conversations', json={}).status_code == 401
    assert client.post('/api/chat', json={'text': 'Меня зовут X, телефон +375291112233'}).status_code == 401
    assert client.post('/api/track1/preview', json={'business_name': 'Чужой'}).status_code == 401
    assert login(client).status_code == 200
    assert client.put('/api/track1/draft', json=draft, headers={'origin': 'http://evil.example'}).status_code == 403
    assert client.post('/api/chat', json={'text': 'x'}, headers={'sec-fetch-site': 'cross-site'}).status_code == 403
    assert snapshot(client) == before


def test_client_code_and_archive_contain_no_secrets():
    pattern = re.compile(r'(gsk_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|\d{8,10}:AA[A-Za-z0-9_-]{30,})')
    hits = [str(p.relative_to(ROOT)) for p in (ROOT / 'static').rglob('*')
            if p.is_file() and p.suffix in {'.js', '.mjs', '.html', '.css', '.json'} and pattern.search(p.read_text('utf-8', 'ignore'))]
    assert hits == []
    # A working checkout may legitimately have .env; exclusion is checked on the built ZIP.


def database_dump():
    """Every table, every row, of EVERY sqlite file next to the main DB (core, workspace draft, evaluation, outbox):
    a rejected request must leave all of them byte-identical."""
    parts = []
    for path in sorted(Path(storage.DB_PATH).parent.glob('*.sqlite')):
        with sqlite3.connect(path) as db:
            parts.append(path.name + '\n' + '\n'.join(db.iterdump()))
    return '\n'.join(parts)


def _walk(routes, prefix=''):
    """Flatten routes. Newer FastAPI keeps include_router() results as lazy _IncludedRouter entries in app.routes,
    so a plain loop over app.routes would silently skip every included router (track1, builder, evaluation, telegram...)."""
    for route in routes:
        if hasattr(route, 'original_router'):  # _IncludedRouter
            yield from _walk(route.original_router.routes, prefix + (route.include_context.prefix or ''))
            continue
        methods = set(getattr(route, 'methods', None) or ()) - {'HEAD', 'OPTIONS'}
        path = getattr(route, 'path', '')
        if methods:
            yield prefix + path, methods


def registered_routes():
    for path, methods in _walk(app_module.app.routes):
        if path not in owner_access.PUBLIC_PATHS:
            yield path, methods


def test_every_non_public_route_rejects_unauthenticated_requests_before_any_side_effect(env):
    """Sweeps ALL registered routes (old and new: draft, overview, knowledge, history, conversations,
    agents, evaluation, telegram, builder) so a route added later cannot silently bypass the gate."""
    client = locked(env)
    before = database_dump()
    checked = 0
    for path, methods in registered_routes():
        url = re.sub(r'\{[^}]+\}', 'x', path)
        for method in sorted(methods):
            response = client.request(method, url, json={}, follow_redirects=False)
            # HTML entry page redirects to /login (303); every API route answers 401. Nothing else is acceptable.
            expected = {401, 303} if (method, path) == ('GET', '/') else {401}
            assert response.status_code in expected, f'{method} {path} -> {response.status_code}'
            checked += 1
    assert checked >= 40  # 43 non-public routes today; the old loop saw only 17 because it skipped included routers
    covered = {p for p, _ in registered_routes()}
    for needle in ('/api/track1/draft', '/api/agents', '/api/access/logout', '/api/evaluation', '/api/telegram'):
        assert any(c.startswith(needle) for c in covered), f'sweep does not reach {needle}'
    assert database_dump() == before


def test_rejected_cross_site_and_foreign_host_requests_leave_the_database_identical(env):
    client = locked(env)
    assert login(client).status_code == 200
    before = database_dump()
    attacks = [{'origin': 'http://evil.example'}, {'sec-fetch-site': 'cross-site'}, {'host': 'evil.example'}]
    for headers in attacks:
        for method, url in [('PUT', '/api/track1/draft'), ('POST', '/api/chat'), ('POST', '/api/conversations'),
                            ('POST', '/api/application'), ('POST', '/api/track1/agents')]:
            assert client.request(method, url, json={}, headers=headers).status_code in {400, 403}, (method, url, headers)
    assert database_dump() == before


def test_authenticated_owner_reaches_new_and_old_apis(env):
    client = locked(env)
    assert login(client).status_code == 200
    for path in ['/api/track1/draft', '/api/track1/overview', '/api/applications', '/api/config', '/api/agent', '/api/agents']:
        assert client.get(path).status_code == 200, path
    assert client.post('/api/conversations', json={}).status_code == 200
    assert client.get('/api/access/status').json() == {'mode': 'single_owner'}  # single owner, explicitly not tenants


def test_wrong_password_and_cookie_never_reach_logs(env, caplog):
    client = locked(env)
    secret = 'wrong-password-12345'
    with caplog.at_level(logging.DEBUG):
        assert login(client, secret).status_code == 401
        assert login(client).status_code == 200
        client.get('/api/track1/draft')
    cookie = client.cookies.get(owner_access.COOKIE)
    text = caplog.text
    assert secret not in text and PASSWORD not in text and cookie not in text


def test_password_shorter_than_twelve_chars_locks_everything(env):
    env.setenv('CALLWISE_OWNER_PASSWORD', 'short')
    client = TestClient(app_module.app)
    assert login(client, 'short').status_code == 503
    assert client.get('/api/track1/draft').status_code == 401
