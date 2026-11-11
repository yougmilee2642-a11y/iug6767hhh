"""Local meeting voice routing tests use fakes and never load speech models."""


def test_local_speech_passes_all_mode_to_dual_asr_and_closes_stream(monkeypatch):
    from services import dual_asr, local_speech

    calls = []
    monkeypatch.setattr(local_speech, 'load_models', lambda: None)
    monkeypatch.setattr(
        dual_asr,
        'final',
        lambda *args, **kwargs: calls.append(('final', args, kwargs)) or {'text': 'все голоса'},
    )
    monkeypatch.setattr(dual_asr, 'close_stream', lambda *args: calls.append(('close', args)))

    result = local_speech.transcribe_final(b'waveform', 'контекст', 'meeting', 'chunk-1', speaker_mode='all')

    assert result['text'] == 'все голоса'
    assert calls[0][2]['speaker_mode'] == 'all'
    assert calls[1] == ('close', ('meeting', 'chunk-1'))
