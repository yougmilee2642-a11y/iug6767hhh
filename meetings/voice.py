"""«Фокус», the manager's voice assistant: push-to-talk question -> existing read APIs -> short spoken phrase.

No new model path: questions go only to the knowledge QA (`knowledge.service.answer`) or the
management overview (`management.service.build`). Nothing is written by voice: a command to
create or change something gets a refusal and a pointer to the on-screen preview/confirm flow.

Speaker privacy: a loudspeaker is heard by everyone in the room, while access rights belong to
one user. By default a phrase is spoken only when every member of the audience (the meeting's
participants, or every user when no meeting is chosen) could see the same thing themselves.
Otherwise the answer is shown on screen only, unless the user explicitly says they are alone.
"""
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, File, Request, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from meetings import auth, store
from meetings.auth import MeetError, current_user
from meetings.knowledge.common import ExtensionRoute, run, utc_now

MAX_SPOKEN = 220
MAX_AUDIO = 5 * 1024 * 1024
MAX_WAKE_AUDIO = 256 * 1024  # ~8 s of 16 kHz PCM: a wake segment, not a recording
LOOPBACK = {'127.0.0.1', '::1'}
# Two words at the start of an utterance: «фокус» alone is an everyday word ("фокус на сроках").
WAKE = re.compile(r'^\W*(?:привет|окей|окэй|ок|о\s?кей|okay|ok)\W+фокус(?:е|а)?(?![а-яё])\W*(.*)$', re.I | re.S)
MONTHS = ('января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября',
          'октября', 'ноября', 'декабря')

# Commands only: imperatives and "can you / need to" + infinitive. A question such as
# "какие задачи поставили вчера?" stays a question.
_IMPERATIVE = ('создай поставь назначь добавь перенеси сдвинь отмени удали измени поменяй закрой отметь пригласи '
               'позови запиши отправь напиши запланируй организуй подтверди согласуй сохрани выполни убери верни '
               'переназначь').split()
_INFINITIVE = ('создать поставить назначить добавить перенести сдвинуть отменить удалить изменить поменять закрыть '
               'отметить пригласить позвать записать отправить написать запланировать организовать подтвердить '
               'согласовать сохранить выполнить убрать вернуть переназначить').split()
WRITE = re.compile(
    rf'(?<![а-яё])(?:{"|".join(_IMPERATIVE)})(?:те)?(?![а-яё])'
    rf'|(?<![а-яё])(?:можешь|можете|могли\s+бы|нужно|надо|прошу|давай|давайте)[\s,]+(?:[а-яё]+[\s,]+){{0,2}}?'
    rf'(?:{"|".join(_INFINITIVE)})(?![а-яё])', re.I)
OVERVIEW = re.compile(r'задач|поручени|просроч|kpi|кпи|показател|метрик|сводк|обзор|загрузк\w*\s+производ|'
                      r'заказ\w*\s+в\s+срок|брак', re.I)
DOCUMENT_HINT = re.compile(r'документ|регламент|договор|инструкц|положени|политик|прайс|в\s+файл', re.I)
METRIC_CUES = (('defect_rate', re.compile(r'брак', re.I)),
               ('on_time_orders', re.compile(r'в\s+срок|вовремя|своевремен', re.I)),
               ('capacity_utilization', re.compile(r'загрузк', re.I)))
METRIC_WORDS = {'on_time_orders': 'заказы в срок', 'defect_rate': 'брак',
                'capacity_utilization': 'загрузка производства'}
ALL_METRICS = re.compile(r'kpi|кпи|показател|метрик|сводк|обзор', re.I)
WRITE_PAGES = (('calendar', re.compile(r'пригла|позов|встреч|созвон|календар|запланир|перенес|сдвин', re.I)),
               ('tasks', re.compile(r'задач|поручени|срок|ответствен', re.I)))


def route(text):
    """Deterministic routing; the model never chooses an action."""
    if WRITE.search(text):
        return 'action'
    if OVERVIEW.search(text) and not DOCUMENT_HINT.search(text):
        return 'overview'
    return 'knowledge'


def day_label(value):
    moment = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if moment.tzinfo is None:
        raise ValueError('timezone required')
    local = moment.astimezone(ZoneInfo(store.DISPLAY_ZONE))
    return f'{local.day} {MONTHS[local.month - 1]} {local.year}'


def number(value):
    text = f'{value:.1f}'.rstrip('0').rstrip('.') if isinstance(value, float) else str(value)
    return text.replace('.', ',')


