import importlib.util
import json
from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient

from providers.local_settings import LocalAIError
from providers.ollama import OllamaProvider, endpoint

TOKEN = 'synthetic-gateway-token-0123456789abcdef'
spec = importlib.util.spec_from_file_location('llm_gateway', Path(__file__).resolve().parent.parent / 'scripts' / 'llm_gateway.py')
gateway = importlib.util.module_from_spec(spec); spec.loader.exec_module(gateway)


@pytest.fixture
def upstream_calls():
    return []


@pytest.fixture
def client(upstream_calls):
    def upstream(request):
        upstream_calls.append((request.method, request.url.path, request.headers.get('authorization')))
        if request.url.path == '/api/tags': return httpx.Response(200, json={'models': [{'name': 'qwen3:4b'}]})
        return httpx.Response(200, json={'done': True, 'message': {'content': 'Готов.'}})
    fake = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    with TestClient(gateway.build_app(TOKEN, fake)) as test_client: yield test_client


def auth(token=TOKEN): return {'Authorization': f'Bearer {token}'}


def test_gateway_requires_token(client, upstream_calls):
    assert client.get('/api/tags').status_code == 401
    assert client.get('/api/tags', headers=auth('wrong-token-wrong-token-wrong')).status_code == 401
    assert upstream_calls == []
    assert client.get('/healthz').json() == {'ok': True}


def test_gateway_forwards_inference_without_leaking_token(client, upstream_calls):
    reply = client.post('/api/chat', headers=auth(), json={'model': 'qwen3:4b', 'messages': []})
    assert reply.status_code == 200 and reply.json()['message']['content'] == 'Готов.'
    assert upstream_calls == [('POST', '/api/chat', None)]


@pytest.mark.parametrize('method,path', [('POST', '/api/pull'), ('DELETE', '/api/delete'), ('POST', '/api/create'), ('POST', '/api/push')])
def test_gateway_blocks_model_management(client, upstream_calls, method, path):
    assert client.request(method, path, headers=auth(), json={'model': 'x'}).status_code == 403
    assert upstream_calls == []


def test_gateway_blocks_cloud_models(client, upstream_calls):
    assert client.post('/api/chat', headers=auth(), json={'model': 'gpt-oss:120b-cloud'}).status_code == 400
    assert client.post('/api/chat', headers=auth(), json={'model': 'qwen3:480b:cloud'}).status_code == 400
    assert upstream_calls == []


@pytest.mark.parametrize('url,key,allowed', [
    ('http://127.0.0.1:11434', '', True),
    ('http://100.101.102.103:11500', TOKEN, True),
    ('http://leha-pc.tailabcd.ts.net:11500', TOKEN, True),
    ('https://abc.trycloudflare.com', TOKEN, True),
    ('https://abc.trycloudflare.com', '', False),          # remote needs a key
    ('https://abc.trycloudflare.com', 'short', False),
    ('http://203.0.113.5:11500', TOKEN, False),             # plain HTTP over the internet
    ('http://192.168.1.20:11500', TOKEN, False),
    ('https://user:pw@abc.trycloudflare.com', TOKEN, False),
])
def test_remote_endpoint_policy(monkeypatch, url, key, allowed):
    monkeypatch.setenv('OLLAMA_BASE_URL', url)
    monkeypatch.setenv('OLLAMA_API_KEY', key)
    assert (endpoint() is not None) is allowed


def test_provider_sends_key_to_gateway(monkeypatch):
    monkeypatch.setenv('OLLAMA_BASE_URL', 'http://100.101.102.103:11500')
    monkeypatch.setenv('OLLAMA_API_KEY', TOKEN)
    seen = []
    def reply(request):
        seen.append((str(request.url), request.headers.get('authorization')))
        if request.url.path == '/api/tags': return httpx.Response(200, json={'models': [{'name': 'qwen3:4b'}]})
        return httpx.Response(200, json={'done': True, 'message': {'content': 'Готов.'}})
    provider = OllamaProvider(transport=httpx.MockTransport(reply), model='qwen3:4b')
    assert provider.available()
    assert provider.complete([], []).text == 'Готов.'
    assert seen == [('http://100.101.102.103:11500/api/tags', f'Bearer {TOKEN}'),
                    ('http://100.101.102.103:11500/api/chat', f'Bearer {TOKEN}')]
    assert provider.metadata()['remote_gateway'] is True


def test_provider_refuses_remote_without_key(monkeypatch):
    monkeypatch.setenv('OLLAMA_BASE_URL', 'http://100.101.102.103:11500')
    monkeypatch.delenv('OLLAMA_API_KEY', raising=False)
    with pytest.raises(LocalAIError): OllamaProvider().complete([], [])
