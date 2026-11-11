"""Single-process turn serialization. Referenced entries are never evicted.

Adapted from colleagues' proposal: duplicates wait before reserving model
capacity; entries are released only after their last holder/waiter leaves.
This is not a distributed lock or a multi-worker concurrency guarantee.
"""
import os
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field

try:
    _capacity = min(16, max(1, int(os.getenv('CALLWISE_MAX_CONCURRENT_TURNS', '2'))))
except ValueError:
    _capacity = 2
_slots = threading.BoundedSemaphore(_capacity)
_registry_lock = threading.Lock()
_MAX_TRACKED = 512


class ConversationBusy(TimeoutError):
    pass


@dataclass
class Entry:
    lock: object = field(default_factory=threading.RLock)
    users: int = 0


_entries: dict[str, Entry] = {}


@contextmanager
def conversation_turn(interaction_id, timeout=60):
    key = interaction_id or 'new:' + uuid.uuid4().hex
    with _registry_lock:
        entry = _entries.get(key)
        if entry is None:
            if len(_entries) >= _MAX_TRACKED:
                raise ConversationBusy('Очередь разговоров заполнена. Повторите позже.')
            entry = _entries[key] = Entry()
        entry.users += 1
    acquired_lock = acquired_slot = False
    deadline = time.monotonic() + timeout
    try:
        acquired_lock = entry.lock.acquire(timeout=max(0, deadline-time.monotonic()))
        if not acquired_lock:
            raise ConversationBusy('Этот разговор ещё обрабатывается. Повторите позже.')
        acquired_slot = _slots.acquire(timeout=max(0, deadline-time.monotonic()))
        if not acquired_slot:
            raise ConversationBusy('Все места обработки заняты. Повторите позже.')
        yield
    finally:
        if acquired_slot:
            _slots.release()
        if acquired_lock:
            entry.lock.release()
        with _registry_lock:
            entry.users -= 1
            if not entry.users and _entries.get(key) is entry:
                del _entries[key]


def active_conversation_count():
    with _registry_lock:
        return len(_entries)
