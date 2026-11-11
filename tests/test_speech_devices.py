import pytest
from services import local_speech
from providers.local_settings import LocalAIError


@pytest.mark.parametrize('requested,available,expected', [
    ('cpu', True, 'cpu'), ('cpu', False, 'cpu'),
    ('auto', True, 'cuda'), ('auto', False, 'cpu'), ('cuda', True, 'cuda')])
def test_device_policy(requested, available, expected):
    assert local_speech.select_device(requested, available) == expected


def test_explicit_cuda_does_not_silently_fall_back():
    with pytest.raises(LocalAIError) as error:
        local_speech.select_device('cuda', False)
    assert error.value.code == 'cuda_unavailable'


def test_bad_device_rejected():
    with pytest.raises(ValueError): local_speech.select_device('invented', True)


def test_readiness_reports_effective_devices_not_claimed_settings(monkeypatch):
    monkeypatch.setattr(local_speech, '_stt_device', 'cpu')
    monkeypatch.setattr(local_speech, '_tts_device', 'cuda')
    monkeypatch.setattr(local_speech, '_compute_type', 'int8')
    monkeypatch.setenv('LOCAL_STT_DEVICE', 'cuda')
    report=local_speech.readiness()
    assert report['stt_device']=='cpu' and report['tts_device']=='cuda'
    assert report['vad_device']=='cpu' and report['stt_compute_type']=='int8'
