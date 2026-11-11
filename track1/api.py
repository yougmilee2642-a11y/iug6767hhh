from fastapi import APIRouter, HTTPException
from builder.api import SaveRequest
from services.track1_service import Track1Service, QuickInput, RevisionConflict
from services.product_workspace import DraftInput, load_draft, save_draft, overview
from agents.models import StrictModel
from pydantic import Field


class PreviewRequest(QuickInput):
    draft_revision: int | None = Field(default=None, ge=0)


class DraftRequest(StrictModel):
    expected_revision: int = Field(ge=0)
    data: DraftInput


def router():
    api = APIRouter(prefix='/api/track1')

    @api.post('/preview')
    def preview(payload: PreviewRequest):
        try:
            return Track1Service().preview(QuickInput.model_validate(payload.model_dump(exclude={'draft_revision'})),payload.draft_revision)
        except RevisionConflict as exc:
            raise HTTPException(409, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    @api.post('/agents')
    def save(payload: SaveRequest):
        try:
            return Track1Service().save(payload.candidate_id, payload.review_token)
        except ValueError as exc:
            raise HTTPException(409, str(exc))

    @api.get('/agents/{agent_id}/settings')
    def settings(agent_id: str):
        try:
            return Track1Service().settings(agent_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc))

    @api.get('/draft')
    def draft():
        return load_draft()

    @api.put('/draft')
    def update_draft(payload: DraftRequest):
        try:
            return save_draft(payload.data,payload.expected_revision)
        except ValueError as exc:
            raise HTTPException(409,str(exc))

    @api.get('/overview')
    def workspace():
        return overview()

    return api
