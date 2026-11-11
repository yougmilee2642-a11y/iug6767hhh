from tests.test_dual_asr_api import call


def test_speaker_mode_all_is_forwarded_to_local_asr(call, monkeypatch):
    client, app, _, state = call
    received = []

    def fake_final(data, context, interaction_id, stream_id, speaker_mode='primary'):
        received.append(speaker_mode)
        return {'text': 'Решение обсудили', 'raw_text': 'Решение обсудили', 'final': True}

    monkeypatch.setattr(app.local_speech, 'transcribe_final', fake_final)
    response = client.post(
        '/api/transcribe',
        files={'file': ('meeting.wav', b'fake-audio')},
        data={'interaction_id': state['id'], 'mode': 'final', 'speaker_mode': 'all'},
    )

    assert response.status_code == 200
    assert received == ['all']


def test_speaker_mode_defaults_to_primary(call, monkeypatch):
    client, app, _, state = call
    received = []

    def fake_final(data, context, interaction_id, stream_id, speaker_mode='primary'):
        received.append(speaker_mode)
        return {'text': 'Решение обсудили', 'raw_text': 'Решение обсудили', 'final': True}

    monkeypatch.setattr(app.local_speech, 'transcribe_final', fake_final)
    response = client.post(
        '/api/transcribe',
        files={'file': ('call.wav', b'fake-audio')},
        data={'interaction_id': state['id'], 'mode': 'final'},
    )

    assert response.status_code == 200
    assert received == ['primary']


def test_all_mode_keeps_audio_without_calling_primary_filter(monkeypatch):
    from services import dual_asr

    audio = object()
    monkeypatch.setattr(dual_asr, 'filter_speaker', lambda *_: (_ for _ in ()).throw(AssertionError('filter must be skipped')))

    kept, metadata = dual_asr.apply_speaker_mode(audio, 'meeting', [], 'all')

    assert kept is audio
    assert metadata == {'status': 'all_speakers', 'filter_applied': False}


def test_primary_mode_still_calls_existing_speaker_filter(monkeypatch):
    from services import dual_asr

    audio = object()
    expected = (audio, {'status': 'matched'})
    calls = []
    monkeypatch.setattr(dual_asr, 'filter_speaker', lambda *args: calls.append(args) or expected)

    result = dual_asr.apply_speaker_mode(audio, 'call', ['speech'], 'primary')

    assert result == expected
    assert calls == [(audio, 'call', ['speech'])]
