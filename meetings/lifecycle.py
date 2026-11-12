"""Compose lifecycle hooks through public FastAPI router lifespan support.

Works with both the pinned runtime and newer base-profile Starlette versions,
without depending on removed add_event_handler/on_startup APIs.
"""
from contextlib import asynccontextmanager
from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool


def install(app,start,finish=None):
    @asynccontextmanager
    async def lifespan(_app):
        await run_in_threadpool(start)
        try:yield
        finally:
            if finish:await run_in_threadpool(finish)
    app.include_router(APIRouter(lifespan=lifespan))
