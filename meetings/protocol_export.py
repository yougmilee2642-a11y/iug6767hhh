"""Confirmed protocol export and local mass-mail outbox; no SMTP transport."""
import html
import json
import re
from email.message import EmailMessage
from email.policy import SMTP
from fastapi import APIRouter,Request
from fastapi.responses import Response
from pydantic import BaseModel,ConfigDict,Field
from meetings import access,confirmations,notifications,store,textutil
from meetings.api import ConfirmTokenIn,_meeting,denied
from meetings.auth import MeetError,MeetRoute,current_user,require
from meetings.connectors.mock import digest
from meetings.privacy import Masker,customer_names

LABELS={'decision':'Решение','task':'Поручение','proposal':'Предложение','risk':'Риск','open_question':'Открытый вопрос','summary':'Итог'}


def export(c,user,mid):
    meeting=_meeting(c,user,mid)
    lines=['# Протокол: '+meeting['title'],'','Сформировано: '+store.now(),'']
    items=[]
    for row in c.execute('SELECT * FROM protocol_items WHERE meeting_id=? AND confirmed_at IS NOT NULL ORDER BY position,id',(mid,)):
        item=dict(row);citations=[]
        for quote in json.loads(row['quotes']):
            uid=str(quote.get('utterance_id',''))
            if not re.fullmatch(r'U[1-9]\d{0,17}',uid):continue
            utterance=c.execute('SELECT text FROM utterances WHERE id=? AND meeting_id=? AND deleted=0',(int(uid[1:]),mid)).fetchone()
            if utterance and textutil.find_exact(quote.get('text',''),utterance['text']):
                citations.append({'quote':quote['text'],'path':'/api/meet/utterances/'+uid})
        manual=bool(row['task_id'] and c.execute('SELECT 1 FROM task_origins WHERE task_id=?',(row['task_id'],)).fetchone())
        lines.extend(['## '+LABELS.get(row['kind'],row['kind']),row['text'],
            'Подтвердил: '+str(store.user_name(c,row['confirmed_by']) or 'пользователь')+' · '+row['confirmed_at']])
        if row['assignee'] or row['due']:lines.append('Ответственный: '+str(row['assignee'] or 'требует уточнения')+'; срок: '+str(row['due'] or 'требует уточнения'))
        if manual:lines.append('Основание: ручное поручение пользователя, подтверждённое отдельно от записи.')
        elif not citations:lines.append('Первичный источник недоступен или удалён по политике хранения; требуется проверка.')
        for citation in citations:lines.extend(['> '+citation['quote'],'Источник: [открыть реплику]('+citation['path']+')'])
        lines.extend(['Встреча: [открыть встречу](/meetings#meeting-'+str(mid)+')',''])
        items.append({'id':row['id'],'text':row['text'],'confirmed_by':row['confirmed_by'],'confirmed_at':row['confirmed_at'],
                      'citations':citations,'manual':manual})
    if not items:raise MeetError(422,'no_confirmed_items','В протоколе нет подтверждённых пунктов.')
    return meeting,'\n'.join(lines),items


def mail_preview(c,user,mid,recipients):
    require(user,'calendar.invite',action='protocol.share')
    meeting,body,items=export(c,user,mid)
    if meeting['confidentiality']=='secret':raise MeetError(403,'secret_export_denied','Закрытый протокол не рассылается через ассистента.')
    if not access.object_decision(c,user['id'],'meeting',mid,'calendar.invite').allowed:raise denied(user,'meeting',mid,'protocol.share')
    permitted={meeting['owner_id'],*[r[0] for r in c.execute('SELECT user_id FROM meeting_access WHERE meeting_id=?',(mid,))]}
    permitted.update(r[0] for r in c.execute('SELECT p.user_id FROM calendar_event_participants p JOIN calendar_events e ON e.id=p.event_id WHERE e.meeting_id=?',(mid,)))
    selected=sorted(set(recipients or permitted))
    if not selected or len(selected)>30:raise MeetError(422,'invalid_recipients','Выберите от 1 до 30 участников встречи.')
    for uid in selected:
        recipient=access.load_user(c,uid)
        if uid not in permitted or not recipient or not recipient['active'] or not store.can_read_meeting(c,uid,mid,model=True):
            raise MeetError(422,'recipient_scope','Один из получателей больше не имеет доступа к встрече.')
    # Exclude generation timestamp from fingerprint; it is not a content change.
    proof={'meeting_id':mid,'version':meeting['version'],'items':items,'recipients':selected}
    return meeting,body,proof


class Mail(BaseModel):
    model_config=ConfigDict(extra='forbid')
    recipient_ids: list[int]=Field(default_factory=list,max_length=30)


def printable(body):
    # Escape first; turn only our own fixed local links into anchors. No HTML or
    # arbitrary Markdown from user/provider content is executed.
    rendered=[]
    for line in body.splitlines():
        safe=html.escape(line)
        safe=re.sub(r'\[(открыть реплику|открыть встречу)\]\((/api/meet/utterances/U[1-9]\d*|/meetings#meeting-[1-9]\d*)\)',
                    r'<a href="\2">\1</a>',safe)
        if safe.startswith('## '):rendered.append('<h2>'+safe[3:]+'</h2>')
        elif safe.startswith('# '):rendered.append('<h1>'+safe[2:]+'</h1>')
        elif safe:rendered.append('<p>'+safe+'</p>')
    return '<!doctype html><html lang="ru"><meta charset="utf-8"><title>Протокол</title><body>'+''.join(rendered)+'</body></html>'


