import io
import time
from types import SimpleNamespace

import numpy as np
import pytest
from services import dual_asr as asr


def segments(items):
    return SimpleNamespace(sort_by_start_time=lambda:[SimpleNamespace(start=a,end=b,speaker=s) for a,b,s in items])


@pytest.fixture
def speakers(monkeypatch):
    monkeypatch.setattr(asr,'_speakers',{})
    monkeypatch.setattr(asr,'_streams',{})
    monkeypatch.setattr(asr,'speaker_embedding',lambda audio:np.array([1.,0.],dtype=np.float32))


def test_multiple_initial_voices_request_repeat_instead_of_guessing(speakers,monkeypatch):
    monkeypatch.setattr(asr,'_diarizer',SimpleNamespace(process=lambda _:segments([(0,2,0),(2,4,1)])))
    audio,meta=asr.filter_speaker(np.ones(64000,dtype=np.float32),'call')
    assert not len(audio) and meta['requires_repeat']
    assert 'call' not in asr._speakers


def test_clear_dominant_first_voice_survives_brief_background(speakers,monkeypatch):
    monkeypatch.setattr(asr,'_diarizer',SimpleNamespace(process=lambda _:segments([(0,.6,1),(1,5,0)])))
    audio,meta=asr.filter_speaker(np.ones(80000,dtype=np.float32),'call')
    assert len(audio)==80000 and meta['status']=='enrolled'
    assert meta['dominant_speech_share']>.75 and 'call' in asr._speakers
    assert np.all(audio[:9600]==0) and np.all(audio[16000:]==1)


def test_distant_intro_removed_but_quiet_internal_words_preserved(speakers,monkeypatch):
    audio=np.zeros(16000*8,dtype=np.float32)
    bounds=[(0,1,.01),(2,4,.4),(4.5,5.5,.01),(6,8,.4)]
    for a,b,value in bounds:audio[int(a*16000):int(b*16000)]=value
    monkeypatch.setattr(asr,'speaker_embedding',lambda a:np.array([.75,.66]) if np.sqrt(np.mean(a**2))<.1 else np.array([1.,0.]))
    speech=[{'start':int(a*16000),'end':int(b*16000)} for a,b,_ in bounds]
    retained,removed=asr.foreground_spans(audio,speech,[(s['start'],s['end']) for s in speech],np.array([1.,0.]))
    assert removed==1 and retained==[(32000,64000),(72000,88000),(96000,128000)]


def test_failed_initial_overlap_does_not_poison_voice_profile(speakers,monkeypatch):
    monkeypatch.setattr(asr,'_diarizer',SimpleNamespace(process=lambda _:segments([(0,4,0),(1,2,1)])))
    audio,meta=asr.filter_speaker(np.ones(64000,dtype=np.float32),'call')
    assert not len(audio) and meta['requires_repeat'] and 'call' not in asr._speakers


def test_same_voice_quiet_intro_is_not_removed_as_background(speakers):
    audio=np.zeros(16000*5,dtype=np.float32)
    audio[:16000]=.01;audio[32000:]=.4
    selected=[(0,16000),(32000,80000)]
    speech=[{'start':a,'end':b} for a,b in selected]
    retained,removed=asr.foreground_spans(audio,speech,selected,np.array([1.,0.]))
    assert retained==selected and removed==0


def test_background_speaker_removed_without_concatenating_word_edges(speakers,monkeypatch):
    asr._speakers['call']=(np.array([1.,0.]),time.monotonic())
    monkeypatch.setattr(asr,'_diarizer',SimpleNamespace(process=lambda _:segments([(0,2,7),(2,4,9),(4,6,7)])))
    monkeypatch.setattr(asr,'speaker_embedding',lambda a:np.array([1.,0.]) if len(a)==64000 else np.array([0.,1.]))
    audio,meta=asr.filter_speaker(np.ones(96000,dtype=np.float32),'call')
    assert np.all(audio[:32000]==1) and np.all(audio[32000:64000]==0) and np.all(audio[64000:]==1)
    assert meta['removed_background_speakers']==1


