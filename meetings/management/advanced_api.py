"""Extra read reports and explicit confirmations; external sends are not used."""
from datetime import datetime,timezone
import json
from fastapi import APIRouter,Request,Response,Path
from pydantic import BaseModel,ConfigDict,Field
from meetings import access,confirmations,store,effect_checks,weekly_digest
from meetings.api import ConfirmTokenIn
from meetings.auth import MeetError,MeetRoute,current_user,require
from meetings.connectors.mock import digest
from meetings.management import advanced,service


class Week(BaseModel):
    model_config=ConfigDict(extra='forbid')
    period_end:str=Field(pattern=r'^\d{4}-\d{2}-\d{2}$')


class Effect(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    protocol_item_id:int=Field(gt=0,le=2**63-1)
    metric_key:str=Field(pattern='^(on_time_orders|defect_rate|capacity_utilization)$')
    target_value:float=Field(ge=0,le=1000)
    direction:str=Field(pattern='^(le|ge)$')
    days:int=Field(default=7,ge=1,le=90)


def router():
    api=APIRouter(route_class=MeetRoute)
    @api.get('/api/meet/advanced-overview')
    def overview(request:Request):
        user=current_user(request);now=datetime.now(timezone.utc)
        with store.db() as c:
            c.execute('BEGIN')
            result,_=advanced.build(c,user,now,now)
            store.audit(c,user['id'],'advanced_overview',object_type='metric',source_ids=[m['source']['id'] for m in result['metrics']])
            return result

    @api.post('/api/meet/briefing/weekly/preview')
    def weekly_preview(body:Week,request:Request):
        user=current_user(request)
        with store.write_tx() as c:
            result=weekly_digest.build(c,user,body.period_end,store.now())
            token=confirmations.create(c,user,'weekly.digest','user',user['id'],None,result)
            store.audit(c,user['id'],'weekly_preview',object_type='user',object_id=user['id'],stage='preview',confirmation_id=token['confirmation_id'])
            return {**token,'preview':result}

    @api.post('/api/meet/briefing/weekly/confirm')
    def weekly_confirm(body:ConfirmTokenIn,request:Request):
        user=current_user(request);require(user,'overview.read',action='weekly.confirm')
        with store.write_tx() as c:
            p=confirmations.load(c,user,body.confirmation_id,'weekly.digest','user',user['id'],body.idempotency_key)
            if p['already']:return {**p['result'],'already_confirmed':True}
            old=p['payload'];current=weekly_digest.build(c,user,old['period_end'],old['generated_at'])
            if digest(current)!=digest(old):raise MeetError(409,'stale','Дайджест или права изменились. Проверьте новый предпросмотр.')
            ident=c.execute('INSERT INTO weekly_digest_outbox(user_id,period_end,payload,payload_hash,confirmation_id,created_at) VALUES (?,?,?,?,?,?)',
                (user['id'],old['period_end'],json.dumps(old,ensure_ascii=False),digest(old),body.confirmation_id,store.now())).lastrowid
            result={'outbox_id':ident,'delivery':'local_outbox_only','path':f'/api/meet/briefing/weekly/outbox/{ident}.eml'}
            confirmations.finish(c,body.confirmation_id,body.idempotency_key,result)
            store.audit(c,user['id'],'weekly_confirmed',object_type='user',object_id=user['id'],stage='confirm',confirmation_id=body.confirmation_id)
            return {**result,'already_confirmed':False}

    @api.get('/api/meet/briefing/weekly/outbox')
    def weekly_outbox(request:Request):
        user=current_user(request);require(user,'overview.read',action='weekly.outbox')
        with store.db() as c:return {'outbox':[dict(r) for r in c.execute('SELECT id,period_end,created_at,status FROM weekly_digest_outbox WHERE user_id=? ORDER BY id DESC LIMIT 100',(user['id'],))]}

    @api.get('/api/meet/briefing/weekly/outbox/{outbox_id}.eml')
    def download(request:Request,outbox_id:int=Path(gt=0,le=2**63-1)):
        user=current_user(request);require(user,'overview.read',action='weekly.download')
        with store.db() as c:
            c.execute('BEGIN')
            row=c.execute('SELECT * FROM weekly_digest_outbox WHERE id=? AND user_id=?',(outbox_id,user['id'])).fetchone()
            if not row:raise MeetError(404,'not_found','Письмо недоступно.')
            data=weekly_digest.message(c,user,row)
            store.audit(c,user['id'],'weekly_download',object_type='user',object_id=user['id'])
        return Response(data,media_type='message/rfc822',headers={'Content-Disposition':f'attachment; filename="weekly-{outbox_id}.eml"','Cache-Control':'no-store'})

    @api.get('/api/meet/effect-checks')
    def effects(request:Request):
        user=current_user(request)
        with store.db() as c:
            c.execute('BEGIN')
            return {'checks':effect_checks.visible(c,user)}

    @api.post('/api/meet/effect-checks/preview')
    def effect_preview(body:Effect,request:Request):
        user=current_user(request)
        with store.write_tx() as c:
            plan=effect_checks.plan(c,user,body.model_dump(),store.now())
            token=confirmations.create(c,user,'decision.effect','protocol_item',body.protocol_item_id,None,plan)
            store.audit(c,user['id'],'effect_preview',object_type='meeting',object_id=plan['meeting_id'],stage='preview',confirmation_id=token['confirmation_id'])
            return {**token,'preview':plan,'notice':'Будет проверено достижение числовой цели на свежем снимке. Это не доказательство причинного эффекта решения.'}

    @api.post('/api/meet/effect-checks/confirm')
    def effect_confirm(body:ConfirmTokenIn,request:Request):
        user=current_user(request);require(user,'overview.read',action='effect.confirm')
        with store.write_tx() as c:
            p=confirmations.load(c,user,body.confirmation_id,'decision.effect',idempotency_key=body.idempotency_key)
            old=p['payload'];params=old['input']
            item,_,_=effect_checks.basis(c,user,params['protocol_item_id'],write=True)
            if not store.can_read_meeting(c,user['id'],item['meeting_id'],model=True):raise MeetError(404,'not_found','Решение недоступно.')
            if p['already']:return {**p['result'],'already_confirmed':True}
            if digest(effect_checks.plan(c,user,params,old['observed']))!=digest(old):raise MeetError(409,'stale','Решение, метрика или права изменились. Нужен новый предпросмотр.')
            ident=c.execute('INSERT INTO task_effect_checks(protocol_item_id,owner_id,metric_key,baseline,baseline_json,target_value,direction,check_at,created_at,department_id,confirmation_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (params['protocol_item_id'],user['id'],params['metric_key'],old['baseline']['value'],json.dumps(old['baseline'],ensure_ascii=False),params['target_value'],params['direction'],old['check_at'],store.now(),old['department_id'],body.confirmation_id)).lastrowid
            result={'check_id':ident,'check_at':old['check_at'],'status':'scheduled'}
            confirmations.finish(c,body.confirmation_id,body.idempotency_key,result)
            store.audit(c,user['id'],'effect_confirmed',object_type='meeting',object_id=old['meeting_id'],stage='confirm',confirmation_id=body.confirmation_id)
            return {**result,'already_confirmed':False}
    return api
