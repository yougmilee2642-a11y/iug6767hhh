"""Room hints and a three-sentence personal briefing. No models or actions."""
from datetime import datetime,timezone
import json,re
from typing import Annotated
from fastapi import APIRouter,Request,Path
from pydantic import BaseModel,ConfigDict,Field
from meetings import access,store
from meetings.auth import MeetError,MeetRoute,current_user,require
from meetings.privacy import source_is_injection

TASK=re.compile(r'\b(?:проверь\w*|согласу\w*|подготов\w*|задач\w*|поруча\w*|нужно|надо)\b',re.I)
DEADLINE=re.compile(r'\b(?:сегодня|завтра|послезавтра|понедельник|вторник|сред\w*|четверг|пятниц\w*|суббот\w*|воскресень\w*)\b|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}\s+(?:январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр|ноябр|декабр)\w*|\bчерез\s+\w+\s+(?:дня|дней|час|минут|недел)',re.I)
NEGATION=re.compile(r'не\s+(?:нужно|надо|поруча)|задач\w*\s+(?:отмен|отклон)',re.I)


class Room(BaseModel):
    model_config=ConfigDict(extra='forbid')
    consent:bool=False
    drafts:list[Annotated[str,Field(min_length=1,max_length=2000)]]=Field(default_factory=list,max_length=20)


def hints(c,user,meeting_id,body):
    require(user,'transcript.edit',action='room.hints')
    if not body.consent:raise MeetError(403,'consent_required','Подсказки записи доступны только с согласия участников.')
    from meetings.api import _meeting,denied
    meeting=_meeting(c,user,meeting_id,'transcript.edit','room.hints')
    if not store.can_read_meeting(c,user['id'],meeting_id,model=True):raise denied(user,'meeting',meeting_id,'room.hints')
    if sum(map(len,body.drafts))>20000:raise MeetError(422,'room_limit','Не больше20тыс. символов временного текста.')
    candidates=[{'text':u['text'],'source':{'kind':'utterance','id':u['id'],'quote':u['text'],
                  'source_at':meeting['scheduled_at'] or meeting['created_at']},'verified':True}
                for u in store.utterances(c,meeting_id)[-30:]]
    candidates.extend({'text':text,'source':{'kind':'draft','id':'P'+str(i+1),'quote':text},'verified':False} for i,text in enumerate(body.drafts))
    result=[]
    from meetings.intent import people
    for item in candidates:
        text=item['text']
        if not TASK.search(text) or NEGATION.search(text) or source_is_injection(text):continue
        missing=[]
        if not people(c,user,text,'task',meeting_id):missing.append('ответственного')
        if not DEADLINE.search(text):missing.append('срок')
        if missing:result.append({'text':'Возможное поручение: уточните '+ ' и '.join(missing)+'.',
                                  'source':item['source'],'verified_transcript':item['verified']})
    return {'hints':result[-10:],'partial':len(result)>10,'generated_at':store.now(),
            'notice':'Подсказки по правилам, без действий. Непроверенный текст ASR не является репликой протокола; подтвердите его отдельно.'}


def corridor(c,user,now=None):
    require(user,'meetings.read',action='corridor.read')
    now=now or datetime.now(timezone.utc);visible,args=access.predicate(c,user['id'],'meeting','m',model=True)
    candidates=[]
    for row in c.execute('SELECT m.* FROM meetings m WHERE '+visible,args):
        stamps=[]
        for event in c.execute("SELECT e.start_at FROM calendar_events e WHERE e.meeting_id=? AND e.status='confirmed' AND (e.organizer_id=? OR EXISTS (SELECT 1 FROM calendar_event_participants p WHERE p.event_id=e.id AND p.user_id=?))",(row['id'],user['id'],user['id'])):
            stamps.append(event[0])
        try:personal=row['owner_id']==user['id'] or user['name'] in json.loads(row['participants'])
        except (ValueError,TypeError):personal=False
        if not stamps and personal and row['scheduled_at']:stamps=[row['scheduled_at']]
        for stamp in stamps:
            try:at=store.parse_aware(stamp)
            except store.TimeError:continue
            if at>=now:candidates.append((at,dict(row)))
    if not candidates:return {'status':'insufficient_data','claims':[],'spoken':'В доступном личном расписании будущая встреча не найдена. Проверьте приглашения и время.','meeting_id':None,'model':None}
    at,meeting=min(candidates,key=lambda p:(p[0],p[1]['id']));mid=meeting['id']
    tasks=[dict(r) for r in c.execute("SELECT * FROM tasks WHERE meeting_id=? AND status NOT IN ('done','cancelled')",(mid,))]
    docs=[dict(r) for r in c.execute('SELECT d.* FROM documents d JOIN meeting_documents m ON m.document_id=d.id WHERE m.meeting_id=?',(mid,)) if store.can_read_document(c,user['id'],r['id'],model=True)]
    source={'kind':'meeting','id':str(mid),'title':meeting['title'],'source_at':meeting['created_at']}
    sources=[source,*[{'kind':'task','id':'T'+str(t['id']),'title':t['text'],'source_at':t['updated_at']} for t in tasks]]
    local=at.astimezone(store.zone(store.DISPLAY_ZONE));short=meeting['title'] if len(meeting['title'])<90 else 'указанная на экране встреча'
    texts=[f'Ближайшая встреча: {short}, {local:%d.%m в %H:%M}.',
           f'В её текущем реестре открытых поручений: {len(tasks)}; без срока: {sum(not t["due"] for t in tasks)}.',
           f'Доступных прикреплённых документов: {len(docs)}; проверьте повестку на экране.']
    doc_sources=[]
    for d in docs:
        f=c.execute('SELECT id,text FROM fragments WHERE document_id=? ORDER BY idx LIMIT 1',(d['id'],)).fetchone()
        if f:doc_sources.append({'kind':'document','id':'F'+str(f['id']),'title':d['title'],'source_at':d['created_at']})
    return {'status':'grounded','claims':[{'text':texts[0],'sources':[source]},{'text':texts[1],'sources':sources},
        {'text':texts[2],'sources':[source,*doc_sources]}],'spoken':' '.join(texts),'meeting_id':mid,'model':None,'generated_at':store.iso_utc(now),
        'notice':'Короткий детерминированный брифинг; длительность зависит от TTS, измеряется на хосте.'}


def router():
    api=APIRouter(route_class=MeetRoute)
    @api.get('/api/meet/corridor')
    def read(request:Request):
        user=current_user(request)
        with store.db() as c:
            c.execute('BEGIN')
            result=corridor(c,user);store.audit(c,user['id'],'corridor_read',object_type='meeting',object_id=result['meeting_id'])
            return result
    @api.post('/api/meet/meetings/{meeting_id}/room-hints')
    def room(body:Room,request:Request,meeting_id:int=Path(gt=0,le=2**63-1)):
        user=current_user(request)
        with store.db() as c:
            c.execute('BEGIN')
            result=hints(c,user,meeting_id,body)
            store.audit(c,user['id'],'room_hints',object_type='meeting',object_id=meeting_id,hint_count=len(result['hints']))
            return result
    return api