def test_other_voice_is_not_sent_to_agent(speakers,monkeypatch):
    asr._speakers['call']=(np.array([0.,1.]),time.monotonic())
    monkeypatch.setattr(asr,'_diarizer',SimpleNamespace(process=lambda _:segments([(0,2,0)])))
    audio,meta=asr.filter_speaker(np.ones(32000,dtype=np.float32),'call')
    assert not len(audio) and meta['requires_repeat']


def test_simultaneous_voices_request_repeat(speakers,monkeypatch):
    asr._speakers['call']=(np.array([1.,0.]),time.monotonic())
    monkeypatch.setattr(asr,'_diarizer',SimpleNamespace(process=lambda _:segments([(0,3,0),(1,3,1)])))
    monkeypatch.setattr(asr,'speaker_embedding',lambda a:np.array([1.,0.]) if len(a)==48000 else np.array([0.,1.]))
    audio,meta=asr.filter_speaker(np.ones(48000,dtype=np.float32),'call')
    assert not len(audio) and meta['status']=='overlapping_speakers'


def test_short_yes_is_preserved_without_claiming_verified_identity(speakers,monkeypatch):
    asr._speakers['call']=(np.array([1.,0.]),time.monotonic())
    monkeypatch.setattr(asr,'_diarizer',SimpleNamespace(process=lambda _:segments([(0,.25,0)])))
    monkeypatch.setattr(asr,'speaker_embedding',lambda _:None)
    audio,meta=asr.filter_speaker(np.ones(4000,dtype=np.float32),'call')
    assert len(audio)==4000 and meta['status']=='short_reply_unverified'


def test_long_audio_segmentation_retains_every_sample_and_uses_pause():
    audio=np.arange(16000*55,dtype=np.float32)
    speech=[{'start':0,'end':16000*20},{'start':16000*21,'end':len(audio)}]
    chunks=list(asr.split_long_audio(audio,speech))
    assert len(chunks[0])==16000*20.5
    assert all(len(c)<=16000*24 for c in chunks)
    assert np.array_equal(np.concatenate(chunks),audio)


def test_ctc_repetition_state_survives_packets(monkeypatch):
    outputs=[[0,0,34],[0,0,1],[1,34,1]]
    class Model:
        def run(self,_,inputs):
            assert inputs['signal'].shape==(1,2400,1)
            probs=np.full((1,3,35),-20.,dtype=np.float32)
            for i,token in enumerate(outputs.pop(0)):probs[0,i,token]=0
            return probs,inputs['state']
    monkeypatch.setattr(asr,'_tone',Model())
    stream=asr.ToneStream()
    # Left padding followed by two packets, blank separates repeated letters.
    assert stream.feed(np.zeros(4800,dtype=np.float32))=='ааб'
    assert stream.feed(np.zeros(4800,dtype=np.float32))=='аабб'


def test_long_masked_gap_separates_short_confirmation_without_losing_samples():
    audio=np.arange(16000*10,dtype=np.float32)
    chunks=list(asr.split_long_audio(audio,[{'start':0,'end':16000*4},{'start':16000*8,'end':len(audio)}]))
    assert len(chunks)==2 and np.array_equal(np.concatenate(chunks),audio)


def test_audio_decode_and_duration_limit():
    import soundfile as sf
    out=io.BytesIO();sf.write(out,np.zeros(1600),16000,format='WAV')
    assert len(asr.decode_audio(out.getvalue()))==1600
    out=io.BytesIO();sf.write(out,np.zeros(16000*121),16000,format='WAV')
    with pytest.raises(ValueError):asr.decode_audio(out.getvalue())


def test_stream_order_and_session_isolation(monkeypatch):
    monkeypatch.setattr(asr,'load',lambda:None)
    monkeypatch.setattr(asr,'decode_audio',lambda _:np.zeros(0,dtype=np.float32))
    monkeypatch.setattr(asr.ToneStream,'feed',lambda self,_:'текст')
    monkeypatch.setattr(asr,'_streams',{})
    assert asr.preview(b'x','call1','same',0)['cumulative']
    assert asr.preview(b'x','call2','same',0)['cumulative']
    with pytest.raises(ValueError):asr.preview(b'x','call1','same',0)
    asr.close_stream('call1','same')
    assert ('call2','same') in asr._streams
