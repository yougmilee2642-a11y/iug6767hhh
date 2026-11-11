from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from meetings.auth import MeetError
from . import service
from .common import run


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    meeting_id: int | None = Field(default=None, gt=0, le=2**63 - 1)


def router():
    api = APIRouter()

    @api.post('/api/meet/qa')
    def ask(payload: Question, request: Request, response: Response):
        def operation(actor, audit):
            if not payload.question.strip():
                raise MeetError(422, 'invalid_question', 'Введите вопрос.')
            return service.answer(actor, payload.question.strip(), payload.meeting_id, audit)
        return run(request, response, 'qa.generate', operation)

    @api.get('/api/meet/qa/{answer_id}')
    def saved(answer_id: str, request: Request, response: Response):
        return run(request, response, 'qa.read', lambda actor, audit: service.saved_answer(actor, answer_id, audit))

    return api
