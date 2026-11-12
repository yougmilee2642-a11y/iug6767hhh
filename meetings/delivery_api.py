"""SMTP is a second, explicit preview/confirm after a local invitation exists."""
from fastapi import APIRouter,Request,Path
from meetings import store,confirmations,smtp_delivery,notification_delivery
from meetings.api import ConfirmTokenIn
from meetings.auth import MeetError,MeetRoute,current_user,require
from meetings.connectors.mock import digest


def router():
    api=APIRouter(route_class=MeetRoute)
    @api.get('/api/meet/delivery-status')
    def status(request:Request):
        user=current_user(request)
        with store.db() as c:
            return {'smtp':smtp_delivery.gate(),'telegram':notification_delivery.destination(c,user['id'],'telegram').get('enabled',False),
                    'bitrix':notification_delivery.destination(c,user['id'],'bitrix').get('enabled',False)}

    @api.post('/api/meet/calendar/outbox/{invitation_id}/smtp/preview')
    def preview(request:Request,invitation_id:int=Path(gt=0,le=2**63-1)):
        user=current_user(request)
        with store.write_tx() as c:
            proof,_,_,display=smtp_delivery.plan(c,user,invitation_id)
            if c.execute('SELECT 1 FROM smtp_outbox WHERE invitation_id=?',(invitation_id,)).fetchone():
                raise MeetError(409,'smtp_already_queued','Для приглашения уже есть отправка. Проверьте её статус; автоматический повтор запрещён.')
            token=confirmations.create(c,user,'smtp.invitation','calendar_invitation',invitation_id,None,{'proof':digest(proof),'display':display})
            store.audit(c,user['id'],'smtp_preview',object_type='calendar_invitation',object_id=invitation_id,stage='preview',confirmation_id=token['confirmation_id'])
            return {**token,'preview':display,'notice':'Это внешняя отправка одному показанному получателю. Подтверждение поставит письмо в SMTP-очередь.'}

    @api.post('/api/meet/calendar/outbox/{invitation_id}/smtp/confirm')
    def confirm(body:ConfirmTokenIn,request:Request,invitation_id:int=Path(gt=0,le=2**63-1)):
        user=current_user(request);require(user,'calendar.invite',action='smtp.confirm')
        with store.write_tx() as c:
            p=confirmations.load(c,user,body.confirmation_id,'smtp.invitation','calendar_invitation',invitation_id,body.idempotency_key)
            if p['already']:return {**p['result'],'already_confirmed':True}
            proof,_,_,_=smtp_delivery.plan(c,user,invitation_id)
            if digest(proof)!=p['payload']['proof']:raise MeetError(409,'stale','Приглашение, адресат или конфигурация изменились. Нужен новый предпросмотр.')
            if c.execute('SELECT 1 FROM smtp_outbox WHERE invitation_id=?',(invitation_id,)).fetchone():raise MeetError(409,'smtp_already_queued','Письмо уже в очереди.')
            ident=c.execute('INSERT INTO smtp_outbox(invitation_id,user_id,proof,confirmation_id,created_at) VALUES (?,?,?,?,?)',
                (invitation_id,user['id'],digest(proof),body.confirmation_id,store.now())).lastrowid
            result={'outbox_id':ident,'status':'pending','delivery':'smtp_outbox'}
            confirmations.finish(c,body.confirmation_id,body.idempotency_key,result)
            store.audit(c,user['id'],'smtp_confirmed',object_type='calendar_invitation',object_id=invitation_id,stage='confirm',confirmation_id=body.confirmation_id)
            return {**result,'already_confirmed':False}

    @api.get('/api/meet/smtp-outbox')
    def outbox(request:Request):
        user=current_user(request);require(user,'calendar.view',action='smtp.outbox')
        with store.db() as c:
            return {'outbox':[dict(r) for r in c.execute('SELECT id,invitation_id,status,created_at,finished_at,error_code FROM smtp_outbox WHERE user_id=? ORDER BY id DESC LIMIT 100',(user['id'],))]}
    return api
