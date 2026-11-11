"""P1-03: phone/negation/amount handling, silence and noise, STT and Ollama failures."""
import pytest

from providers.language import normalize_transcript

PHONE_CONTEXT = 'Назовите номер телефона.'


def test_single_digit_phone_is_joined_across_pauses():
    assert normalize_transcript('три семь пять, два девять, один два три четыре пять шесть семь', PHONE_CONTEXT) == '375291234567'


def test_phone_with_tens_and_hundreds_is_not_half_converted():
    # "двадцать девять" is not a digit word: rewriting only the tail would give a plausible but WRONG number.
    text = 'плюс триста семьдесят пять двадцать девять один один один два два три три'
    assert normalize_transcript(text, PHONE_CONTEXT) == text


def test_amounts_and_negation_are_never_rewritten():
    for text in ['пятьдесят рублей пять', 'Я не хочу доставку', 'не нужно перезванивать, нет нет']:
        assert normalize_transcript(text, PHONE_CONTEXT) == text


def test_digits_are_not_joined_when_phone_was_not_asked():
    assert normalize_transcript('три семь пять', 'Как вас зовут?') == 'три семь пять'


@pytest.fixture
def client_state(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app
    import storage
    from agents.runtime import new_interaction
    from prompts import load_agent
    monkeypatch.setenv('CALLWISE_LOCAL_ONLY', 'true')
    monkeypatch.setattr(storage, 'DB_PATH', tmp_path / 'test.db')
    monkeypatch.setattr(storage, 'DATA_DIR', tmp_path)
    storage.initialize_db()
    state = new_interaction(load_agent(storage.get_config()))
    storage.save_interaction(state)
    monkeypatch.setattr(app, 'uses_local_ai', lambda: True)
    return TestClient(app.app), state, app, storage


def _wav():
    import io, wave
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(16000); out.writeframes(b'\0\0' * 16000)
    return buffer.getvalue()


def test_silence_or_noise_returns_empty_text_and_creates_no_turn(client_state, monkeypatch):
    client, state, app, storage = client_state
    monkeypatch.setattr(app.local_speech, 'transcribe_final', lambda *args: {'raw_text':'','text':''})
    monkeypatch.setattr(app, 'runtime', lambda *_: pytest.fail('silence must not reach the Runtime'))
    response = client.post('/api/transcribe', files={'file': ('v.wav', _wav(), 'audio/wav')}, data={'interaction_id': state['id']})
    assert response.status_code == 200 and response.json()['text'] == ''
    assert storage.get_interaction(state['id'])['transcript'] == state['transcript']
    # list_applications returns every interaction, so compare with the pre-call state instead of expecting [].
    assert [(i['id'], i['status']) for i in storage.list_applications(10)] == [(state['id'], state['status'])]
    import sqlite3
    with sqlite3.connect(storage.DB_PATH) as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert 'callback_requests' not in tables or db.execute('SELECT COUNT(*) FROM callback_requests').fetchone()[0] == 0


def test_stt_failure_is_an_explicit_error_not_partial_text(client_state, monkeypatch):
    client, state, app, _ = client_state
    def broken(*_args, **_kwargs):
        raise RuntimeError('decoder crashed')
    monkeypatch.setattr(app.local_speech, 'transcribe_final', broken)
    response = client.post('/api/transcribe', files={'file': ('v.wav', _wav(), 'audio/wav')}, data={'interaction_id': state['id']})
    assert response.status_code == 422 and 'text' not in response.json()


def test_missing_local_models_report_503(client_state, monkeypatch):
    client, state, app, _ = client_state
    from providers.local_settings import LocalAIError
    def missing(*_args, **_kwargs):
        raise LocalAIError('Локальные модели недоступны')
    monkeypatch.setattr(app.local_speech, 'transcribe_final', missing)
    response = client.post('/api/transcribe', files={'file': ('v.wav', _wav(), 'audio/wav')}, data={'interaction_id': state['id']})
    assert response.status_code == 503


def test_ollama_off_gives_503_and_no_completed_application(client_state, monkeypatch):
    client, state, app, storage = client_state
    from providers.local_settings import LocalAIError

    class Down:
        def turn(self, *_args, **_kwargs):
            raise LocalAIError('Ollama недоступна')
    monkeypatch.setattr(app, 'runtime', lambda *_: Down())
    response = client.post('/api/chat', json={'interaction_id': state['id'], 'text': 'Меня зовут Анна', 'request_id': 'r1'})
    assert response.status_code == 503
    saved = storage.get_interaction(state['id'])
    assert saved['status'] not in {'completed', 'escalated'}


def test_tts_failure_is_502_so_the_call_continues_in_text(client_state, monkeypatch):
    client, _state, app, _ = client_state
    def broken(_text):
        raise RuntimeError('tts crashed')
    monkeypatch.setattr(app.local_speech, 'synthesize_local', broken)
    assert client.post('/api/speech', json={'text': 'Здравствуйте'}).status_code == 502
