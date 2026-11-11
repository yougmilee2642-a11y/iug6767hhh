"""Opt-in real provider checks; isolated SQLite and disabled email."""
import os
import pytest
from fastapi.testclient import TestClient
import app as app_module
import storage

pytestmark = pytest.mark.skipif(os.getenv("CALLWISE_LIVE_TESTS") != "1", reason="Для реального Groq/TTS: CALLWISE_LIVE_TESTS=1")


@pytest.fixture
def live_client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "live.db")
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    storage.initialize_db()
    monkeypatch.setattr(app_module, "send_application_email", lambda *_: False)
    return TestClient(app_module.app)


def test_real_groq_booking_and_handoff(live_client):
    identifier = live_client.post("/api/conversations").json()["interaction_id"]
    phone_given = False
    for text in ["Хочу завтра после шести записаться на маникюр.", "Давайте на 18:30, мастер Анна.", "Меня зовут Алексей.", "Мой телефон +375291234567.", "На 18:30, мастер Анна.", "Выбираю предложенный слот на 18:30 с Анной."]:
        phone_given = phone_given or "телефон" in text.lower()
        response = live_client.post("/api/chat", json={"interaction_id": identifier, "text": text})
        assert response.status_code == 200, response.text
        data = response.json()
        print("AI:", data["text"])
        if data["status"] == "awaiting_confirmation":
            assert phone_given, "Нельзя подготовить запись с выдуманным телефоном до слов клиента"
            break
    assert data["status"] == "awaiting_confirmation", data
    assert any(e["name"] == "check_slots" for e in data["interaction"]["tool_events"])
    with storage.connect() as db:
        assert db.execute("SELECT count(*) FROM bookings").fetchone()[0] == 0
    response = live_client.post("/api/chat", json={"interaction_id": identifier, "text": "Да, подтверждаю."})
    assert response.json()["status"] == "completed", response.text
    with storage.connect() as db:
        assert db.execute("SELECT count(*) FROM bookings").fetchone()[0] == 1
    second = live_client.post("/api/conversations").json()["interaction_id"]
    response = live_client.post("/api/chat", json={"interaction_id": second, "text": "Соедините меня с человеком."})
    assert response.json()["status"] == "escalated", response.text


def test_real_russian_speech_to_transcription(live_client):
    audio = live_client.post("/api/speech", json={"text": "Хочу завтра после шести записаться на маникюр."})
    assert audio.status_code == 200, audio.text
    assert len(audio.content) > 1000
    response = live_client.post("/api/transcribe", files={"file": ("voice.mp3", audio.content, "audio/mpeg")})
    assert response.status_code == 200, response.text
    print("STT:", response.json()["text"])
    assert "маникюр" in response.json()["text"].lower()


def test_real_builder_nova_and_existing_runtime(live_client):
    from tests.test_builder import nova
    created = live_client.post('/api/builder/generate', json=nova())
    assert created.status_code == 200, created.text
    result = created.json()
    assert result['validation']['valid'], result['validation']
    print('Builder: valid, attempts=', result['attempts'])
    saved = live_client.post('/api/agents', json={k: result[k] for k in ['candidate_id', 'review_token']}).json()
    aid = saved['id']
    assert live_client.post(f'/api/agents/{aid}/activate', json={}).status_code == 200
    identifier = live_client.post('/api/conversations', json={'agent_id': aid}).json()['interaction_id']
    for text in ['Хочу завтра после шести на маникюр.', 'Выбираю 18:30, Анна.', 'Меня зовут Алексей.', 'Мой телефон +375291234567.', 'На 18:30, сотрудник Анна.', 'Выбираю предложенный слот на 18:30 с Анной.']:
        response = live_client.post('/api/chat', json={'interaction_id': identifier, 'text': text})
        assert response.status_code == 200, response.text
        data = response.json()
        print('Nova AI:', data['text'])
        if data['status'] == 'awaiting_confirmation': break
    assert data['status'] == 'awaiting_confirmation', data
    assert any(e['name'] == 'check_slots' for e in data['interaction']['tool_events'])
    response = live_client.post('/api/chat', json={'interaction_id': identifier, 'text': 'Да, подтверждаю.'})
    assert response.json()['status'] == 'completed', response.text
    with storage.connect() as db:
        row = dict(db.execute('SELECT * FROM bookings').fetchone())
        assert row['service'].startswith('service_') and row['employee'].startswith('business_')
        assert db.execute('SELECT agent_id FROM interactions WHERE id=?', (identifier,)).fetchone()[0] == aid
    second = live_client.post('/api/conversations', json={'agent_id': aid}).json()['interaction_id']
    response = live_client.post('/api/chat', json={'interaction_id': second, 'text': 'Я не хочу разговаривать с ботом. Дайте человека.'})
    assert response.json()['status'] == 'escalated', response.text


def test_generated_agent_real_speech_path(live_client):
    from tests.test_builder import nova, MockBuilder
    from builder.models import BusinessInput
    from builder.service import AgentBuilder
    from services.agent_service import AgentService
    builder = AgentBuilder(MockBuilder())
    candidate = builder.generate(BusinessInput.model_validate(nova()))
    saved = builder.save(candidate['candidate_id'], candidate['review_token'])
    AgentService().activate(saved['id'])
    identifier = live_client.post('/api/conversations', json={'agent_id': saved['id']}).json()['interaction_id']
    audio = live_client.post('/api/speech', json={'text': 'Хочу завтра после шести на маникюр.'})
    assert audio.status_code == 200 and len(audio.content) > 1000
    response = live_client.post('/api/transcribe', data={'interaction_id': identifier, 'context': 'Какую услугу выбираете?'},
        files={'file': ('voice.mp3', audio.content, 'audio/mpeg')})
    assert response.status_code == 200, response.text
    assert 'маникюр' in response.json()['text'].casefold()
    assert storage.get_interaction(identifier)['agent_id'] == saved['id']


def test_real_builder_sales_role_and_short_schedule(live_client):
    from tests.test_builder import nova
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    business = nova()
    business['desired_role'] = 'Менеджер по продажам'
    business['schedule'] = {str(d): [{'start':'16:00', 'end':'17:00'}] for d in range(7)}
    business['services'] = [{'name':'Консультация', 'price':10, 'currency':'BYN', 'duration_minutes':30, 'employees':['Анна']}]
    result = live_client.post('/api/builder/generate', json=business).json()
    assert result['validation']['valid'], result['validation']
    c = result['config']
    assert c['role']['name'] == 'Менеджер по продажам'
    assert c['role']['id'] != 'administrator' and 'администратор' not in c['greeting'].casefold()
    saved = live_client.post('/api/agents', json={k:result[k] for k in ['candidate_id','review_token']}).json()
    assert live_client.post(f"/api/agents/{saved['id']}/activate", json={}).status_code == 200
    session = live_client.post('/api/conversations', json={'agent_id':saved['id']}).json()
    day = (datetime.now(ZoneInfo('Europe/Minsk'))+timedelta(days=1)).date().isoformat()
    response = live_client.post('/api/chat', json={'interaction_id':session['interaction_id'],
        'text':f'Проверьте, пожалуйста, свободные слоты на консультацию {day} в 16:30 с Анной.'})
    assert response.status_code == 200, response.text
    data = response.json()
    events = [e for e in data['interaction']['tool_events'] if e['name']=='check_slots']
    assert events and any(s['datetime'][11:16]=='16:30' for e in events for s in e['result']['slots']), data
    print('Live sales Builder and short-window Runtime: passed; attempts=', result['attempts'])
