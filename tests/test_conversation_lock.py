import threading
from concurrent.futures import ThreadPoolExecutor
import pytest
from services import conversation_lock as locks
from test_track1_quick import client, create_agent, call, request_count


def test_different_conversations_can_progress_together(monkeypatch):
    monkeypatch.setattr(locks,'_slots',threading.BoundedSemaphore(2))
    barrier=threading.Barrier(2)
    def turn(key):
        with locks.conversation_turn(key):barrier.wait(timeout=2)
    with ThreadPoolExecutor(2) as pool:
        a=pool.submit(turn,'a');b=pool.submit(turn,'b');a.result();b.result()
    assert locks.active_conversation_count()==0


def test_same_key_times_out_and_keeps_the_original_entry():
    with locks.conversation_turn('same'):
        entry=locks._entries['same']
        def waiting():
            with pytest.raises(locks.ConversationBusy):
                with locks.conversation_turn('same',timeout=.02):pass
        with ThreadPoolExecutor(1) as pool:pool.submit(waiting).result()
        assert locks._entries['same'] is entry and entry.users==1
    assert 'same' not in locks._entries


def test_capacity_does_not_evict_active_entries(monkeypatch):
    monkeypatch.setattr(locks,'_MAX_TRACKED',1)
    with locks.conversation_turn('busy'):
        entry=locks._entries['busy']
        with pytest.raises(locks.ConversationBusy):
            with locks.conversation_turn('another',timeout=.01):pass
        assert locks._entries['busy'] is entry
    assert locks.active_conversation_count()==0


def test_duplicates_wait_without_consuming_unrelated_capacity(monkeypatch):
    monkeypatch.setattr(locks,'_slots',threading.BoundedSemaphore(2))
    waiting=threading.Event()
    def duplicate():
        waiting.set()
        with pytest.raises(locks.ConversationBusy):
            with locks.conversation_turn('same',timeout=.1):pass
    with locks.conversation_turn('same'):
        with ThreadPoolExecutor(1) as pool:
            result=pool.submit(duplicate);assert waiting.wait(1)
            with locks.conversation_turn('unrelated',timeout=.02):pass
            result.result()


def test_exception_releases_capacity_and_registry(monkeypatch):
    monkeypatch.setattr(locks,'_slots',threading.BoundedSemaphore(1))
    with pytest.raises(ValueError):
        with locks.conversation_turn('failed'):raise ValueError('test')
    with locks.conversation_turn('next',timeout=.01):pass
    assert locks.active_conversation_count()==0


def test_api_duplicate_confirmation_creates_only_one_callback(client):
    aid=create_agent(client)
    cid=client.post('/api/conversations',json={'agent_id':aid}).json()['interaction_id']
    call(client,cid,'Тест');call(client,cid,'+375290000000');call(client,cid,'Нужна консультация')
    assert request_count()==0
    with ThreadPoolExecutor(2) as pool:
        replies=list(pool.map(lambda _:call(client,cid,'Да','same-confirmation'),range(2)))
    assert request_count()==1
    assert replies[0]['interaction']['action_result']['callback_id']==replies[1]['interaction']['action_result']['callback_id']
