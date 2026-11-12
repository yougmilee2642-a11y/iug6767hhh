import json
from datetime import date

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from meetings import access, confirmations, store
from meetings.api import ConfirmTokenIn, _meeting
from meetings.auth import MeetError, MeetRoute, current_user, require
from meetings.connectors.contracts import IntegrationError
from meetings.connectors.mock import digest
from meetings.knowledge.common import run
from meetings.privacy import prohibited_intent, source_is_injection
from providers.local_settings import LocalAIError
from . import service


class Ask(BaseModel):
    model_config=ConfigDict(extra='forbid')
    text: str=Field(min_length=1,max_length=2000)
    meeting_id: int | None=Field(default=None,gt=0,le=2**63-1)
    conversation_id: str | None=Field(default=None,max_length=80)


class Basis(BaseModel):
    model_config=ConfigDict(extra='forbid')
    kind:str=Field(pattern='^(metric|call|document|utterance)$')
    id:str=Field(min_length=1,max_length=240)


class CalendarHint(BaseModel):
    model_config=ConfigDict(extra='forbid')
    participant_ids:list[int]=Field(default_factory=list,max_length=30)
    range_start:str|None=Field(default=None,max_length=40)
    range_end:str|None=Field(default=None,max_length=40)
    duration_minutes:int=Field(default=60,ge=15,le=480)
    timezone:str=Field(default=store.DISPLAY_ZONE,max_length=60)


class Action(BaseModel):
    model_config=ConfigDict(extra='forbid')
    kind: str=Field(pattern='^(task|meeting|task_change)$')
    text: str=Field(min_length=5,max_length=2000)
    meeting_id: int | None=Field(default=None,gt=0,le=2**63-1)
    assignee_user_id: int | None=Field(default=None,gt=0,le=2**63-1)
    due: str | None=Field(default=None,max_length=10)
    task_id: int | None=Field(default=None,gt=0,le=2**63-1)
    status: str | None=Field(default=None,pattern='^(open|in_progress|blocked|done|cancelled)$')
    basis:Basis|None=None
    calendar_hint:CalendarHint|None=None


def validate(c,user,data,*,known_basis=False):
    data['_actor_context']=digest([user['id'],user.get('level'),user.get('department_id'),user.get('_delegated_departments',[])])
    if prohibited_intent(data['text']) or source_is_injection(data['text']):
        raise MeetError(422,'restricted_action','Действие запрещено политикой ассистента. Обратитесь к уполномоченному сотруднику.')
    if data.get('basis'):
        from meetings.management.service import resolve
        try:
            if data['basis']['kind'] in ('document','utterance'):
                from meetings.evidence import resolve as evidence
                source=evidence(c,user,data['basis']['kind'],data['basis']['id'])
            else:
                source=resolve(user['id'],data['basis']['kind'],data['basis']['id'],{})
        except MeetError as error:
            if known_basis and error.status in (404,409):
                raise MeetError(409,'stale','Источник изменился или доступ отозван. Нужен новый предпросмотр.') from None
            raise
        data['_basis_hash']=digest(source)
        data['_basis_source']=source['source']
    if data['due']:
        try:data['due']=date.fromisoformat(data['due']).isoformat()
        except ValueError:raise MeetError(422,'invalid_date','Срок должен быть датой ГГГГ-ММ-ДД.') from None
    if data['kind']=='task_change':
        if not data['task_id'] or not data['status']:raise MeetError(422,'task_status_required','Выберите поручение и новый статус.')
        task=c.execute('SELECT * FROM tasks WHERE id=?',(data['task_id'],)).fetchone()
        if not task or not store.can_read_meeting(c,user['id'],task['meeting_id']):raise service.gone(user,'task',data['task_id'])
        require(user,'tasks.change',action='assistant.task_change')
        parent=dict(c.execute('SELECT * FROM meetings WHERE id=?',(task['meeting_id'],)).fetchone())
        parent.update(_shared=True,assignee_user_id=task['assignee_user_id'],department_id=task['department_id'] or parent['department_id'])
        if not access.decide(access.load_user(c,user['id']),'tasks.change',parent).allowed:raise MeetError(403,'task_change_denied','Недостаточно прав на изменение поручения.')
        return task,data
    if data['kind']=='meeting':
        require(user,'meetings.create',action='assistant.meeting')
        if data.get('calendar_hint'):
            from meetings.calendar.service import participants
            hint=data['calendar_hint'];people=participants(c,hint['participant_ids'],user['id'])
            hint['participant_ids']=[p['id'] for p in people if p['id']!=user['id']]
            try:
                store.zone(hint['timezone'])
                a,b=hint['range_start'],hint['range_end']
                if bool(a)!=bool(b):raise ValueError()
                if a and not 0<(store.parse_aware(b)-store.parse_aware(a)).total_seconds()<=31*86400:raise ValueError()
            except (store.TimeError,ValueError):raise MeetError(422,'calendar_hint','Уточните диапазон поиска с часовым поясом (не больше31 дня).') from None
            data['_participant_names']=[p['name'] for p in people if p['id']!=user['id']]
        return {'department_id':user.get('department_id'),'version':None},data
    if not data['meeting_id']:raise MeetError(422,'meeting_required','Для поручения выберите встречу-основание.')
    row=_meeting(c,user,data['meeting_id'],'protocol.confirm','assistant.task')
    person=access.load_user(c,data['assignee_user_id']) if data['assignee_user_id'] else None
    if data['assignee_user_id'] and (not person or not person['active'] or person['level'] in ('admin','auditor')):
        raise MeetError(422,'invalid_assignee','Выберите действующего ответственного.')
    if person and user.get('level')!='director' and person['department_id'] not in [row['department_id'],*user.get('_delegated_departments',[])]:
        raise MeetError(403,'department_assignee','Ответственный должен быть из доступного отдела.')
    return row,data


