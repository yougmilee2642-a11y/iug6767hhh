import pytest
from fastapi.testclient import TestClient
from tests.test_voice_safety import _wav


@pytest.fixture
def call(tmp_path,monkeypatch):
    import app, storage
    from agents.runtime import new_interaction
    from prompts import load_agent
    monkeypatch.setenv('CALLWISE_LOCAL_ONLY','true')
    monkeypatch.setattr(storage,'DB_PATH',tmp_path/'db.sqlite')
    monkeypatch.setattr(storage,'DATA_DIR',tmp_path)
    storage.initialize_db()
    state=new_interaction(load_agent(storage.get_config()))
    storage.save_interaction(state)
    return TestClient(app.app),app,storage,state


def test_preview_only_returns_hint_and_does_not_create_a_turn(call,monkeypatch):
    client,app,storage,state=call
    calls=[]
    def preview(data,interaction_id,stream_id,sequence):
        calls.append((interaction_id,stream_id,sequence))
        return {'raw_text':'предварительно','text':'предварительно','cumulative':True,'final':False}
    monkeypatch.setattr(app.local_speech,'transcribe_preview',preview)
    response=client.post('/api/transcribe',files={'file':('c.wav',_wav())},
        data={'interaction_id':state['id'],'mode':'preview','stream_id':'stream','sequence':'0'})
    assert response.status_code==200 and response.json()['final'] is False
    assert calls==[(state['id'],'stream',0)]
    assert storage.get_interaction(state['id'])['transcript']==state['transcript']


def test_final_audio_is_authoritative_and_phone_is_normalized_once(call,monkeypatch):
    client,app,storage,state=call
    def final(data,context,interaction_id,stream_id):
        assert data==_wav() and stream_id=='stream' and interaction_id==state['id']
        return {'text':'три семь пять два девять один два три четыре пять шесть семь',
                'raw_text':'три семь пять два девять один два три четыре пять шесть семь','final':True}
    monkeypatch.setattr(app.local_speech,'transcribe_final',final)
    response=client.post('/api/transcribe',files={'file':('full.wav',_wav())},
        data={'interaction_id':state['id'],'mode':'final','stream_id':'stream','context':'Назовите номер телефона.'})
    assert response.status_code==200 and response.json()['text']=='375291234567'
    assert storage.get_interaction(state['id'])['transcript']==state['transcript']


def test_uncertain_speaker_returns_repeat_and_never_chat(call,monkeypatch):
    client,app,storage,state=call
    monkeypatch.setattr(app.local_speech,'transcribe_final',lambda *_:{'raw_text':'','text':'',
        'speaker':{'requires_repeat':True,'status':'overlapping_speakers'}})
    response=client.post('/api/transcribe',files={'file':('full.wav',_wav())},
        data={'interaction_id':state['id'],'mode':'final'})
    assert response.status_code==200 and not response.json()['text']
    assert response.json()['speaker']['requires_repeat']
    assert storage.get_interaction(state['id'])['transcript']==state['transcript']


def test_missing_stream_context_is_rejected_before_model(call,monkeypatch):
    client,app,_,state=call
    monkeypatch.setattr(app.local_speech,'transcribe_preview',lambda *_:pytest.fail('Missing stream ID'))
    assert client.post('/api/transcribe',files={'file':('c.wav',_wav())},
        data={'mode':'preview','interaction_id':state['id']}).status_code==400
