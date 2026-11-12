import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
import app as app_module
import storage
from prompts import load_agent, build_system_prompt, build_transcription_prompt
from agents.models import AgentConfig
from providers.base import ModelReply


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    storage.initialize_db()
    monkeypatch.setattr(app_module, "send_application_email", lambda *_: False)
    return TestClient(app_module.app)


class FakeGroq:
    def __init__(self, transcript=""):
        self.audio = SimpleNamespace(transcriptions=SimpleNamespace(create=lambda **_: SimpleNamespace(text=transcript)))


class FakeProvider:
    def complete(self, messages, tools):
        return ModelReply("Назовите телефон для связи.")


def test_default_config_is_available(client):
    response = client.get("/api/config")
    assert response.status_code == 200
    assert response.json()["business_name"] == "Линия — демо-салон"
    assert response.json()["language"] == "ru"
    assert "car" not in response.json()


def test_root_has_branded_social_metadata(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Фокус" in response.text
    assert '<meta property="og:title" content="Фокус' in response.text
    assert '<meta name="twitter:card" content="summary">' in response.text
    assert "/static/og.png" not in response.text
    assert ">RU<" in response.text
    assert "AutoFix" not in response.text


def test_health_does_not_expose_secrets(client, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "secret-test-token")
    response = client.get("/api/health")
    assert response.status_code == 200
    assert set(response.json()) == {"status", "groq_configured", "smtp_configured", "business_configured", "ai_provider", "local_only", "local_speech", "model", "llm_ready"}
    assert "secret-test-token" not in response.text


def test_company_form_changes_ai_context(client):
    config = client.get("/api/config").json()
    config.update(business_name="Новый салон", knowledge_base="Без выдуманных скидок.", custom_questions=[
        {"id": "allergy", "label": "Аллергия", "question": "Есть ли аллергия?", "required": True}
    ])
    response = client.put("/api/config", json=config)
    assert response.status_code == 200
    agent = load_agent(response.json())
    prompt = build_system_prompt(agent)
    assert "Новый салон" in prompt and "Есть ли аллергия" in prompt and "Без выдуманных скидок" in prompt
    assert "маникюр" in build_transcription_prompt(agent)


def test_application_schema_uses_custom_question_ids(client):
    agent = client.get("/api/agent").json()
    agent["fields"].append({"id": "allergy", "label": "Аллергия", "question": "Есть ли аллергия?", "required": False})
    config = AgentConfig.model_validate(agent)
    assert config.fields[-1].id == "allergy"
    assert "car" not in {field.id for field in config.fields}


def test_chat_returns_reply_and_completion_state(client, monkeypatch):
    monkeypatch.setattr(app_module, "get_provider", lambda: FakeProvider())
    identifier = client.post("/api/conversations").json()["interaction_id"]
    response = client.post("/api/chat", json={"interaction_id": identifier, "text": "Меня зовут Лёша"})
    assert response.status_code == 200
    assert response.json()["text"] == "Назовите телефон для связи."
    assert response.json()["complete"] is False


def test_transcription_preserves_russian_names(client, monkeypatch):
    monkeypatch.setattr(app_module, "client", lambda: FakeGroq("Лёша, хочу маникюр"))
    response = client.post("/api/transcribe", files={"file": ("voice.webm", b"not-empty", "audio/webm")})
    assert response.status_code == 200
    assert response.json()["text"] == "Лёша, хочу маникюр"


def test_phone_context_converts_spoken_digits(client, monkeypatch):
    monkeypatch.setattr(app_module, "client", lambda: FakeGroq("один два три четыре пять шесть семь восемь девять"))
    response = client.post("/api/transcribe", data={"context": "Назовите телефон"},
                           files={"file": ("voice.webm", b"not-empty", "audio/webm")})
    assert response.status_code == 200
    assert response.json()["text"] == "123456789"


def test_completed_application_is_persisted(client, monkeypatch):
    monkeypatch.setattr(app_module, "get_provider", lambda: FakeProvider())
    identifier = client.post("/api/conversations").json()["interaction_id"]
    client.post("/api/chat", json={"interaction_id": identifier, "text": "Нужна консультация"})
    response = client.post("/api/application", json={"interaction_id": identifier})
    assert response.status_code == 200
    assert response.json()["status"] == "stopped"
    saved = client.get("/api/applications").json()["items"]
    assert saved[0]["id"] == identifier
    assert saved[0]["transcript"][-2]["content"] == "Нужна консультация"
    assert "car" not in saved[0]


def test_voice_script_has_no_fixed_eight_second_limit():
    script = (Path(__file__).parents[1] / "static" / "app.js").read_text(encoding="utf-8")
    assert "recordTimeout" not in script and "8000" not in script
    assert "performance.now() - lastDetectedVoice > endSilenceMs" in script


def test_validation_errors_are_russian(client):
    assert "Проверьте" in client.put("/api/config", json={}).json()["detail"]


def test_speech_uses_russian_voice(client, monkeypatch):
    voices = []
    class FakeSpeech:
        def __init__(self, text, voice, **kwargs):
            voices.append(voice)
        async def stream(self):
            yield {"type": "audio", "data": b"mock-mp3"}
    monkeypatch.setattr(app_module.edge_tts, "Communicate", FakeSpeech)
    monkeypatch.setenv("TTS_VOICE", "pl-PL-ZofiaNeural")
    response = client.post("/api/speech", json={"text": "Здравствуйте!"})
    assert response.status_code == 200 and voices == ["ru-RU-SvetlanaNeural"]
    assert response.headers["content-type"] == "audio/mpeg"


def test_email_error_does_not_lose_escalation(client, monkeypatch):
    def fail(*_):
        raise OSError("secret credential info")
    monkeypatch.setattr(app_module, "send_application_email", fail)
    identifier = client.post("/api/conversations").json()["interaction_id"]
    response = client.post("/api/chat", json={"interaction_id": identifier, "text": "Оператор"})
    assert response.json()["status"] == "escalated"
    assert "secret credential" not in response.text
    assert response.json()["interaction"]["email_error"]
    assert storage.get_interaction(identifier)["escalation"]


def test_request_retry_is_idempotent(client, monkeypatch):
    monkeypatch.setattr(app_module, "get_provider", lambda: FakeProvider())
    identifier = client.post("/api/conversations").json()["interaction_id"]
    payload = {"interaction_id": identifier, "text": "Лёша", "request_id": "turn-1"}
    first = client.post("/api/chat", json=payload)
    second = client.post("/api/chat", json=payload)
    assert first.json() == second.json()
    assert len(storage.get_interaction(identifier)["transcript"]) == 3


def test_legacy_history_remains_available(client):
    storage.save_application({"name": "Архивный клиент", "car": "BMW", "problem": "Архив"}, [])
    history = client.get("/api/applications").json()["items"]
    assert history[0]["agent_id"] == "legacy-autofix"
    assert history[0]["structured_data"]["Автомобиль (архив)"] == "BMW"
