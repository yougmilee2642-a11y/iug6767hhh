from typing import Literal
import asyncio
import logging
import os
import re
import smtplib
import tempfile
from pathlib import Path
from contextlib import asynccontextmanager

import edge_tts
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from openai import APIError, RateLimitError
from pydantic import BaseModel, Field, field_validator

from agents.models import AgentConfig
from services.notifications import send_application_email
from agents.runtime import AgentRuntime, new_interaction
from agents.factory import create_runtime
from agents.validation import InvalidAgentConfig, validate_agent
from prompts import load_agent, build_transcription_prompt
from providers.groq import GroqProvider, groq_client
from providers.language import normalize_transcript
from providers.errors import ProviderError
from services.call_summary import intake_summary
from services.conversation_lock import conversation_turn, ConversationBusy
from services.telegram_bot import TelegramWorker
from services import owner_access
from integrations.api import router as integrations_router
from services.safety_api import router as safety_router
from services import customer_safety
from services.abuse_limits import check_start
from providers.local_settings import local_only, uses_local_ai, LocalAIError
from providers.ollama import OllamaProvider
from services import local_speech
from track1.telegram_api import router as telegram_router
from track1.api import router as track1_router
from track1.shell_api import router as shell_router
from meetings.api import install as install_meetings
from providers.builder import GroqBuilderProvider
from services.agent_service import AgentService
from builder.api import router as builder_router
from evaluation.api import router as evaluation_router
from evaluation.service import EvaluationService
from storage import get_config, initialize_db, list_applications, save_config, get_interaction, save_interaction, public_interaction

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")
if local_only():
    os.environ['HF_HUB_OFFLINE']='1'
    os.environ['TRANSFORMERS_OFFLINE']='1'
    os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
initialize_db()
stored_config = get_config()
if not stored_config.get("notification_email") and os.getenv("BUSINESS_EMAIL", "").strip():
    stored_config["notification_email"] = os.getenv("BUSINESS_EMAIL", "").strip()
    save_config(stored_config)

@asynccontextmanager
async def lifespan(application):
    worker = TelegramWorker()
    if not local_only(): worker.start()
    if uses_local_ai() and all(local_speech.readiness()[key] for key in ('stt_weights','tts_weights')):
        await asyncio.to_thread(local_speech.warm_up)
    if uses_local_ai():
        local_provider = OllamaProvider()
        if await asyncio.to_thread(local_provider.available):
            try:
                await asyncio.to_thread(local_provider.warm_up)
            except LocalAIError:
                logging.getLogger('focus').warning('Local AI warmup incomplete; no fallback used')
    try:
        yield
    finally:
        await asyncio.to_thread(worker.stop)


app = FastAPI(title="Фокус — AI-сотрудник", lifespan=lifespan)
app.middleware('http')(owner_access.guard)
app.include_router(owner_access.router())
app.include_router(integrations_router())
app.include_router(safety_router())
app.include_router(telegram_router())
app.include_router(shell_router())
install_meetings(app)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
logger = logging.getLogger("focus")


