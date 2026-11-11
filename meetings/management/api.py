from fastapi import APIRouter, Request, Response

from meetings.knowledge.common import run
from . import service


def router():
    api = APIRouter()

    @api.get('/api/meet/overview')
    def overview(request: Request, response: Response, as_of: str | None = None):
        return run(request, response, 'overview.read', lambda actor, audit: service.overview(actor, as_of, audit))

    @api.get('/api/meet/sources/{kind}/{source_id}')
    def source(kind: str, source_id: str, request: Request, response: Response):
        return run(request, response, 'source.read', lambda actor, audit: service.resolve(actor, kind, source_id, audit))

    return api