def router():
    api=APIRouter(route_class=MeetRoute)

    @api.get('/api/meet/meetings/{meeting_id}/protocol/export')
    def download(meeting_id: int,request: Request,format: str='md'):
        user=current_user(request)
        if format not in ('md','html'):raise MeetError(422,'export_format','Доступны Markdown и HTML для печати.')
        with store.db() as c:
            _,body,_=export(c,user,meeting_id)
            store.audit(c,user['id'],'protocol_export',object_type='meeting',object_id=meeting_id,format=format)
        if format=='html':
            body=printable(body)
        return Response(body,media_type='text/html' if format=='html' else 'text/markdown',headers={
            'Content-Disposition':f'attachment; filename="protocol-{meeting_id}.{format}"','Cache-Control':'no-store'})

    @api.post('/api/meet/meetings/{meeting_id}/protocol/mail/preview')
    def preview(meeting_id: int,payload: Mail,request: Request):
        user=current_user(request)
        with store.write_tx() as c:
            meeting,body,proof=mail_preview(c,user,meeting_id,payload.recipient_ids)
            token=confirmations.create(c,user,'protocol.mail','meeting',meeting_id,meeting['version'],{'proof':proof,'hash':digest(proof)})
            store.audit(c,user['id'],'protocol_mail_preview',object_type='meeting',object_id=meeting_id,stage='preview',confirmation_id=token['confirmation_id'])
            return {**token,'preview':{'recipients':proof['recipients'],'body':Masker(customer_names()).text(body),
                    'notice':'Будут созданы внутренние уведомления и локальные EML. Реальные письма не отправляются.'}}

    @api.post('/api/meet/meetings/{meeting_id}/protocol/mail/confirm')
    def confirm(meeting_id: int,payload: ConfirmTokenIn,request: Request):
        user=current_user(request)
        with store.write_tx() as c:
            p=confirmations.load(c,user,payload.confirmation_id,'protocol.mail','meeting',meeting_id,payload.idempotency_key)
            _meeting(c,user,meeting_id)
            if p['already']:return {**p['result'],'already_confirmed':True}
            meeting,body,proof=mail_preview(c,user,meeting_id,p['payload']['proof']['recipients'])
            if digest(proof)!=p['payload']['hash']:raise MeetError(409,'stale','Протокол или доступ получателей изменились.')
            body=Masker(customer_names()).text(body)
            ids=[]
            for uid in proof['recipients']:
                ids.append(c.execute('INSERT INTO protocol_mail_outbox(meeting_id,recipient_id,confirmation_id,body,created_at) VALUES (?,?,?,?,?)',
                                    (meeting_id,uid,payload.confirmation_id,body,store.now())).lastrowid)
                notifications.emit(c,uid,'protocol_shared','meeting',meeting_id,'Доступен подтверждённый протокол встречи.',f'protocol:{payload.confirmation_id}:{uid}')
            result={'outbox_ids':ids,'status':'queued_local'}
            confirmations.finish(c,payload.confirmation_id,payload.idempotency_key,result)
            store.audit(c,user['id'],'protocol_mail_confirmed',object_type='meeting',object_id=meeting_id,stage='confirm',confirmation_id=payload.confirmation_id)
            return result

    @api.get('/api/meet/protocol-outbox/{outbox_id}/download.eml')
    def eml(outbox_id: int,request: Request):
        user=current_user(request)
        with store.db() as c:
            row=c.execute('SELECT * FROM protocol_mail_outbox WHERE id=?',(outbox_id,)).fetchone()
            if not row or not store.can_read_meeting(c,user['id'],row['meeting_id']) or not store.can_read_meeting(c,row['recipient_id'],row['meeting_id'],model=True):
                raise denied(user,'protocol_outbox',outbox_id,'protocol.download')
            if row['recipient_id']!=user['id'] and not access.object_decision(c,user['id'],'meeting',row['meeting_id'],'calendar.invite').allowed:
                raise denied(user,'protocol_outbox',outbox_id,'protocol.download')
            data=message_bytes(row)
            store.audit(c,user['id'],'protocol_mail_download',object_type='protocol_outbox',object_id=outbox_id)
            return Response(data,media_type='message/rfc822',headers={'Content-Disposition':f'attachment; filename="protocol-{outbox_id}.eml"'})

    return api


def message_bytes(row):
    message=EmailMessage(policy=SMTP)
    message['From']='focus@demo.invalid';message['To']=f"user-{row['recipient_id']}@demo.invalid"
    message['Subject']='Подтверждённый протокол встречи'
    message['Date']=store.parse_aware(row['created_at'])
    message['Message-ID']=f"<protocol-{row['id']}@focus.invalid>"
    message.set_content('Локальная очередь. Реальное письмо не отправлено.\n\n'+row['body'])
    return message.as_bytes()
