from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.testclient import TestClient
from meetings.lifecycle import install


def test_hooks_compose_with_original_lifespan_and_shutdown_in_reverse_order():
    events=[]
    @asynccontextmanager
    async def original(_app):
        events.append('original:start')
        try:yield
        finally:events.append('original:stop')
    app=FastAPI(lifespan=original)
    install(app,lambda:events.append('first:start'),lambda:events.append('first:stop'))
    install(app,lambda:events.append('second:start'),lambda:events.append('second:stop'))
    with TestClient(app):
        assert events==['original:start','first:start','second:start']
    assert events==['original:start','first:start','second:start','second:stop','first:stop','original:stop']


def test_shutdown_runs_when_serving_code_raises():
    events=[];app=FastAPI()
    install(app,lambda:events.append('start'),lambda:events.append('stop'))
    try:
        with TestClient(app):raise RuntimeError('synthetic interruption')
    except RuntimeError:pass
    assert events==['start','stop']