def audience(connection, actor, meeting_id):
    """Who may hear the speaker: the meeting's participants, or everyone when no meeting is chosen."""
    if meeting_id is None:
        return [row['id'] for row in connection.execute('SELECT id FROM users ORDER BY id')]
    owner = connection.execute('SELECT owner_id FROM meetings WHERE id=?', (meeting_id,)).fetchone()
    members = {owner['owner_id']} if owner else set()
    members.update(row['user_id'] for row in connection.execute(
        'SELECT user_id FROM meeting_access WHERE meeting_id=?', (meeting_id,)))
    members.add(actor)
    return sorted(members)


# ---------- spoken phrases ----------
def knowledge_phrase(result):
    if result['status'] != 'grounded' or not result['claims']:
        return 'В доступных документах оснований для ответа не найдено.'
    first = result['claims'][0]
    origin = first['sources'][0]
    try:
        dated = f', от {day_label(origin["source_at"])}'
    except (ValueError, TypeError):
        dated = ''
    where = f'Источник: «{origin["title"]}»{dated}.'
    rest = len(result['claims']) - 1
    tail = f' Ещё подтверждений на экране: {rest}.' if rest else ''
    quote = ' '.join(first['text'].split())
    if quote and quote[-1] not in '.!?…':
        quote += '.'  # a heading-like quote must not run into "Источник"
    if len(quote) > MAX_SPOKEN:
        # A verbatim quote is never cut: dropping a clause can drop a condition.
        return f'Ответ длинный, он на экране. {where}{tail}'
    return f'{quote} {where}{tail}'


def overview_phrase(result, question, generated):
    by_key = {metric['key']: metric for metric in result['metrics']}
    wanted = [key for key, cue in METRIC_CUES if cue.search(question)]
    if ALL_METRICS.search(question):
        wanted = [key for key, _ in METRIC_CUES]
    parts = []
    tasks_asked = not wanted or re.search(r'задач|поручени|просроч', question, re.I)
    if tasks_asked:
        open_count = by_key.get('open_tasks', {}).get('value', 0)
        late = by_key.get('overdue_tasks', {}).get('value', 0)
        parts.append(f'Реестр задач на {day_label(generated)}: открытых — {open_count}, просроченных — {late}.')
    if wanted:
        values = []
        for key in wanted:
            metric = by_key.get(key)
            label = METRIC_WORDS[key]
            values.append(f'{label} — {number(metric["value"])} %' if metric and metric['value'] is not None
                          else f'{label} — нет данных')
        when = f' на {day_label(result["as_of"])}' if result.get('as_of') else ''
        parts.append(f'Производственная витрина{when}: {", ".join(values)}.')
    return ' '.join(parts)


def action_reply(text):
    page = next((name for name, cue in WRITE_PAGES if cue.search(text)), 'tasks')
    where = 'в календаре встречи' if page == 'calendar' else 'в разделе «Задачи»'
    spoken = ('Голосом я ничего не создаю и не меняю. '
              f'Откройте предпросмотр {where} и подтвердите изменение на экране.')
    return {'route': 'action', 'status': 'refused', 'open_page': page, 'answer': None,
            'spoken': spoken, 'display': spoken, 'speak': True, 'silent_reason': None}


# ---------- service ----------
def answer_knowledge(actor_user, text, meeting_id, details):
    from meetings.knowledge import service as knowledge
    auth.require(actor_user, 'qa.ask', action='voice.ask')
    result = knowledge.answer(actor_user['id'], text, meeting_id, details)
    phrase = knowledge_phrase(result)
    private = False
    if result['status'] == 'grounded':
        fragment_ids = sorted({int(source['id'][1:]) for source in result['sources']})
        with store.db() as connection:
            documents = {row['document_id'] for row in connection.execute(
                f'SELECT document_id FROM fragments WHERE id IN ({",".join("?" * len(fragment_ids))})', fragment_ids)}
            listeners = audience(connection, actor_user['id'], meeting_id)
            private = any(not store.can_read_document(connection, member, document)
                          for member in listeners for document in documents)
    return result, phrase, private


def answer_overview(actor_user, text, meeting_id, details):
    from meetings.management import service as management
    auth.require(actor_user, 'overview.read', action='voice.ask')
    generated = utc_now()
    with store.db() as connection:
        connection.execute('BEGIN')  # one snapshot for the user and every listener
        if meeting_id is not None and not store.can_read_meeting(connection, actor_user['id'], meeting_id):
            raise MeetError(404, 'not_found', 'Не найдено или нет доступа.')
        result, _ = management.build(connection, actor_user['id'], generated, generated)
        phrase = overview_phrase(result, text, generated)
        # The phrase is safe to speak only if every listener would hear exactly the same from their own rights.
        private = any(overview_phrase(management.build(connection, member, generated, generated)[0], text, generated)
                      != phrase for member in audience(connection, actor_user['id'], meeting_id)
                      if member != actor_user['id'])
    details['source_ids'] = [metric['source']['id'] for metric in result['metrics']]
    return result, phrase, private


