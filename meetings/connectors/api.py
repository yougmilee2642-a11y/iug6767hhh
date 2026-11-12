import os
"""Human-confirmed CRM exports. Mock transport only; no background retries."""
import json
import re
from typing import Literal
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from meetings import access, confirmations, store, textutil
from meetings.auth import MeetError, MeetRoute, current_user, require, forbidden
from meetings.connectors.contracts import IntegrationError
from meetings.connectors.mock import MockCRM, digest
from meetings.connectors.factory import connector, name as connector_name
from meetings.privacy import Masker, prohibited_intent, source_is_injection


class Draft(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['task.create','protocol.attach']
    object_id: int = Field(gt=0)
    entity_ref: str | None = Field(default=None,max_length=100)


class Token(BaseModel):
    model_config = ConfigDict(extra='forbid')
    confirmation_id: str = Field(min_length=8,max_length=100)
    idempotency_key: str = Field(min_length=8,max_length=100)


def denied(user, kind, object_id):
    return MeetError(404,'not_found','Не найдено или нет доступа.',audit={
        'user_id':user['id'],'action':'crm.access_denied','object_type':kind,
        'object_id':object_id,'result':'denied','error_code':'not_found'})


def checked_meeting(c,user,meeting_id):
    row = c.execute('SELECT * FROM meetings WHERE id=?',(meeting_id,)).fetchone()
    if not row or not store.can_read_meeting(c,user['id'],meeting_id): raise denied(user,'meeting',meeting_id)
    if row['confidentiality']=='secret':
        raise forbidden(user,'crm.write','meeting',meeting_id,'crm.secret_export')
    if user.get('level')=='head' and row['department_id'] not in [user.get('department_id'),*user.get('_delegated_departments',[])]:
        raise forbidden(user,'crm.write','meeting',meeting_id,'crm.department_export')
    if not access.object_decision(c,user['id'],'meeting',meeting_id,'crm.write').allowed:
        raise forbidden(user,'crm.write','meeting',meeting_id,'crm.export')
    return dict(row)


def quote(c,meeting_id,value):
    uid = str(value.get('utterance_id',''))
    if not re.fullmatch(r'U[1-9][0-9]{0,17}',uid): return None
    row = c.execute('SELECT text FROM utterances WHERE id=? AND meeting_id=? AND deleted=0',
                    (int(uid[1:]),meeting_id)).fetchone()
    if not row or not textutil.find_exact(value.get('text',''),row['text']): return None
    return {'utterance_id':uid,'text':value['text']}


def safe_text(text):
    if prohibited_intent(text) or source_is_injection(text):
        raise MeetError(422,'restricted_action','Такое действие не передаётся в CRM. Обратитесь к уполномоченному ответственному.')


def build(c,user,data,*,read_faults=True):
    """Regenerate the exact export at confirm, including mappings and source proof."""
    action, object_id = data['action'], data['object_id']
    require(user,'crm.write','task' if action=='task.create' else 'meeting',object_id,'crm.export')
    crm = connector(c,user['id'],read_faults=read_faults)
    masker = Masker(r[0] for r in c.execute('SELECT display_name FROM crm_customers'))
    if action=='task.create':
        task = c.execute('SELECT * FROM tasks WHERE id=?',(object_id,)).fetchone()
        if not task: raise denied(user,'task',object_id)
        meeting = checked_meeting(c,user,task['meeting_id'])
        if task['status'] in ('done','cancelled'):
            raise MeetError(422,'task_closed','Задача закрыта. Проверьте её статус перед созданием задачи CRM.')
        original=json.loads(task['source_quote'])
        manual=original.get('kind')=='manual_request' and c.execute('SELECT 1 FROM task_origins WHERE task_id=?',(task['id'],)).fetchone()
        proof = {'kind':'manual_request','task_id':task['id'],'text':task['text']} if manual else quote(c,meeting['id'],original)
        if not proof: raise MeetError(422,'source_quote_required','Проверьте реплику-основание задачи перед отправкой.')
        safe_text(task['text']); safe_text(proof['text'])
        for entity in json.loads(task['linked_entities']):
            if entity['kind']=='document':
                if not store.can_read_document(c,user['id'],int(entity['id'])): raise denied(user,'document',entity['id'])
            else:
                linked = crm.get_order(entity['id']) if entity['kind']=='order' else crm.get_customer(entity['id'])
                if not linked: raise denied(user,entity['kind'],entity['id'])
        mapping = c.execute('SELECT external_id FROM user_external_ids WHERE user_id=? AND connector=?',
                            (task['assignee_user_id'],crm.name)).fetchone()
        employee = crm.get_employee(mapping[0]) if mapping else None
        if not employee:
            raise MeetError(422,'employee_mapping_required','Ответственный в CRM не найден. Уточните владельца задачи и сопоставление сотрудника; отправка запрещена.')
        result = {'task_id':object_id,'meeting_id':meeting['id'],'text':masker.text(task['text']),
                  'assignee_external_id':employee['external_id'],'assignee_name':employee['name'],
                  'due':task['due'],'priority':task['priority'],'linked_entities':json.loads(task['linked_entities']),
                  'source_quote':masker.value(proof),'source_at':meeting['scheduled_at'] or meeting['created_at'],
                  'source_path':f"/api/meet/utterances/{proof['utterance_id']}" if proof.get('utterance_id') else f"/api/meet/sources/task/T{task['id']}"}
        version = task['version']
        if crm.name=='bitrix24':result['destination_hash']=digest(crm.webhook)
        freshness = {k:employee[k] for k in ('source_id','as_of','fetched_at','stale')}
        return result, version, freshness
    meeting = checked_meeting(c,user,object_id)
    safe_text(meeting['title'])
    target = data.get('entity_ref') or ''
    if target.startswith('deal:'):
        entity = crm.get_deal(target[5:])
    else:
        entity = crm.get_task_status(target)
    if not entity: raise denied(user,'crm_entity',target)
    items = []
    for item in c.execute('SELECT * FROM protocol_items WHERE meeting_id=? AND confirmed_at IS NOT NULL ORDER BY position,id',(object_id,)):
        proofs = [p for value in json.loads(item['quotes']) if (p := quote(c,object_id,value))]
        if not proofs and item['task_id'] and c.execute('SELECT 1 FROM task_origins WHERE task_id=?',(item['task_id'],)).fetchone():
            task=c.execute('SELECT * FROM tasks WHERE id=? AND protocol_item_id=?',(item['task_id'],item['id'])).fetchone()
            if task and json.loads(task['source_quote']).get('kind')=='manual_request':
                proofs=[{'kind':'manual_request','task_id':task['id'],'text':task['text']}]
        if not proofs: raise MeetError(422,'source_quote_required','У подтверждённого пункта нет проверяемой цитаты.')
        safe_text(item['text'])
        for proof in proofs: safe_text(proof['text'])
        items.append({'id':item['id'],'kind':item['kind'],'text':item['text'],'quotes':proofs})
    if not items: raise MeetError(422,'no_confirmed_items','Сначала подтвердите пункты протокола с цитатами.')
    result = masker.value({'meeting_id':object_id,'title':meeting['title'],'items':items,'entity_ref':target,
                          'source_at':meeting['scheduled_at'] or meeting['created_at'],
                          'source_path':f'/api/meet/meetings/{object_id}'})
    if crm.name=='bitrix24':
        result['destination_hash']=digest(crm.webhook)
        result['entity_external_id']=entity.get('external_id') or target.rsplit(':',1)[-1]
    return result,meeting['version'],{k:entity[k] for k in ('source_id','as_of','fetched_at','stale')}


def integration_error(error,user):
    denied_result = error.code=='forbidden'
    return MeetError(403 if denied_result else 503,error.code,
        'Недостаточно прав для операции CRM.' if denied_result else str(error),audit={
            'user_id':user['id'],'action':'crm.error','object_type':'integration',
            'result':'denied' if denied_result else 'failed','error_code':error.code})


def response(result, already=False):
    body = {**result,'already_confirmed':already}
    return JSONResponse(body,status_code=result.get('http_status',200))


def router():
    api = APIRouter(route_class=MeetRoute)

    @api.post('/api/meet/crm/preview')
    def preview(payload: Draft,request: Request):
        user = current_user(request)
        with store.write_tx() as c:
            try: draft,version,freshness = build(c,user,payload.model_dump())
            except IntegrationError as error: raise integration_error(error,user) from None
            kind = 'task' if payload.action=='task.create' else 'meeting'
            old = c.execute('SELECT status,external_ref FROM integration_outbox WHERE connector=? AND action=? AND object_type=? AND object_id=?',
                            (connector_name(),payload.action,kind,payload.object_id)).fetchone()
            if old:
                raise MeetError(409,'export_exists','Отправка уже зарегистрирована. Проверьте её статус; повторная отправка запрещена.')
            view = {'connector':connector_name(),'mode':('mock' if connector_name()==MockCRM.name else 'bitrix24'),'action':payload.action,'fields':draft,
                    'freshness':freshness,'warning':'Данные устарели.' if freshness['stale'] else None,
                    'notice':'Локальная имитация Битрикс24. Реальный портал не подключён.' if connector_name()==MockCRM.name else 'Транспорт Битрикс24 включён. Проверьте адресата и поля перед подтверждением.'}
            token = confirmations.create(c,user,'crm.export',kind,payload.object_id,version,
                        {'input':payload.model_dump(),'draft':draft,'payload_hash':digest(draft),'preview':view})
            store.audit(c,user['id'],'crm_export_preview',object_type=kind,object_id=payload.object_id,
                        confirmation_id=token['confirmation_id'],stage='preview')
            return {**token,'preview':view}

    @api.post('/api/meet/crm/confirm')
    def confirm(payload: Token,request: Request):
        user = current_user(request)
        require(user,'crm.write',action='crm.confirm')
        with store.write_tx() as c:
            pending = confirmations.load(c,user,payload.confirmation_id,'crm.export',idempotency_key=payload.idempotency_key)
            data = pending['payload']['input']
            # Recheck read/write even for a replay, without calling the transport.
            if data['action']=='task.create':
                task = c.execute('SELECT meeting_id FROM tasks WHERE id=?',(data['object_id'],)).fetchone()
                if not task: raise denied(user,'task',data['object_id'])
                checked_meeting(c,user,task['meeting_id'])
            else: checked_meeting(c,user,data['object_id'])
            if pending.get('already'): return response(pending['result'],True)
            kind = 'task' if data['action']=='task.create' else 'meeting'
            old = c.execute('SELECT 1 FROM integration_outbox WHERE connector=? AND action=? AND object_type=? AND object_id=?',
                            (connector_name(),data['action'],kind,data['object_id'])).fetchone()
            if old: raise MeetError(409,'export_exists','Отправка уже зарегистрирована. Проверьте её статус.')
            # Revalidate the local SQLite mirror without injected read faults.
            # The fault is applied exactly once at the mock write boundary. A
            # future network adapter must not reuse this local-only atomic flow.
            if pending['payload']['preview']['connector']!=connector_name():
                raise MeetError(409,'connector_changed','Подключение изменилось. Нужен новый предпросмотр.')
            try: draft,version,_ = build(c,user,data,read_faults=False)
            except IntegrationError as error: raise integration_error(error,user) from None
            if version!=pending['object_version'] or digest(draft)!=pending['payload']['payload_hash']:
                raise MeetError(409,'stale','Задача, протокол, цитата или сопоставление изменились. Нужен новый предпросмотр.')
            key = digest([connector_name(),data['action'],kind,data['object_id']])
            oid = c.execute('INSERT INTO integration_outbox(connector,action,object_type,object_id,payload_hash,preview_json,status,idempotency_key,confirmation_id,confirmed_by,confirmed_at) VALUES (?,?,?,?,?,?,\'pending\',?,?,?,?)',
                (connector_name(),data['action'],kind,data['object_id'],digest(draft),json.dumps(pending['payload']['preview'],ensure_ascii=False),key,payload.confirmation_id,user['id'],store.now())).lastrowid
            try:
                crm = connector(c,user['id'])
                result = crm.create_task(draft,key) if kind=='task' else crm.attach_protocol(data['entity_ref'],draft,key)
                result = {'status':'sent','external_ref':result['ref'],'outbox_id':oid,'mode':('mock' if connector_name()==MockCRM.name else 'bitrix24')}
                c.execute("UPDATE integration_outbox SET status='sent',external_ref=? WHERE id=?",(result['external_ref'],oid))
                if kind=='task': c.execute('UPDATE tasks SET external_ref=?,version=version+1,updated_at=? WHERE id=?',
                                          (result['external_ref'],store.now(),data['object_id']))
            except IntegrationError as error:
                status = 'uncertain' if error.uncertain or error.code=='uncertain' else 'failed'
                c.execute('UPDATE integration_outbox SET status=?,last_error=? WHERE id=?',(status,error.code,oid))
                result = {'status':status,'outbox_id':oid,'code':error.code,'detail':str(error),'http_status':503,'mode':('mock' if connector_name()==MockCRM.name else 'bitrix24')}
            confirmations.finish(c,payload.confirmation_id,payload.idempotency_key,result)
            store.audit(c,user['id'],'crm_export_confirmed',object_type=kind,object_id=data['object_id'],
                        confirmation_id=payload.confirmation_id,result=result['status'],stage='confirm',error_code=result.get('code'))
            return response(result)

    @api.get('/api/meet/crm/tasks/{task_id}')
    def task_status(task_id: int,request: Request):
        user = current_user(request)
        with store.db() as c:
            row = c.execute('SELECT meeting_id,external_ref FROM tasks WHERE id=?',(task_id,)).fetchone()
            if not row or not store.can_read_meeting(c,user['id'],row['meeting_id']): raise denied(user,'task',task_id)
            outbox = c.execute("SELECT status,external_ref,last_error,confirmed_at FROM integration_outbox WHERE connector=? AND action='task.create' AND object_type='task' AND object_id=?",(connector_name(),task_id)).fetchone()
            try: external = connector(c,user['id']).get_task_status(row['external_ref']) if row['external_ref'] else None
            except IntegrationError as error: raise integration_error(error,user) from None
            return {'outbox':dict(outbox) if outbox else None,'external':external,'mode':('mock' if connector_name()==MockCRM.name else 'bitrix24')}

    @api.get('/api/meet/crm/orders/{order_no}')
    def order(order_no: str,request: Request):
        user = current_user(request)
        with store.db() as c:
            crm = connector(c,user['id'])
            try:
                row = crm.get_order(order_no)
                if not row: raise denied(user,'order',order_no)
                interactions = crm.find_interactions(order_no=order_no)
            except IntegrationError as error: raise integration_error(error,user) from None
            store.audit(c,user['id'],'crm_order_read',object_type='order',object_id=order_no)
            return {'order':row,'interactions':interactions,'warning':'Данные устарели.' if row['stale'] else None,'mode':('mock' if connector_name()==MockCRM.name else 'bitrix24')}

    @api.get('/api/meet/integrations')
    def integrations(request: Request):
        user = current_user(request); require(user,'integrations.manage',action='integrations.read')
        with store.db() as c:
            last = c.execute('SELECT MAX(confirmed_at) FROM integration_outbox').fetchone()[0]
            check = c.execute("SELECT at,result FROM audit WHERE action='integration_check' ORDER BY id DESC LIMIT 1").fetchone()
            return {'connectors':[{'name':connector_name(),'mode':('mock' if connector_name()==MockCRM.name else 'bitrix24'),'configured':(connector_name()==MockCRM.name or bool(os.getenv('MEETINGS_BITRIX_WEBHOOK'))),'last_export_at':last,
                                  'last_checked_at':check['at'] if check else None,'last_check_result':check['result'] if check else None,
                                  'notice':'SQLite-имитация; реальный портал не подключён.' if connector_name()==MockCRM.name else 'Транспорт Битрикс24; права остаются локальными.'}],
                    'mapped_employees':c.execute('SELECT COUNT(*) FROM user_external_ids WHERE connector=?',(connector_name(),)).fetchone()[0]}

    @api.get('/api/meet/crm/targets')
    def targets(meeting_id: int,request: Request):
        user = current_user(request); require(user,'crm.write',action='crm.targets')
        with store.db() as c:
            checked_meeting(c,user,meeting_id)
            sql,args = access.snapshot_predicate(c,user['id'],'d',own_column='responsible_user_id')
            rows = [{'ref':'deal:'+r['id'],'label':'Сделка '+r['id']+' · '+r['title']} for r in c.execute(
                'SELECT d.id,d.title FROM crm_deals d WHERE '+sql+' ORDER BY d.id',args)]
            rows += [{'ref':r['external_ref'],'label':'Задача · '+r['text']} for r in c.execute(
                'SELECT text,external_ref FROM tasks WHERE meeting_id=? AND external_ref IS NOT NULL ORDER BY id',(meeting_id,))]
            return {'targets':rows,'mode':('mock' if connector_name()==MockCRM.name else 'bitrix24')}

    @api.post('/api/meet/integrations/check')
    def check(request: Request):
        user = current_user(request); require(user,'integrations.manage',action='integrations.check')
        with store.db() as c:
            try:
                departments = connector(c,user['id']).list_departments()
                result = {'status':'ok','mode':('mock' if connector_name()==MockCRM.name else 'bitrix24'),'departments':len(departments),
                          'stale':any(d['stale'] for d in departments),'fetched_at':store.now()}
            except IntegrationError as error:
                store.audit(c,user['id'],'integration_check',object_type='integration',result='failed',error_code=error.code)
                return JSONResponse({'status':'error','code':error.code,'detail':str(error)},status_code=503)
            store.audit(c,user['id'],'integration_check',object_type='integration')
            return result

    return api
