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


def test_meeting_capture_requires_explicit_consent(call, monkeypatch):
    client, _, _, _ = call

    response = client.post(
        '/api/transcribe',
        files={'file': ('meeting.wav', b'fake-audio')},
        data={'mode': 'final', 'speaker_mode': 'all'},
    )

    assert response.status_code == 403
    assert 'согласны' in response.json()['detail']


def test_attested_meeting_capture_uses_all_speakers_without_conversation(call, monkeypatch):
    client, app, _, _ = call
    monkeypatch.setenv('CALLWISE_CONVERSATION_SAFETY', 'true')
    from contextlib import nullcontext
    from meetings import auth, store

    monkeypatch.setattr(auth, 'user_from_request', lambda _request: {'id': 42})
    monkeypatch.setattr(store, 'db', lambda: nullcontext(object()))
    monkeypatch.setattr(store, 'can_read_meeting', lambda _connection, _user_id, meeting_id: meeting_id == 7)
    calls = []

    def fake_final(data, context, interaction_id, stream_id, speaker_mode='primary'):
        calls.append((interaction_id, speaker_mode))
        return {'text': 'Обсудили план', 'raw_text': 'Обсудили план', 'final': True}

    monkeypatch.setattr(app.local_speech, 'transcribe_final', fake_final)
    response = client.post(
        '/api/transcribe',
        files={'file': ('meeting.wav', b'fake-audio')},
        data={'mode': 'final', 'speaker_mode': 'all', 'meeting_consent': 'true', 'meeting_id': '7'},
    )

    assert response.status_code == 200
    assert calls == [('', 'all')]


def test_meeting_capture_requires_a_valid_signed_in_meeting_user(call, monkeypatch):
    client, app, _, _ = call
    from contextlib import nullcontext
    from meetings import auth, store

    monkeypatch.setattr(auth, 'user_from_request', lambda _request: None)
    monkeypatch.setattr(store, 'db', lambda: nullcontext(object()))
    monkeypatch.setattr(store, 'can_read_meeting', lambda *_: True)
    monkeypatch.setattr(app.local_speech, 'transcribe_final', lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('must not transcribe')))

    response = client.post(
        '/api/transcribe',
        files={'file': ('meeting.wav', b'fake-audio')},
        data={'mode': 'final', 'speaker_mode': 'all', 'meeting_consent': 'true', 'meeting_id': '7'},
    )

    assert response.status_code == 401


def test_meeting_capture_requires_access_to_the_meeting(call, monkeypatch):
    client, app, _, _ = call
    from contextlib import nullcontext
    from meetings import auth, store

    monkeypatch.setattr(auth, 'user_from_request', lambda _request: {'id': 42})
    monkeypatch.setattr(store, 'db', lambda: nullcontext(object()))
    monkeypatch.setattr(store, 'can_read_meeting', lambda *_: False)
    monkeypatch.setattr(app.local_speech, 'transcribe_final', lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('must not transcribe')))

    response = client.post(
        '/api/transcribe',
        files={'file': ('meeting.wav', b'fake-audio')},
        data={'mode': 'final', 'speaker_mode': 'all', 'meeting_consent': 'true', 'meeting_id': '7'},
    )

    assert response.status_code == 404


def test_meeting_consent_does_not_bypass_conversation_policy(call, monkeypatch):
    client, app, _, state = call
    monkeypatch.setenv('CALLWISE_CONVERSATION_SAFETY', 'true')
    monkeypatch.setattr(app.local_speech, 'transcribe_final', lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('must not transcribe')))

    response = client.post(
        '/api/transcribe',
        files={'file': ('meeting.wav', b'fake-audio')},
        data={'interaction_id': state['id'], 'mode': 'final', 'speaker_mode': 'all', 'meeting_consent': 'true'},
    )

    assert response.status_code == 403
