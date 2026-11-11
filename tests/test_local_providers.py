import json
import os
import pytest
import httpx
from fastapi.testclient import TestClient
import app
import storage
from providers.base import ConversationMessage, ToolCall, ToolSpec
from providers.ollama import OllamaProvider, encode_messages
from providers.local_settings import LocalAIError


@pytest.fixture
def local(monkeypatch,tmp_path):
    monkeypatch.setenv('CALLWISE_LOCAL_ONLY','true')
    monkeypatch.setenv('AI_PROVIDER','ollama')
    monkeypatch.setenv('OLLAMA_BASE_URL','http://127.0.0.1:11434')
    monkeypatch.setattr(storage,'DB_PATH',tmp_path/'test.sqlite')
    monkeypatch.setattr(storage,'DATA_DIR',tmp_path)
    storage.initialize_db()


def test_native_tools_and_no_thinking(local):
    seen=[]
    def reply(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200,json={'done':True,'message':{'content':'','thinking':'must not leak',
            'tool_calls':[{'function':{'name':'save_test','arguments':{'name':'Алексей'}}}]}})
    provider=OllamaProvider(transport=httpx.MockTransport(reply),model='qwen3:4b')
    result=provider.complete([ConversationMessage('user','Алексей')],[ToolSpec('save_test','Test',{'type':'object'})])
    assert result.tool_calls[0].arguments=={'name':'Алексей'}
    assert result.text=='' and seen[0]['think'] is False
    assert seen[0]['model']=='qwen3:4b'
    assert seen[0]['stream'] is False and provider.metadata()['provider']=='Ollama'


def test_default_and_configured_local_model(monkeypatch):
    monkeypatch.delenv('OLLAMA_MODEL',raising=False)
    assert OllamaProvider().model=='qwen3:4b-instruct'
    monkeypatch.setenv('OLLAMA_MODEL','another-local-model:latest')
    assert OllamaProvider().model=='another-local-model:latest'
    assert OllamaProvider(model='qwen3:4b').model=='qwen3:4b'


@pytest.mark.parametrize('content', ['<think>private reasoning</think>Готов.', 'private reasoning</think>Готов.'])
def test_reasoning_prefix_never_reaches_voice(local,content):
    provider=OllamaProvider(transport=httpx.MockTransport(lambda r: httpx.Response(200,json={
        'done':True,'message':{'content':content}})))
    assert provider.complete([],[]).text=='Готов.'


def test_unfinished_thinking_block_is_rejected(local):
    provider=OllamaProvider(transport=httpx.MockTransport(lambda r: httpx.Response(200,json={
        'done':True,'message':{'content':'<think>unfinished reasoning'}})))
    with pytest.raises(LocalAIError): provider.complete([],[])


def test_tool_result_maps_name_not_groq_id():
    messages=[ConversationMessage('assistant',calls=[ToolCall('id1','test',{})]),ConversationMessage('tool',call_id='id1',result={'ok':True})]
    output=encode_messages(messages)
    assert output[1]['tool_name']=='test' and 'tool_call_id' not in output[1]


def test_local_url_cannot_send_prompt_elsewhere(local,monkeypatch):
    monkeypatch.setenv('OLLAMA_BASE_URL','https://external.example')
    with pytest.raises(LocalAIError): OllamaProvider().complete([],[])


@pytest.mark.parametrize('reply',[{'done':True,'message':{'content':''}}, {'done':True,'done_reason':'length','message':{'content':'truncated'}},
    {'done':True,'message':{'tool_calls':[{'function':{'name':'invented','arguments':{}}}]}}])
def test_invalid_local_response_has_no_fallback(local,reply):
    provider=OllamaProvider(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=reply)))
    with pytest.raises(LocalAIError): provider.complete([],[])
    assert provider.request_count==1


def test_all_cloud_entrypoints_blocked(local,monkeypatch):
    monkeypatch.setenv('GROQ_API_KEY','synthetic-key-not-real')
    monkeypatch.setenv('TELEGRAM_ENABLED','true')
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','synthetic-token')
    from providers.groq import groq_client,GroqProvider
    from services.telegram_bot import TelegramClient
    from services.telegram_store import enabled
    from services.notifications import send_application_email
    from evaluation.providers import live_agent_provider
    assert not enabled() and not send_application_email({}, {})
    for invoke in [groq_client,lambda:GroqProvider().complete([],[]),lambda:TelegramClient().call('getMe'),lambda:live_agent_provider(None)]:
        with pytest.raises(LocalAIError): invoke()
    assert isinstance(app.get_provider(),OllamaProvider)


def test_local_speech_endpoints_do_not_touch_cloud(local,monkeypatch):
    monkeypatch.setattr(app.local_speech,'transcribe_local',lambda *args:'Тестовый текст')
    monkeypatch.setattr(app.local_speech,'synthesize_local',lambda text:b'RIFFtest')
    monkeypatch.setattr(app,'client',lambda:pytest.fail('Cloud STT attempted'))
    monkeypatch.setattr(app.edge_tts,'Communicate',lambda *args,**kwargs:pytest.fail('Cloud TTS attempted'))
    client=TestClient(app.app)
    assert client.post('/api/transcribe',files={'file':('test.wav',b'audio','audio/wav')}).json()['text']=='Тестовый текст'
    response=client.post('/api/speech',json={'text':'Здравствуйте'})
    assert response.status_code==200 and response.headers['content-type']=='audio/wav'
    assert client.get('/miniapp').status_code==503
    # Missing agent is rejected before model calls; local Evaluation now uses Ollama.
    assert client.post('/api/evaluations',json={'agent_id':'test'}).status_code==404


def test_local_failure_not_reported_as_missing_groq(local,monkeypatch):
    class Failed:
        def complete(self,*args): raise LocalAIError('unavailable')
    monkeypatch.setattr(app,'get_provider',Failed)
    client=TestClient(app.app)
    cid=client.post('/api/conversations',json={}).json()['interaction_id']
    response=client.post('/api/chat',json={'interaction_id':cid,'text':'Здравствуйте'})
    assert response.status_code==503 and 'Ollama' in response.json()['detail']
    assert storage.get_interaction(cid)['transcript'][-1]['content']=='Здравствуйте'
