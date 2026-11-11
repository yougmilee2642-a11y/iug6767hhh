from datetime import datetime, timedelta
from agents import prompts
from services.local_speech import speech_window
from services.track1_service import QuickInput, make_config


def test_current_time_changes_without_invalidating_stable_prompt(monkeypatch):
    base = datetime(2026, 10, 13, 12, 0)
    times = iter([base, base + timedelta(seconds=1)])

    class Clock:
        @staticmethod
        def now(zone):
            return next(times).replace(tzinfo=zone)

    monkeypatch.setattr(prompts, 'datetime', Clock)
    config = make_config(QuickInput(business_name='Тест времени'), 'time_test')
    first, second = prompts.build_system_prompt(config), prompts.build_system_prompt(config)
    prefix, time_line = first.rsplit('\n\n', 1)
    assert second.rsplit('\n\n', 1)[0] == prefix
    assert first != second and time_line.startswith('Текущая дата и время бизнеса')
    for required in [prompts.identity(config), prompts.business_context(config),
                     prompts.scenario_rules(config), prompts.safety_rules(config)]:
        assert required in prefix


def test_speech_window_preserves_internal_pause_and_word_margins():
    audio = list(range(64000))
    window = speech_window(audio, [{'start':16000,'end':24000}, {'start':32000,'end':40000}])
    assert window == audio[12800:43200]
    assert 28000 in window  # Do not concatenate distinct spoken phrases.


def test_speech_window_never_wraps_or_exceeds_recording():
    audio = list(range(1000))
    assert speech_window(audio, [{'start':0,'end':1000}]) == audio


def test_llm_warmup_has_no_business_data_or_actions(monkeypatch):
    import json
    import httpx
    from providers.ollama import OllamaProvider
    monkeypatch.setenv('OLLAMA_BASE_URL','http://127.0.0.1:11434')
    requests=[]
    def reply(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200,json={'done':True,'message':{'content':'Готов.'}})
    provider=OllamaProvider(model='qwen2.5:3b',transport=httpx.MockTransport(reply))
    provider.warm_up()
    assert len(requests)==1 and 'tools' not in requests[0]
    assert requests[0]['options']['num_predict']==16
    assert all('Контекст бизнеса' not in message['content'] for message in requests[0]['messages'])


def test_unavailable_warmup_does_not_enable_cloud_fallback(monkeypatch):
    import asyncio
    import app
    from providers.local_settings import LocalAIError
    monkeypatch.setenv('CALLWISE_LOCAL_ONLY','true')
    monkeypatch.setenv('AI_PROVIDER','ollama')
    monkeypatch.setattr(app.local_speech,'readiness',lambda:{'stt_weights':False,'tts_weights':False})
    class Local:
        def available(self):return True
        def warm_up(self):raise LocalAIError('unavailable')
    monkeypatch.setattr(app,'OllamaProvider',Local)
    monkeypatch.setattr(app,'groq_client',lambda:(_ for _ in ()).throw(AssertionError('Cloud fallback')))
    async def start():
        async with app.lifespan(app.app):
            assert app.local_only()
    asyncio.run(start())
