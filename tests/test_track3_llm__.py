import json

import httpx
import pytest

from meetings.llm import MeetingLLM
from providers import ollama
from providers.local_settings import LocalAIError

TOKEN = 'synthetic-gateway-token-0123456789'
SCHEMA = {'type':'object','properties':{'ok':{'type':'boolean'}}}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for k in ('OLLAMA_BASE_URL','OLLAMA_API_KEY','MEETINGS_MODEL'):
        monkeypatch.delenv(k,raising=False)


@pytest.mark.parametrize('base', ['http://127.0.0.1:11434','http://[::1]:11434','https://gateway.example',
                                 'http://100.101.102.103:11500','http://host.tailnet.ts.net:11500'])
def test_shared_policy_and_bearer_payload(monkeypatch,base):
    monkeypatch.setenv('OLLAMA_BASE_URL',base)
    monkeypatch.setenv('OLLAMA_API_KEY',TOKEN)
    seen = []
    def reply(r):
        seen.append(r)
        return httpx.Response(200,json={'done':True,'message':{'content':'{"ok":true}'}})
    llm = MeetingLLM(transport=httpx.MockTransport(reply))
    assert llm.json('rules','data',SCHEMA,predict=321) == {'ok':True}
    assert str(seen[0].url)==base+'/api/chat'
    assert seen[0].headers['Authorization']=='Bearer '+TOKEN
    payload=json.loads(seen[0].content)
    assert payload['format']==SCHEMA and payload['think'] is False and payload['stream'] is False
    assert payload['options']=={'num_ctx':8192,'num_predict':321,'temperature':0.1}


def test_defaults_and_delegates_to_one_policy(monkeypatch):
    monkeypatch.setattr(ollama,'endpoint',lambda:('http://127.0.0.1:11434',{}))
    assert MeetingLLM()._base()=='http://127.0.0.1:11434'
    monkeypatch.setattr(ollama,'endpoint',lambda:None)
    with pytest.raises(LocalAIError): MeetingLLM()._base()


@pytest.mark.parametrize('base,key', [('http://example.com',TOKEN),('https://example.com',''),
                                     ('http://192.168.1.1',TOKEN),('https://example.com/api',TOKEN),
                                     ('https://u:p@example.com',TOKEN),('http://127.0.0.1?x=y',''),
                                     ('http://127.0.0.1#frag',''),('http://[broken','')])
def test_denied_before_any_request(monkeypatch,base,key):
    monkeypatch.setenv('OLLAMA_BASE_URL',base);monkeypatch.setenv('OLLAMA_API_KEY',key)
    def never(_): raise AssertionError('No request allowed')
    with pytest.raises(LocalAIError): MeetingLLM(transport=httpx.MockTransport(never)).json('s','u',SCHEMA)


@pytest.mark.parametrize('model',['qwen:cloud','QWEN:CLOUD','qwen-cloud:latest','qwen:cloud-latest'])
def test_cloud_blocked(model):
    with pytest.raises(LocalAIError) as e: MeetingLLM(model=model)._base()
    assert e.value.code=='cloud_disabled'


def test_client_ignores_env_proxy_and_redirect(monkeypatch):
    import meetings.llm as module
    real = httpx.Client
    settings = {}
    def client(**kwargs):
        settings.update(kwargs)
        return real(**kwargs)
    monkeypatch.setattr(module.httpx,'Client',client)
    monkeypatch.setenv('HTTPS_PROXY','http://invalid.proxy:9')
    requests=[]
    def redirect(r):
        requests.append(str(r.url));return httpx.Response(302,headers={'Location':'https://evil.example'})
    with pytest.raises(LocalAIError): MeetingLLM(transport=httpx.MockTransport(redirect)).json('s','u',SCHEMA)
    assert len(requests)==1 and settings['trust_env'] is False and settings['follow_redirects'] is False


@pytest.mark.parametrize('body',[{'done':False,'message':{'content':'{}'}}, {'done':True,'done_reason':'length'},
                                 [],{'done':True,'message':{'content':'[]'}},{'done':True,'message':{'content':'bad'}}])
def test_invalid_replies(body):
    with pytest.raises(LocalAIError) as e:
        MeetingLLM(transport=httpx.MockTransport(lambda _:httpx.Response(200,json=body))).json('s','u',SCHEMA)
    assert e.value.code=='invalid_reply'


def test_timeout():
    def fail(r): raise httpx.ReadTimeout('test',request=r)
    with pytest.raises(LocalAIError) as e: MeetingLLM(transport=httpx.MockTransport(fail)).json('s','u',SCHEMA)
    assert e.value.code=='timeout'


def test_invalid_url_maps_to_safe_unavailable(monkeypatch):
    monkeypatch.setenv('OLLAMA_BASE_URL','https://gateway.example:bad')
    monkeypatch.setenv('OLLAMA_API_KEY',TOKEN)
    with pytest.raises(LocalAIError) as e: MeetingLLM().json('s','u',SCHEMA)
    assert e.value.code=='unavailable'
