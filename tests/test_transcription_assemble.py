import pytest
from fastapi.testclient import TestClient
import app
import storage
from agents.runtime import new_interaction
from prompts import load_agent


@pytest.fixture
def conversation(tmp_path,monkeypatch):
    monkeypatch.setenv('CALLWISE_LOCAL_ONLY','true')
    monkeypatch.setattr(storage,'DB_PATH',tmp_path/'test.db')
    monkeypatch.setattr(storage,'DATA_DIR',tmp_path)
    storage.initialize_db()
    state=new_interaction(load_agent(storage.get_config()))
    state['transcript'][-1]['content']='Назовите номер телефона.'
    storage.save_interaction(state)
    return TestClient(app.app),state


def test_assembly_normalizes_digits_across_boundaries_without_creating_a_turn(conversation,monkeypatch):
    client,state=conversation
    monkeypatch.setattr(app,'create_runtime',lambda *_:pytest.fail('Partial text reached LLM'))
    response=client.post('/api/transcribe/assemble',json={'interaction_id':state['id'],'parts':['три семь пять','два девять','один два три четыре пять шесть семь']})
    assert response.status_code==200
    assert response.json()['text']=='375291234567'
    assert storage.get_interaction(state['id'])['transcript']==state['transcript']


def test_assembly_keeps_repeated_words_and_empty_chunks(conversation):
    client,state=conversation
    response=client.post('/api/transcribe/assemble',json={'interaction_id':state['id'],'parts':['да','', 'нет нет']})
    assert response.json()['text']=='да нет нет'


def test_assembly_rejects_missing_or_closed_conversation(conversation):
    client,state=conversation
    assert client.post('/api/transcribe/assemble',json={'interaction_id':'missing','parts':['да']}).status_code==404
    state['status']='stopped';storage.save_interaction(state)
    assert client.post('/api/transcribe/assemble',json={'interaction_id':state['id'],'parts':['да']}).status_code==409


def test_assembly_bounds_work_and_disables_cloud_path(conversation,monkeypatch):
    client,state=conversation
    for parts in [[],['x']*61,['x'*4001]]:
        assert client.post('/api/transcribe/assemble',json={'interaction_id':state['id'],'parts':parts}).status_code==422
    monkeypatch.setenv('CALLWISE_LOCAL_ONLY','false');monkeypatch.setenv('AI_PROVIDER','groq')
    assert client.post('/api/transcribe/assemble',json={'interaction_id':state['id'],'parts':['да']}).status_code==409
