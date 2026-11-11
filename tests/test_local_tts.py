import io

import pytest

np=pytest.importorskip('numpy')
sf=pytest.importorskip('soundfile')
torch=pytest.importorskip('torch')

from services import local_speech


@pytest.fixture
def fake_tts(monkeypatch):
    class Model:
        speakers=['xenia','baya']
        calls=[]

        def apply_tts(self, **kwargs):
            self.calls.append(kwargs)
            return torch.zeros(kwargs['sample_rate']//10)

    model=Model()
    monkeypatch.setattr(local_speech,'load_models',lambda:None)
    monkeypatch.setattr(local_speech,'_tts',model)
    monkeypatch.delenv('LOCAL_TTS_SAMPLE_RATE',raising=False)
    monkeypatch.setenv('LOCAL_TTS_SPEAKER','xenia')
    return model


def test_spoken_copy_and_wav_use_prepared_text_and_matching_rate(fake_tts):
    original='**МТС**: тест. Наберите *100#.'
    audio=local_speech.synthesize_local(original)
    call=fake_tts.calls[0]
    assert original=='**МТС**: тест. Наберите *100#.'
    assert call['text']=='+эм т+э +эс: т+ест. Наберите звёздочка один ноль ноль решётка.'
    assert call['speaker']=='xenia' and call['sample_rate']==48000
    assert all(call[key] is True for key in ['put_accent','put_yo','put_stress_homo','put_yo_homo'])
    decoded,rate=sf.read(io.BytesIO(audio))
    assert rate==48000 and len(decoded)==4800 and np.all(decoded==0)


@pytest.mark.parametrize('rate',[8000,24000,48000])
def test_explicit_sample_rate_is_used_in_synthesis_and_wav(fake_tts,monkeypatch,rate):
    monkeypatch.setenv('LOCAL_TTS_SAMPLE_RATE',str(rate))
    audio=local_speech.synthesize_local('Здравствуйте!')
    decoded,wav_rate=sf.read(io.BytesIO(audio))
    assert fake_tts.calls[0]['sample_rate']==rate==wav_rate
    assert len(decoded)==rate//10


def test_installed_voice_can_be_selected(fake_tts,monkeypatch):
    monkeypatch.setenv('LOCAL_TTS_SPEAKER','baya')
    local_speech.synthesize_local('Здравствуйте!')
    assert fake_tts.calls[0]['speaker']=='baya'


@pytest.mark.parametrize('rate',['22050','bad'])
def test_bad_rate_does_not_call_model(fake_tts,monkeypatch,rate):
    monkeypatch.setenv('LOCAL_TTS_SAMPLE_RATE',rate)
    with pytest.raises(ValueError):local_speech.synthesize_local('МТС')
    assert not fake_tts.calls


def test_unknown_voice_is_not_silently_replaced(fake_tts,monkeypatch):
    monkeypatch.setenv('LOCAL_TTS_SPEAKER','missing')
    with pytest.raises(ValueError,match='LOCAL_TTS_SPEAKER'):
        local_speech.synthesize_local('МТС')
    assert not fake_tts.calls


def test_markup_only_is_rejected_before_model_call(fake_tts):
    with pytest.raises(ValueError):local_speech.synthesize_local('<break time="99s"/>')
    assert not fake_tts.calls