def router():
    api=APIRouter(route_class=MeetRoute)

    @api.post('/api/meet/assistant/ask')
    def ask(payload: Ask,request: Request,response: Response):
        user=current_user(request);require(user,'qa.ask',action='assistant.ask')
        def operation(actor,audit):
            try:return service.question(user,payload.text.strip(),payload.meeting_id,payload.conversation_id,audit)
            except IntegrationError as error:raise MeetError(503,error.code,str(error)) from None
            except LocalAIError as error:raise MeetError(503,'model_'+error.code,str(error)) from None
        return run(request,response,'assistant.ask',operation)

    @api.get('/api/meet/assistant/conversations')
    def conversations(request: Request):
        user=current_user(request);require(user,'qa.ask',action='assistant.history')
        with store.db() as c:
            store.audit(c,user['id'],'assistant_history_list',object_type='assistant')
            return {'conversations':[dict(r) for r in c.execute('SELECT id,created_at FROM assistant_conversations WHERE user_id=? ORDER BY created_at DESC,id DESC LIMIT 30',(user['id'],))]}

    @api.get('/api/meet/assistant/conversations/{conversation_id}')
    def history(conversation_id: str,request: Request,response: Response):
        user=current_user(request);require(user,'qa.ask',action='assistant.history')
        def operation(actor,audit):
            with store.db() as c:
                c.execute('BEGIN')
                return service.history(c,user,conversation_id)
        return run(request,response,'assistant.history',operation)

    @api.post('/api/meet/assistant/actions/preview')
    def preview(payload: Action,request: Request):
        user=current_user(request)
        with store.write_tx() as c:
            row,data=validate(c,user,payload.model_dump())
            preview={**data,'origin':'Ручное поручение, подтверждённое пользователем; не реплика записи.',
                     'assignee_status':'stated' if data['assignee_user_id'] else 'unknown',
                     'due_status':'stated' if data['due'] else 'unknown'}
            if data['kind']=='meeting':preview['origin']='Будет создан проект встречи без приглашений. Время и участников календаря вы проверите отдельно.'
            if data['kind']=='task_change':preview.update(text=row['text'],status_before=row['status'],status_after=data['status'])
            object_type='task' if data['kind']=='task_change' else 'meeting' if data['kind']=='task' else 'user'
            object_id=data['task_id'] if data['kind']=='task_change' else data['meeting_id'] if data['kind']=='task' else user['id']
            token=confirmations.create(c,user,'assistant.action',object_type,object_id,row['version'],{'data':data,'preview':preview,'data_hash':digest(data)})
            store.audit(c,user['id'],'assistant_action_preview',object_type='meeting',object_id=data['meeting_id'],
                        stage='preview',confirmation_id=token['confirmation_id'])
            return {**token,'preview':preview}

    @api.post('/api/meet/assistant/actions/confirm')
    def confirm(payload: ConfirmTokenIn,request: Request):
        user=current_user(request)
        with store.write_tx() as c:
            pending=confirmations.load(c,user,payload.confirmation_id,'assistant.action',idempotency_key=payload.idempotency_key)
            data=pending['payload']['data']
            basis_hash=data.get('_basis_hash')
            row,data=validate(c,user,data,known_basis=True)
            if pending['already']:
                result=pending['result']
                if result.get('meeting_id'): _meeting(c,user,result['meeting_id'])
                return {**result,'already_confirmed':True}
            if basis_hash!=data.get('_basis_hash'):
                raise MeetError(409,'stale','Показатель или источник звонка изменился. Проверьте действие заново.')
            if row['version']!=pending['object_version']:
                raise MeetError(409,'stale','Встреча изменилась после предпросмотра. Проверьте действие заново.')
            if pending['payload'].get('data_hash') and digest(data)!=pending['payload']['data_hash']:
                raise MeetError(409,'stale','Параметры, сотрудники или права изменились. Проверьте действие заново.')
            stamp=store.now()
            if data['kind']=='task_change':
                tid=row['id'];mid=row['meeting_id']
                c.execute('UPDATE tasks SET status=?,updated_at=?,version=version+1 WHERE id=?',(data['status'],stamp,tid))
                c.execute('INSERT INTO task_history(task_id,user_id,before_json,after_json,created_at) VALUES (?,?,?,?,?)',(tid,user['id'],json.dumps({'status':row['status']}),json.dumps({'status':data['status']}),stamp))
                result={'meeting_id':mid,'task_id':tid,'notice':'Статус поручения изменён после подтверждения.'}
            elif data['kind']=='meeting':
                mid=c.execute("INSERT INTO meetings(owner_id,title,topic,created_at,department_id,participants,confidentiality) VALUES (?,?,?,?,?,?,'confidential')",
                              (user['id'],data['text'][:200],data['text'],stamp,user.get('department_id'),json.dumps(data.get('_participant_names',[]),ensure_ascii=False))).lastrowid
                result={'meeting_id':mid,'task_id':None,'calendar_hint':data.get('calendar_hint'),'notice':'Создана встреча без приглашений. Выберите время в календаре.'}
            else:
                mid=data['meeting_id'];person=access.load_user(c,data['assignee_user_id']) if data['assignee_user_id'] else None
                name=person['name'] if person else None
                assignee_status='stated' if person else 'unknown';due_status='stated' if data['due'] else 'unknown'
                c.execute('INSERT OR IGNORE INTO protocols(meeting_id,generated_at,model) VALUES (?,?,?)',(mid,stamp,'human-confirmed-manual'))
                position=c.execute('SELECT COALESCE(MAX(position),0)+1 FROM protocol_items WHERE meeting_id=?',(mid,)).fetchone()[0]
                pid=c.execute("INSERT INTO protocol_items(meeting_id,position,kind,text,assignee,assignee_status,due,due_status,confirmed_by,confirmed_at,edited) VALUES (?,?,'task',?,?,?,?,?,?,?,1)",
                    (mid,position,data['text'],name,assignee_status,data['due'],due_status,user['id'],stamp)).lastrowid
                origin={'kind':'manual_request','text':data['text'],'confirmed_by':user['id'],'source_at':stamp}
                if data.get('basis'):origin['basis']=data['basis']
                tid=c.execute('INSERT INTO tasks(meeting_id,protocol_item_id,text,assignee,assignee_status,due,due_status,source_quote,confirmed_by,confirmed_at,created_at,updated_at,department_id,assignee_user_id) '
                              'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(mid,pid,data['text'],name,assignee_status,data['due'],due_status,json.dumps(origin,ensure_ascii=False),user['id'],stamp,stamp,stamp,row['department_id'],data['assignee_user_id'])).lastrowid
                c.execute('UPDATE protocol_items SET task_id=? WHERE id=?',(tid,pid))
                from meetings.notifications import assigned
                assigned(c,tid)
                c.execute('INSERT INTO task_origins VALUES (?,?,?,?)',(tid,user['id'],'assistant_manual_request',stamp))
                c.execute('UPDATE meetings SET version=version+1 WHERE id=?',(mid,))
                result={'task_id':tid,'meeting_id':mid,'notice':'Ручное поручение сохранено. Запись встречи не изменена.'}
            if data.get('basis'):
                kind='task' if result.get('task_id') else 'meeting';oid=result['task_id'] if kind=='task' else result['meeting_id']
                c.execute('INSERT OR REPLACE INTO action_basis VALUES (?,?,?,?,?,?,?,?)',
                    (kind,oid,data['basis']['kind'],data['basis']['id'],data['_basis_hash'],json.dumps(data['_basis_source'],ensure_ascii=False),user['id'],stamp))
            confirmations.finish(c,payload.confirmation_id,payload.idempotency_key,result)
            store.audit(c,user['id'],'assistant_action_confirmed',object_type='meeting',object_id=result['meeting_id'],
                        stage='confirm',confirmation_id=payload.confirmation_id)
            return {**result,'already_confirmed':False}

    return api
