from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from agents.models import AgentConfig
from services import customer_safety
from services.conversation_lock import conversation_turn
import storage


class ConsentDecision(BaseModel):
    accepted: bool
    version: str = Field(min_length=1, max_length=80)


class ReviewUpdate(BaseModel):
    status: str = Field(pattern='^(pending|in_review|resolved)$')


def router():
    api = APIRouter(tags=['customer-safety'])

    @api.post('/api/conversations/{interaction_id}/consent')
    def decision(interaction_id: str, payload: ConsentDecision):
        with conversation_turn(interaction_id):
            state = storage.get_interaction(interaction_id)
            if state is None: raise HTTPException(404, 'Разговор не найден.')
            config = AgentConfig.model_validate(state['agent_config'])
            try: customer_safety.consent(state, config, payload.accepted, payload.version)
            except ValueError as error: raise HTTPException(409, str(error)) from None
            storage.save_interaction(state)
            return {'accepted': customer_safety.accepted(state), 'greeting': config.greeting if payload.accepted else state['result'],
                    'privacy': state['privacy'], 'complete': not payload.accepted}

    @api.get('/api/safety/reviews')
    def reviews():
        with storage.connect() as db:
            return {'items': [dict(row) for row in db.execute('SELECT * FROM review_requests ORDER BY id DESC LIMIT 100')]}

    @api.get('/api/safety/status')
    def status():
        return {'enabled': customer_safety.enabled(), 'supported_language': 'ru', 'automatic_calls': False,
                'live_handoff': False, 'automatic_booking_changes': False, 'custom_voice': False,
                'review_queue': True, 'production_privacy_approved': False}

    @api.patch('/api/safety/reviews/{review_id}')
    def update(review_id: int, payload: ReviewUpdate):
        with storage.connect() as db:
            cursor = db.execute('UPDATE review_requests SET status=? WHERE id=?', (payload.status, review_id))
            if not cursor.rowcount: raise HTTPException(404, 'Запрос не найден.')
        return {'id': review_id, 'status': payload.status, 'external_action_performed': False}

    return api