class Message(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    agent_id: str | None = Field(default=None, max_length=100)
    interaction_id: str | None = None
    text: str | None = Field(default=None, max_length=4000)
    request_id: str | None = Field(default=None, max_length=100)
    messages: list[Message] = Field(default_factory=list, max_length=80)


class CustomQuestion(BaseModel):
    id: str = Field(min_length=1, max_length=60, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=80)
    question: str = Field(min_length=3, max_length=240)
    required: bool = True


class BusinessConfig(BaseModel):
    business_name: str = Field(min_length=2, max_length=100)
    industry: str = Field(min_length=2, max_length=120)
    city: str = Field(min_length=2, max_length=100)
    description: str = Field(default="", max_length=2000)
    notification_email: str = Field(default="", max_length=254)
    language: str = Field(default="ru", pattern="^ru$")
    greeting: str = Field(min_length=10, max_length=600)
    services: str = Field(default="[]", max_length=5000)
    opening_hours: str = Field(default="", max_length=500)
    timezone: str = Field(default="UTC", max_length=100)
    callback_message: str = Field(default="", max_length=500)
    knowledge_base: str = Field(default="", max_length=5000)
    custom_questions: list[CustomQuestion] = Field(default_factory=list, max_length=12)

    @field_validator("notification_email")
    @classmethod
    def validate_email(cls, value):
        value = value.strip()
        if value and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Некорректный адрес email")
        return value



@app.exception_handler(RequestValidationError)
async def validation_error(request, error):
    fields = ", ".join(str(item["loc"][-1]) for item in error.errors())
    if request.url.path=='/api/track1/preview' and any(e.get('msg')=='Value error, Сократите знания до 6500 символов' for e in error.errors()):
        return JSONResponse(status_code=422,content={'detail':'Сократите знания до 6500 символов. Текст не был обрезан или применён.'})
    return JSONResponse(status_code=422, content={"detail": f"Проверьте значения полей: {fields}. Формат или длина не подходят."})


def client():
    if uses_local_ai(): raise HTTPException(503,'Облачное распознавание отключено для локального AI.')
    try:
        return groq_client()
    except ValueError as error:
        raise HTTPException(503, str(error))


def get_provider():
    if uses_local_ai(): return OllamaProvider()
    return GroqProvider()


def get_builder_provider():
    return GroqBuilderProvider()


app.include_router(builder_router(lambda: get_builder_provider()))
app.include_router(track1_router())


def get_evaluation_service():
    return EvaluationService()


app.include_router(evaluation_router(lambda: get_evaluation_service()))


def selected_agent(agent_id=None):
    try:
        return AgentService().resolve(agent_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except InvalidAgentConfig:
        raise
    except ValueError as exc:
        raise HTTPException(422, str(exc))


def runtime(config):
    return create_runtime(config, get_provider())



def finalize_notification(state):
    if not customer_safety.accepted(state): return
    if local_only():
        state.update(notification_attempted=True,email_sent=False)
        return
    if state.get("notification_attempted"):
        return
    state["notification_attempted"] = True
    # Generated agents have no configured recipient yet. Never send their data
    # to the legacy demo's global BUSINESS_EMAIL by accident.
    item = AgentService().repository.get(state["agent_id"])
    if item and item["source"] in {"builder", "track1"}:
        state["email_sent"] = False
        return
    try:
        state["email_sent"] = send_application_email(state, get_config())
    except (OSError, smtplib.SMTPException, ValueError):
        logger.warning("Не удалось отправить email для обращения %s", state["id"])
        state["email_error"] = "Обращение сохранено, но email не отправлен. Проверьте SMTP-настройки."


@app.get("/")
def index():
    origin = os.getenv("PUBLIC_ORIGIN", "http://127.0.0.1:8000").rstrip("/")
    return HTMLResponse((ROOT / "static" / "index.html").read_text(encoding="utf-8").replace("__PUBLIC_ORIGIN__", origin))


@app.get('/login')
def login_page():
    return HTMLResponse((ROOT / 'static' / 'login.html').read_text(encoding='utf-8'))


@app.get('/miniapp')
def miniapp():
    if local_only(): raise HTTPException(503,'Telegram Mini App отключён в полностью локальном режиме.')
    return HTMLResponse((ROOT / 'static' / 'miniapp.html').read_text(encoding='utf-8'))


@app.get("/api/health")
def health():
    config = get_config()
    local=uses_local_ai()
    return {"status": "ok", "ai_provider": 'Ollama' if local else 'Groq', 'local_only':local_only(),
            'local_speech':local_speech.readiness() if local else None,
            'model':os.getenv('OLLAMA_MODEL','qwen3:4b-instruct') if local else os.getenv('GROQ_MODEL','openai/gpt-oss-20b'),
            'llm_ready':OllamaProvider().available() if local else bool(os.getenv('GROQ_API_KEY','').strip()),
            "groq_configured": not local and bool(os.getenv("GROQ_API_KEY", "").strip()),
            "smtp_configured": all(os.getenv(name, "").strip() for name in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD")),
            "business_configured": bool(config.get("business_name") and config.get("greeting") and config.get("services"))}


@app.get("/api/config")
def read_config():
    return get_config()


@app.put("/api/config")
def update_config(payload: BusinessConfig):
    data, previous = payload.model_dump(), get_config()
    if data["business_name"] != previous["business_name"] and data["greeting"] == previous["greeting"]:
        data["greeting"] = f"Здравствуйте! Я AI-администратор {data['business_name']}. Чем могу помочь?"
    try:
        load_agent(data)
    except InvalidAgentConfig as error:
        raise HTTPException(422, error.report)
    except ValueError:
        raise HTTPException(422, "Проверьте конфигурацию агента и идентификаторы дополнительных полей.")
    return save_config(data)


@app.get("/api/agent")
def read_agent():
    return load_agent(get_config()).model_dump()


@app.post("/api/agent/validate")
def validate_agent_config(payload: dict):
    return validate_agent(payload)


@app.exception_handler(InvalidAgentConfig)
async def invalid_agent(_, error):
    return JSONResponse(status_code=422, content={"detail": error.report})


@app.exception_handler(LocalAIError)
async def local_ai_error(_,error):
    return JSONResponse(status_code=503,content={'detail':str(error)})


@app.exception_handler(ConversationBusy)
async def conversation_busy(_,error):
    return JSONResponse(status_code=503,content={'detail':str(error)},headers={'Retry-After':'3'})


@app.get("/api/applications")
def read_applications(limit: int = 50, agent_id: str | None = None, status: str | None = None, source: Literal['own','demo','other'] | None = None):
    return {"items": list_applications(max(1, min(limit, 100)), agent_id=agent_id, status=status, source=source)}


@app.post("/api/conversations")
def start_conversation(request: Request, payload: ChatRequest | None = None):
    check_start(request.client.host if request.client else 'unknown')
    state = new_interaction(selected_agent(payload.agent_id if payload else None))
    save_interaction(state)
    return {"interaction_id": state["id"], "greeting": state["transcript"][0]["content"], "agent_name": state["agent_config"]["name"], 'privacy': state.get('privacy')}


@app.post("/api/transcribe")
def transcribe(request: Request, file: UploadFile = File(...), context: str = Form(default=""), interaction_id: str = Form(default=""),
               mode: Literal['whole','preview','final'] = Form(default='whole'),
               stream_id: str = Form(default='',max_length=100), sequence: int = Form(default=0,ge=0,le=1200),
               speaker_mode: Literal['primary','all'] = Form(default='primary'),
               meeting_consent: bool = Form(default=False), meeting_id: int | None = Form(default=None)):
    state = get_interaction(interaction_id) if interaction_id else None
    if interaction_id and state is None: raise HTTPException(404,'Разговор не найден.')
    meeting_capture = speaker_mode == 'all' and not interaction_id and mode in {'whole','final'}
    if meeting_capture:
        if not meeting_consent:
            raise HTTPException(403,'Подтвердите, что все участники согласны на запись и расшифровку встречи.')
        if meeting_id is None:
            raise HTTPException(422,'Для записи укажите встречу.')
        from meetings import store as meeting_store
        from meetings.auth import user_from_request
        user = user_from_request(request)
        if not user:
            raise HTTPException(401,'Войдите в демо-профиль встречи.')
        with meeting_store.db() as connection:
            if not meeting_store.can_read_meeting(connection,user['id'],meeting_id):
                raise HTTPException(404,'Встреча не найдена или недоступна.')
    if customer_safety.enabled() and not meeting_capture:
        if state is None: raise HTTPException(404, 'Начните разговор и выберите согласие до записи голоса.')
        if not state.get('safety', {}).get('enabled') or not customer_safety.accepted(state):
            raise HTTPException(403, 'Распознавание запрещено до согласия. Начните новый разговор.')
        if state['status'] in customer_safety.TERMINAL: raise HTTPException(409, 'Разговор завершён.')
    data = file.file.read()
    if not data:
        raise HTTPException(400, "Пустая запись.")
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(413, "Запись превышает 25 МБ. Скажите фразу короче.")
    config = AgentConfig.model_validate(state["agent_config"]) if state else load_agent(get_config())
    if uses_local_ai():
        try:
            if mode=='preview':
                if not state or not stream_id: raise HTTPException(400,'Для потока нужен разговор и идентификатор реплики.')
                return local_speech.transcribe_preview(data,interaction_id,stream_id,sequence)
            if mode=='final' or mode=='whole' and (state is not None or meeting_capture):
                if speaker_mode == 'all':
                    result=local_speech.transcribe_final(data,context,interaction_id,stream_id,speaker_mode='all')
                else:
                    result=local_speech.transcribe_final(data,context,interaction_id,stream_id)
                result['text']=normalize_transcript(result['raw_text'],context,config.language)
                return result
            raw=local_speech.transcribe_local(data,build_transcription_prompt(config,context))
            return {'text':normalize_transcript(raw,context,config.language),'raw_text':raw,'provider':'GigaAM v3 RNNT'}
        except HTTPException: raise
        except LocalAIError as exc: raise HTTPException(503,str(exc))
        except Exception:
            raise HTTPException(422,'Локальный STT не смог прочитать запись. Проверьте формат и длину реплики.') from None
    suffix = Path(file.filename or "audio.webm").suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp:
        temp.write(data)
        name = temp.name
    try:
        with open(name, "rb") as audio:
            result = client().audio.transcriptions.create(model=os.getenv("GROQ_STT_MODEL", "whisper-large-v3"), file=audio,
                language=config.language, temperature=0, prompt=build_transcription_prompt(config, context))
        raw = result.text.strip()
        return {"text": normalize_transcript(raw, context, config.language), "raw_text": raw}
    except APIError as error:
        logger.warning("STT provider error type=%s status=%s", type(error).__name__, getattr(error, "status_code", None))
        if isinstance(error, RateLimitError):
            raise HTTPException(429, "Лимит распознавания Groq исчерпан. Подождите восстановления лимита и повторите фразу.")
        raise HTTPException(502, "Не удалось распознать речь через Groq. Проверьте соединение, ключ и лимиты.")
    finally:
        Path(name).unlink(missing_ok=True)


class TranscriptionParts(BaseModel):
    interaction_id: str = Field(min_length=1,max_length=100)
    parts: list[str] = Field(min_length=1,max_length=60)

    @field_validator('parts')
    @classmethod
    def bounded_parts(cls,parts):
        if sum(len(part) for part in parts)+len(parts)-1>4000:
            raise ValueError('Распознанная реплика превышает 4000 символов.')
        return parts


@app.post('/api/transcribe/assemble')
def assemble_transcription(payload: TranscriptionParts):
    if not uses_local_ai():raise HTTPException(409,'Сборка фрагментов доступна в локальном режиме.')
    state=get_interaction(payload.interaction_id)
    if state is None:raise HTTPException(404,'Разговор не найден.')
    if customer_safety.enabled() and not customer_safety.accepted(state): raise HTTPException(403, 'Нет согласия на обработку.')
    if state['status'] in {'stopped','completed','escalated'}:
        raise HTTPException(409,'Разговор уже завершён.')
    config=AgentConfig.model_validate(state['agent_config'])
    context=next((m['content'] for m in reversed(state['transcript']) if m['role']=='assistant'),'')
    raw=' '.join(part.strip() for part in payload.parts if part.strip())
    # Normalize once across chunk boundaries (especially dictated phone digits).
    # Neither adds a transcript turn nor invokes LLM/tools/storage writes.
    return {'text':normalize_transcript(raw,context,config.language),'raw_text':raw}


@app.post("/api/chat")
def chat(payload: ChatRequest):
    with conversation_turn(payload.interaction_id):
        state = get_interaction(payload.interaction_id) if payload.interaction_id else new_interaction(selected_agent(payload.agent_id))
        if state is None:
            raise HTTPException(404, "Разговор не найден. Начните новый.")
        if customer_safety.enabled() and not state.get('safety', {}).get('enabled'):
            raise HTTPException(409, 'Для этого старого разговора не настроена защита данных. Начните новый.')
        if payload.request_id and state.get("last_request_id") == payload.request_id:
            return state["last_response"]
        text = payload.text or next((m.content for m in reversed(payload.messages) if m.role == "user"), "")
        if not text.strip():
            raise HTTPException(400, "Введите или произнесите сообщение.")
        try:
            reply = runtime(AgentConfig.model_validate(state["agent_config"])).turn(state, text.strip())
        except LocalAIError as error:
            save_interaction(state)
            raise HTTPException(503,str(error))
        except (APIError, ProviderError, ValueError, TypeError, KeyError) as error:
            save_interaction(state)
            logger.warning("Ошибка диалога: %s", type(error).__name__)
            if isinstance(error, RateLimitError) or (isinstance(error, ProviderError) and error.category == 'rate_limit'):
                raise HTTPException(429, "Лимит Groq исчерпан. Обращение сохранено. Подождите восстановления лимита и повторите сообщение.")
            if (isinstance(error, ValueError) and "GROQ_API_KEY" in str(error)) or (isinstance(error, ProviderError) and error.category == 'authentication'):
                raise HTTPException(503, "Нет GROQ_API_KEY. Заполните файл .env.")
            raise HTTPException(502, "Ошибка ответа AI. Обращение сохранено; проверьте подключение и попробуйте ещё раз.")
        save_interaction(state)
        if reply["complete"]:
            finalize_notification(state)
        response = {**reply, "interaction_id": state["id"], "interaction": public_interaction(state)}
        state.update(last_request_id=payload.request_id, last_response=response)
        save_interaction(state)
        return response


@app.post("/api/application")
def application(payload: ChatRequest):
    with conversation_turn(payload.interaction_id):
        state = get_interaction(payload.interaction_id) if payload.interaction_id else None
        if state is None:
            raise HTTPException(404, "Разговор не найден. Начните новый; старое извлечение заменено сохранением разговора.")
        if state["status"] not in {"completed", "escalated", "stopped"}:
            state.update(status="stopped", pending_action=None, pending_collection=None, result="Разговор остановлен. Запись не создана.")
            if state['agent_config']['business']['knowledge'].get('track1_quick') is True:
                state['result'] = 'Незавершённый разговор сохранён. Подтверждённое обращение не создано.'
            elif state['agent_config']['business']['knowledge'].get('track1_profile') == 'support':
                state['result'] = 'Веб-тест завершён. Внешние действия не выполнялись.'
        brief = intake_summary(state)
        if brief is not None:
            state['brief_summary'] = brief
        save_interaction(state)
        if any(m["role"] == "user" for m in state["transcript"]):
            finalize_notification(state)
        save_interaction(state)
        return public_interaction(state)


@app.post("/api/speech")
async def speech(payload: dict[str, str]):
    text = payload.get("text", "").strip()
    if not text or len(text) > 1500:
        raise HTTPException(400, "Для озвучки нужен текст от 1 до 1500 символов.")
    # Фокус speaks with its own (male by default) voice; other callers keep LOCAL_TTS_SPEAKER.
    speaker = os.getenv("FOCUS_TTS_SPEAKER", "aidar") if payload.get("voice") == "focus" else None
    if uses_local_ai():
        try:
            audio=await asyncio.to_thread(local_speech.synthesize_local,*((text,speaker) if speaker else (text,)))
            return Response(audio,media_type='audio/wav')
        except LocalAIError as exc: raise HTTPException(503,str(exc))
        except Exception:
            raise HTTPException(502,'Локальная русская озвучка не удалась. Можно продолжить текстом.') from None
    try:
        audio = bytearray()
        voice = os.getenv("TTS_VOICE", "ru-RU-SvetlanaNeural")
        if not voice.startswith("ru-RU-"):
            voice = "ru-RU-SvetlanaNeural"
        communicate = edge_tts.Communicate(text, voice, rate=os.getenv("TTS_RATE", "+12%"))
        async def collect():
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio.extend(chunk["data"])
        await asyncio.wait_for(collect(), timeout=30)
        if not audio:
            raise ValueError("Пустой звук")
        return Response(bytes(audio), media_type="audio/mpeg")
    except Exception:
        raise HTTPException(502, "Русская озвучка недоступна. Можно продолжить текстом; проверьте интернет и TTS_VOICE.")
