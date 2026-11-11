from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ConfigDict
from services import telegram_store as store
from services.telegram_bot import miniapp_url
from services.telegram_identity import verify_init_data
from services.agent_repository import AgentRepository


class LinkRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    agent_id: str = Field(min_length=1, max_length=100)
    link_id: str = Field(default='', max_length=100)


class InitRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    init_data: str = Field(min_length=1, max_length=12000)


class RegisterRequest(InitRequest):
    display_name: str = Field(min_length=2, max_length=100)
    business_name: str = Field(min_length=2, max_length=100)
    consent: bool


def quick_agent(identifier):
    item = AgentRepository().get(identifier)
    if not item or item['source'] != 'track1':
        raise HTTPException(404, 'Выберите помощника из «Быстрого старта».')


def identity(raw):
    try:
        return verify_init_data(raw)
    except ValueError:
        raise HTTPException(401, 'Подпись Telegram недействительна или сессия устарела. Откройте приложение из бота.')


def router():
    api = APIRouter()

    @api.get('/api/telegram/status')
    def status(agent_id: str = ''):
        if agent_id: quick_agent(agent_id)
        from providers.local_settings import local_only
        return {**store.status(agent_id), 'miniapp_ready': not local_only() and bool(miniapp_url()),'local_only':local_only()}

    @api.post('/api/telegram/link')
    def link(payload: LinkRequest):
        quick_agent(payload.agent_id)
        try: return store.create_link(payload.agent_id)
        except ValueError as exc: raise HTTPException(409,str(exc))

    @api.post('/api/telegram/link/status')
    def check(payload: LinkRequest):
        quick_agent(payload.agent_id)
        try: return store.link_status(payload.link_id,payload.agent_id)
        except ValueError as exc: raise HTTPException(409,str(exc))

    @api.post('/api/telegram/link/approve')
    def approve(payload: LinkRequest):
        quick_agent(payload.agent_id)
        try: return store.approve_link(payload.link_id,payload.agent_id)
        except ValueError as exc: raise HTTPException(409,str(exc))

    @api.post('/api/telegram/disconnect')
    def disconnect(payload: LinkRequest):
        quick_agent(payload.agent_id)
        store.disconnect(payload.agent_id)
        return store.status(payload.agent_id)

    @api.post('/api/miniapp/profile')
    def profile(payload: InitRequest):
        user = identity(payload.init_data)
        return {'profile': store.user_profile(user['id']), 'telegram_name': user.get('first_name','')}

    @api.post('/api/miniapp/register')
    def register(payload: RegisterRequest):
        user = identity(payload.init_data)
        if not payload.consent or len(payload.display_name.strip()) < 2 or len(payload.business_name.strip()) < 2:
            raise HTTPException(422,'Заполните имя, бизнес и согласие на сохранение профиля.')
        return {'profile': store.register_user(user['id'],payload.display_name.strip(),payload.business_name.strip())}

    return api
