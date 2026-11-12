"""Decision controls are explicit human actions, never model side effects."""
from datetime import date
import hashlib
import json
import re

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from meetings import access, confirmations, store, textutil
from meetings.auth import MeetError, MeetRoute, current_user, require, forbidden
from meetings.privacy import source_is_injection


def missing(user,item_id):
    return MeetError(404,'not_found','Не найдено или нет доступа.',audit={'user_id':user['id'],'action':'access_denied',
        'object_type':'protocol_item','object_id':item_id,'result':'denied','error_code':'not_found'})


def basis(connection,user,item_id,write=False):
    item = connection.execute('SELECT i.*,m.department_id FROM protocol_items i JOIN meetings m ON m.id=i.meeting_id WHERE i.id=?',(item_id,)).fetchone()
    if not item or not store.can_read_meeting(connection,user['id'],item['meeting_id']): raise missing(user,item_id)
    if write:
        require(user,'protocol.confirm','protocol_item',item_id,'decision.control')
        if not access.object_decision(connection,user['id'],'meeting',item['meeting_id'],'protocol.confirm').allowed:
            raise forbidden(user,'protocol.confirm','protocol_item',item_id,'decision.control')
    if item['kind']!='decision': raise MeetError(422,'not_a_decision','На контроль ставится пункт с типом «Решение».')
    proof = None
    for quote in json.loads(item['quotes']):
        uid = str(quote.get('utterance_id',''))
        if not re.fullmatch(r'U[1-9]\d{0,17}',uid): continue
        utterance = connection.execute('SELECT * FROM utterances WHERE id=? AND meeting_id=? AND deleted=0',(int(uid[1:]),item['meeting_id'])).fetchone()
        if utterance and textutil.find_exact(quote.get('text',''),utterance['text']):
            proof = {'utterance_id':uid,'text':utterance['text'],'speaker':utterance['speaker_label']}; break
    fingerprint = hashlib.sha256(json.dumps({'text':item['text'],'quotes':json.loads(item['quotes']),
                                            'proof':proof},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    return dict(item),proof,fingerprint


def visible(connection,actor,model=False):
    predicate,args = access.predicate(connection,actor,'meeting','m',model=model)
    return [dict(r) for r in connection.execute('SELECT d.*,i.meeting_id,i.text,m.department_id,u.name AS owner_name '
        'FROM decision_controls d JOIN protocol_items i ON i.id=d.protocol_item_id JOIN meetings m ON m.id=i.meeting_id '
        'LEFT JOIN users u ON u.id=d.owner_user_id WHERE '+predicate+' ORDER BY COALESCE(d.due,\'9999\'),d.id',args)]


class Draft(BaseModel):
    model_config = ConfigDict(extra='forbid')
    owner_user_id: int | None = Field(default=None,gt=0)
    due: str | None = Field(default=None,max_length=10)
    status: str = Field(default='open',pattern='^(open|done|cancelled)$')


class Token(BaseModel):
    model_config = ConfigDict(extra='forbid')
    confirmation_id: str = Field(min_length=8,max_length=100)
    idempotency_key: str = Field(min_length=8,max_length=100)


def normalized(connection,user,item,data):
    result = dict(data)
    if result['due']:
        try: result['due'] = date.fromisoformat(result['due']).isoformat()
        except ValueError: raise MeetError(422,'invalid_date','Срок должен быть датой ГГГГ-ММ-ДД.') from None
    owner = connection.execute('SELECT id,level,department_id FROM users WHERE id=? AND active=1',(result['owner_user_id'],)).fetchone() if result['owner_user_id'] else None
    if result['owner_user_id'] and (not owner or owner['level'] in ('admin','auditor')):
        raise MeetError(422,'invalid_owner','Выберите действующего ответственного сотрудника.')
    if owner and user.get('level')=='lead':
        allowed = {user['department_id']}
        if item['department_id'] in user.get('_delegated_departments',[]): allowed.add(item['department_id'])
        if owner['department_id'] not in allowed: raise forbidden(user,'protocol.confirm','protocol_item',item['id'],'decision.assign_department')
    return result


def router():
    api = APIRouter(route_class=MeetRoute)

    @api.get('/api/meet/decisions')
    def controls(request: Request):
        user = current_user(request); require(user,'meetings.read',action='decision.read')
        with store.db() as c:
            result = visible(c,user['id'])
            for row in result:
                _,proof,_ = basis(c,user,row['protocol_item_id'])
                row['source_quote'] = json.loads(row['source_quote'])
                row['source_status'] = 'verified' if proof else 'needs_review'
            store.audit(c,user['id'],'decision_controls_read',object_type='decision',rows=len(result))
            return {'decisions':result}

    @api.post('/api/meet/decisions/{item_id}/preview')
    def preview(item_id: int,payload: Draft,request: Request):
        user = current_user(request)
        with store.write_tx() as c:
            item,proof,fingerprint = basis(c,user,item_id,write=True)
            before = c.execute('SELECT * FROM decision_controls WHERE protocol_item_id=?',(item_id,)).fetchone()
            if not before and (not proof or source_is_injection(item['text']) or source_is_injection(proof['text'])):
                raise MeetError(422,'source_quote_required','Нужна проверяемая реплика для решения; уточните протокол.')
            data = normalized(c,user,item,payload.model_dump())
            view = {'protocol_item_id':item_id,'meeting_id':item['meeting_id'],'text':item['text'],
                    'before':{k:before[k] for k in ('owner_user_id','due','status')} if before else None,'after':data,
                    'source_quote':proof or json.loads(before['source_quote'])}
            token = confirmations.create(c,user,'decision.control','protocol_item',item_id,before['version'] if before else 0,
                                         {'changes':data,'basis_sha256':fingerprint,'preview':view})
            store.audit(c,user['id'],'decision_control_preview',object_type='protocol_item',object_id=item_id,
                        confirmation_id=token['confirmation_id'],source_ids=[view['source_quote']['utterance_id']])
            return {**token,'preview':view}

    @api.post('/api/meet/decisions/{item_id}/confirm')
    def confirm(item_id: int,payload: Token,request: Request):
        user = current_user(request)
        with store.write_tx() as c:
            item,proof,fingerprint = basis(c,user,item_id,write=True)
            pending = confirmations.load(c,user,payload.confirmation_id,'decision.control','protocol_item',item_id,payload.idempotency_key)
            if pending.get('already'): return {**pending['result'],'already_confirmed':True}
            old = c.execute('SELECT * FROM decision_controls WHERE protocol_item_id=?',(item_id,)).fetchone()
            if pending['object_version'] != (old['version'] if old else 0) or fingerprint!=pending['payload']['basis_sha256']:
                raise MeetError(409,'stale','Решение или контроль изменились после предпросмотра.')
            data = normalized(c,access.load_user(c,user['id']),item,pending['payload']['changes'])
            stamp = store.now()
            if old:
                cid = old['id']
                c.execute('UPDATE decision_controls SET owner_user_id=?,due=?,status=?,updated_at=?,version=version+1 WHERE id=?',
                          (data['owner_user_id'],data['due'],data['status'],stamp,cid))
            else:
                if not proof: raise MeetError(409,'stale','Реплика-основание изменилась; проверьте решение заново.')
                cid = c.execute('INSERT INTO decision_controls(protocol_item_id,owner_user_id,due,status,source_quote,confirmed_by,confirmation_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)',
                    (item_id,data['owner_user_id'],data['due'],data['status'],json.dumps(proof,ensure_ascii=False),user['id'],payload.confirmation_id,stamp,stamp)).lastrowid
                c.execute('UPDATE protocol_items SET confirmed_by=?,confirmed_at=? WHERE id=?',(user['id'],stamp,item_id))
            result = {'decision_control_id':cid,'protocol_item_id':item_id}
            confirmations.finish(c,payload.confirmation_id,payload.idempotency_key,result)
            store.audit(c,user['id'],'decision_control_confirmed',object_type='decision',object_id=cid,
                        confirmation_id=payload.confirmation_id,fields=list(data),source_ids=[(proof or json.loads(old['source_quote']))['utterance_id']])
            return {**result,'already_confirmed':False}

    return api
