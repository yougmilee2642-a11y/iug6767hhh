"""Small process-local throttle for the single-owner prototype, not distributed anti-fraud."""
from collections import deque
import threading
import time
from fastapi import HTTPException
from services.customer_safety import enabled

_lock = threading.Lock()
_starts = {}


def check_start(peer):
    if not enabled(): return
    with _lock:
        now = time.monotonic()
        for key in list(_starts):
            while _starts[key] and _starts[key][0] < now - 600: _starts[key].popleft()
            if not _starts[key]: del _starts[key]
        if len(_starts) >= 1000 and peer not in _starts:
            raise HTTPException(429, 'Слишком много новых разговоров. Попробуйте позже.', headers={'Retry-After': '600'})
        queue = _starts.setdefault(peer, deque())
        if len(queue) >= 30:
            raise HTTPException(429, 'Лимит новых разговоров: 30 за 10 минут. Подождите.', headers={'Retry-After': '600'})
        queue.append(now)
