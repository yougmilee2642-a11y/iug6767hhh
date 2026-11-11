from fastapi import APIRouter, HTTPException
from pydantic import Field
from agents.models import StrictModel
from builder.models import BusinessInput
from builder.service import AgentBuilder
from services.agent_service import AgentService
from requirement_contract import RequirementContract, resolve, CATALOG

class GenerateRequest(BusinessInput):
    requirement_contract: RequirementContract | None = None


class CandidateRequest(StrictModel):
    candidate_id: str = Field(max_length=100)


class SaveRequest(CandidateRequest):
    review_token: str = Field(max_length=100)


def router(provider_factory):
    api = APIRouter()
    def builder():
        return AgentBuilder(provider_factory())

    @api.post("/api/builder/generate")
    def generate(payload: GenerateRequest):
        try:
            business = BusinessInput.model_validate(payload.model_dump(exclude={'requirement_contract'}))
            return builder().generate(business, payload.requirement_contract)
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    @api.post('/api/builder/requirements')
    def requirements(payload: BusinessInput):
        return {'contract': resolve(payload.tasks).model_dump(), 'catalog': CATALOG}

    @api.post("/api/builder/validate")
    def validate(payload: CandidateRequest):
        try:
            return builder().validate(payload.candidate_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc))

    @api.post("/api/agents")
    def save(payload: SaveRequest):
        try:
            return builder().save(payload.candidate_id, payload.review_token)
        except LookupError as exc:
            raise HTTPException(404, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    @api.get("/api/agents")
    def agents():
        service = AgentService()
        service.demo()
        return {"items": service.repository.list()}

    @api.get("/api/agents/{agent_id}")
    def detail(agent_id: str):
        item = AgentService().repository.get(agent_id)
        if not item:
            raise HTTPException(404, "Агент не найден")
        return item

    @api.post("/api/agents/{agent_id}/activate")
    def activate(agent_id: str):
        try:
            return AgentService().activate(agent_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    return api