def ask(actor_user, text, meeting_id, speak_private, details):
    kind = route(text)
    details['route'] = kind
    if kind == 'action':
        details['result'] = 'refused'
        return action_reply(text)
    handler = answer_overview if kind == 'overview' else answer_knowledge
    result, phrase, private = handler(actor_user, text, meeting_id, details)
    speak = not private or speak_private
    details['spoken'] = speak
    details['private'] = private
    return {'route': kind, 'status': result.get('status', 'ok'), 'open_page': kind, 'answer': result,
            'spoken': phrase if speak else None, 'display': phrase, 'speak': speak,
            'silent_reason': None if speak else (
                'Ответ опирается на данные, которые видят не все участники; он показан только на экране.')}


def wake_match(text):
    """(woken, question after the wake phrase)."""
    found = WAKE.match(' '.join((text or '').split()))
    return (True, found.group(1).strip()) if found else (False, '')


def local_room(request):
    # The wake detector listens to the whole room, so it runs only on the machine in that room:
    # a loopback client, not proxied from outside, with local ASR. Nothing leaves the computer.
    client = request.client.host if request.client else ''
    proxied = any(name in request.headers for name in ('x-forwarded-for', 'forwarded', 'x-real-ip'))
    return client in LOOPBACK and not proxied


# ---------- HTTP ----------
class VoiceQuestion(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=1, max_length=1000)
    meeting_id: int | None = Field(default=None, strict=True, gt=0, le=2**63 - 1)
    speak_private: bool = False


def _transcribe(data):
    from providers.local_settings import uses_local_ai, LocalAIError
    from services import local_speech
    if not uses_local_ai():
        # Audio of an internal question must not leave the machine.
        raise MeetError(503, 'local_asr_required', 'Голосовой вопрос распознаётся только локально. Напишите вопрос текстом.')
    try:
        return ' '.join(local_speech.transcribe_local(data).split())
    except LocalAIError as error:
        raise MeetError(503, 'asr_unavailable', str(error)) from None
    except Exception:  # noqa: BLE001 - decoder errors carry no useful user text
        raise MeetError(422, 'asr_failed', 'Не удалось распознать запись. Повторите вопрос или напишите его.') from None


def router():
    api = APIRouter(route_class=ExtensionRoute)

    @api.post('/api/meet/voice/ask')
    def voice_ask(payload: VoiceQuestion, request: Request, response: Response):
        user = current_user(request)
        text = ' '.join(payload.text.split())
        if not text:
            raise MeetError(422, 'invalid_question', 'Повторите вопрос: запись пустая.')
        return run(request, response, 'voice.ask',
                   lambda _actor, details: ask(user, text, payload.meeting_id, payload.speak_private, details))

    @api.post('/api/meet/voice/transcribe')
    async def voice_transcribe(request: Request, response: Response, file: UploadFile = File(...)):
        user = current_user(request)
        auth.require(user, 'qa.ask', action='voice.transcribe')
        data = await file.read(MAX_AUDIO + 1)
        if not data:
            raise MeetError(422, 'empty_audio', 'Пустая запись. Удерживайте кнопку, пока говорите.')
        if len(data) > MAX_AUDIO:
            raise MeetError(413, 'audio_too_long', 'Вопрос слишком длинный: до двух минут.')
        # The audio is kept only in memory for this call and never stored.
        text = await run_in_threadpool(_transcribe, data)
        response.headers['Cache-Control'] = 'no-store'
        return {'text': text}

    @api.post('/api/meet/voice/wake')
    async def voice_wake(request: Request, response: Response, file: UploadFile = File(...)):
        user = current_user(request)
        auth.require(user, 'qa.ask', action='voice.wake')
        if not local_room(request):
            raise MeetError(403, 'wake_local_only', 'Фраза «Привет, Фокус» работает только на компьютере в комнате. '
                                                    'Используйте кнопку «Спросить голосом».')
        data = await file.read(MAX_WAKE_AUDIO + 1)
        if not data or len(data) > MAX_WAKE_AUDIO:
            raise MeetError(413, 'wake_segment_size', 'Фрагмент для фразы активации должен быть короче 8 секунд.')
        text = await run_in_threadpool(_transcribe, data)
        response.headers['Cache-Control'] = 'no-store'
        woken, question = wake_match(text)
        # Room speech that is not addressed to Фокус is neither returned, logged nor audited.
        return {'wake': woken, 'question': question if woken else ''}

    return api
