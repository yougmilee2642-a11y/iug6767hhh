import json
import threading
from datetime import timedelta
from fastapi import APIRouter, Request
from pydantic import BaseModel,ConfigDict,Field
from meetings import access,confirmations,notifications,retention,store
from meetings.api import ConfirmTokenIn
from meetings.auth import MeetError,MeetRoute,current_user,require
from meetings.connectors.mock import digest


class Policy(BaseModel):
    model_config=ConfigDict(extra='forbid')
    audio_after_confirm: bool=True
    transcript_days: int=Field(default=180,ge=1,le=3650)
    chat_days: int=Field(default=30,ge=1,le=3650)
    audit_days: int=Field(default=365,ge=30,le=3650)


class Channels(BaseModel):
    model_config=ConfigDict(extra='forbid')
    email_enabled: bool=False
    telegram_enabled: bool=False
    bitrix_enabled: bool=False


class Comment(BaseModel):
    model_config=ConfigDict(extra='forbid')
    text: str=Field(min_length=1,max_length=2000)


def task(c,user,tid):
    row=c.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone()
    if not row or not store.can_read_meeting(c,user['id'],row['meeting_id']):
        from meetings.api import denied
        raise denied(user,'task',tid,'task.comment')
    return row


def router():
    api=APIRouter(route_class=MeetRoute)

    @api.get('/api/meet/notifications')
    def inbox(request: Request):
        user=current_user(request)
        with store.db() as c:
            rows=[dict(r) for r in c.execute('SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 200',(user['id'],))
                  if notifications.readable(c,user['id'],r['object_type'],r['object_id'])]
            settings=c.execute('SELECT * FROM notification_settings WHERE user_id=?',(user['id'],)).fetchone()
            return {'notifications':rows,'unread':sum(not r['read_at'] for r in rows),'settings':dict(settings) if settings else {k:False for k in Channels.model_fields}}

    @api.post('/api/meet/notifications/{notification_id}/read')
    def mark(notification_id: int,request: Request):
        user=current_user(request)
        with store.write_tx() as c:
            row=c.execute('SELECT * FROM notifications WHERE id=? AND user_id=?',(notification_id,user['id'])).fetchone()
            if not row or not notifications.readable(c,user['id'],row['object_type'],row['object_id']):raise MeetError(404,'not_found','Уведомление недоступно.')
            c.execute('UPDATE notifications SET read_at=? WHERE id=?',(store.now(),notification_id))
            return {'status':'read'}

    @api.post('/api/meet/notification-settings/preview')
    def channel_preview(payload: Channels,request: Request):
        user=current_user(request)
        with store.write_tx() as c:
            old=c.execute('SELECT version FROM notification_settings WHERE user_id=?',(user['id'],)).fetchone()
            data=payload.model_dump()
            token=confirmations.create(c,user,'notification.settings','user',user['id'],old[0] if old else 0,data)
            store.audit(c,user['id'],'notification_settings_preview',object_type='user',object_id=user['id'],stage='preview',confirmation_id=token['confirmation_id'])
            return {**token,'preview':data,'notice':'Внешние каналы сохраняют сообщения в outbox; реальные аккаунты не подключены.'}

    @api.post('/api/meet/notification-settings/confirm')
    def channel_confirm(payload: ConfirmTokenIn,request: Request):
        user=current_user(request)
        with store.write_tx() as c:
            p=confirmations.load(c,user,payload.confirmation_id,'notification.settings','user',user['id'],payload.idempotency_key)
            if p['already']:return {**p['result'],'already_confirmed':True}
            old=c.execute('SELECT version FROM notification_settings WHERE user_id=?',(user['id'],)).fetchone()
            if (old[0] if old else 0)!=p['object_version']:raise MeetError(409,'stale','Настройки изменились. Проверьте заново.')
            data=p['payload']
            c.execute('INSERT INTO notification_settings(user_id,email_enabled,telegram_enabled,bitrix_enabled) VALUES (?,?,?,?) '
                      'ON CONFLICT(user_id) DO UPDATE SET email_enabled=excluded.email_enabled,telegram_enabled=excluded.telegram_enabled,bitrix_enabled=excluded.bitrix_enabled,version=version+1',
                      (user['id'],data['email_enabled'],data['telegram_enabled'],data['bitrix_enabled']))
            confirmations.finish(c,payload.confirmation_id,payload.idempotency_key,{'settings':data})
            store.audit(c,user['id'],'notification_settings_confirmed',object_type='user',object_id=user['id'],stage='confirm')
            return {'settings':data,'already_confirmed':False}

    @api.get('/api/meet/retention')
    def info(request: Request):
        user=current_user(request);require(user,'retention.manage',action='retention.read')
        with store.db() as c:
            return {'policy':retention.policy(c),'requests':[dict(r) for r in c.execute('SELECT id,user_id,status,requested_at FROM deletion_requests ORDER BY id DESC LIMIT 100')],
                    'last_run':dict(c.execute("SELECT at,details FROM audit WHERE action='retention_run' ORDER BY id DESC LIMIT 1").fetchone() or {})}

    @api.post('/api/meet/retention/policy/preview')
    def policy_preview(payload: Policy,request: Request):
        user=current_user(request);require(user,'retention.manage',action='retention.policy')
        with store.write_tx() as c:
            data=payload.model_dump();old=retention.policy(c)
            token=confirmations.create(c,user,'retention.policy','retention',1,old['version'],data)
            store.audit(c,user['id'],'retention_policy_preview',object_type='retention',stage='preview',confirmation_id=token['confirmation_id'])
            return {**token,'preview':data}

    @api.post('/api/meet/retention/policy/confirm')
    def policy_confirm(payload: ConfirmTokenIn,request: Request):
        user=current_user(request);require(user,'retention.manage',action='retention.policy')
        with store.write_tx() as c:
            p=confirmations.load(c,user,payload.confirmation_id,'retention.policy','retention',1,payload.idempotency_key)
            if p['already']:return {**p['result'],'already_confirmed':True}
            if retention.policy(c)['version']!=p['object_version']:raise MeetError(409,'stale','Политика изменилась.')
            d=p['payload'];c.execute('UPDATE retention_policy SET audio_after_confirm=?,transcript_days=?,chat_days=?,audit_days=?,version=version+1 WHERE id=1',
                (d['audio_after_confirm'],d['transcript_days'],d['chat_days'],d['audit_days']))
            result={'policy':retention.policy(c)};confirmations.finish(c,payload.confirmation_id,payload.idempotency_key,result)
            store.audit(c,user['id'],'retention_policy_confirmed',object_type='retention',stage='confirm')
            return result

    @api.post('/api/meet/retention/cleanup/preview')
    def cleanup_preview(request: Request):
        user=current_user(request);require(user,'retention.manage',action='retention.cleanup')
        with store.write_tx() as c:
            counts=retention.cleanup_preview(c)
            token=confirmations.create(c,user,'retention.cleanup','retention',1,None,{'counts':counts})
            store.audit(c,user['id'],'retention_cleanup_preview',object_type='retention',stage='preview',confirmation_id=token['confirmation_id'])
            return {**token,'preview':counts,'notice':'Удалятся все бизнес-данные помеченной тестовой БД. Пользователи и журнал останутся.'}

    @api.post('/api/meet/retention/cleanup/confirm')
    def cleanup_confirm(payload: ConfirmTokenIn,request: Request):
        user=current_user(request);require(user,'retention.manage',action='retention.cleanup')
        with store.write_tx() as c:
            p=confirmations.load(c,user,payload.confirmation_id,'retention.cleanup','retention',1,payload.idempotency_key)
            if p['already']:return {**p['result'],'already_confirmed':True}
            if retention.cleanup_preview(c)!=p['payload']['counts']:raise MeetError(409,'stale','Состав данных изменился. Проверьте очистку заново.')
            result={'deleted':retention.cleanup(c,payload.confirmation_id)}
            confirmations.finish(c,payload.confirmation_id,payload.idempotency_key,result)
            store.audit(c,user['id'],'retention_cleanup_confirmed',object_type='retention',stage='confirm')
            return result

    @api.post('/api/meet/privacy/delete-request')
    def request_deletion(request: Request):
        user=current_user(request)
        with store.write_tx() as c:
            old=c.execute("SELECT id FROM deletion_requests WHERE user_id=? AND status='pending'",(user['id'],)).fetchone()
            rid=old[0] if old else c.execute('INSERT INTO deletion_requests(user_id,requested_at) VALUES (?,?)',(user['id'],store.now())).lastrowid
            store.audit(c,user['id'],'data_deletion_requested',object_type='user',object_id=user['id'])
            return {'request_id':rid,'status':'pending'}

    @api.post('/api/meet/privacy/delete-requests/{request_id}/preview')
    def deletion_preview(request_id: int,request: Request):
        user=current_user(request);require(user,'retention.manage',action='privacy.delete')
        with store.write_tx() as c:
            row=c.execute("SELECT * FROM deletion_requests WHERE id=? AND status='pending'",(request_id,)).fetchone()
            if not row or row['user_id']==user['id']:raise MeetError(404,'not_found','Запрос недоступен.')
            data={'request_id':request_id,'user_id':row['user_id'],
                  'meetings':c.execute('SELECT count(*) FROM meetings WHERE owner_id=?',(row['user_id'],)).fetchone()[0],
                  'documents':c.execute('SELECT count(*) FROM documents WHERE owner_id=?',(row['user_id'],)).fetchone()[0]}
            token=confirmations.create(c,user,'privacy.delete','deletion_request',request_id,None,data)
            return {**token,'preview':data,'notice':'Удалятся личные диалоги, свои документы и встречи (включая совместные), обратная связь и уведомления. Учётная запись деактивируется. Назначения в чужих задачах обезличиваются. Аудит и чужие бизнес-записи сохраняются по политике.'}

    @api.post('/api/meet/privacy/delete-requests/{request_id}/confirm')
    def deletion_confirm(request_id: int,payload: ConfirmTokenIn,request: Request):
        user=current_user(request);require(user,'retention.manage',action='privacy.delete')
        with store.write_tx() as c:
            p=confirmations.load(c,user,payload.confirmation_id,'privacy.delete','deletion_request',request_id,payload.idempotency_key)
            if p['already']:return {**p['result'],'already_confirmed':True}
            row=c.execute("SELECT * FROM deletion_requests WHERE id=? AND status='pending'",(request_id,)).fetchone()
            if not row or row['user_id']!=p['payload']['user_id']:raise MeetError(409,'stale','Запрос изменился.')
            # Counts are reviewable; a new owned file/meeting requires another preview.
            for key,table in [('meetings','meetings'),('documents','documents')]:
                if c.execute('SELECT count(*) FROM '+table+' WHERE owner_id=?',(row['user_id'],)).fetchone()[0]!=p['payload'][key]:
                    raise MeetError(409,'stale','Состав личных данных изменился. Проверьте удаление заново.')
            result={'deleted':retention.delete_user(c,row['user_id'])}
            c.execute("UPDATE deletion_requests SET status='confirmed',confirmed_by=?,confirmed_at=? WHERE id=?",(user['id'],store.now(),request_id))
            confirmations.finish(c,payload.confirmation_id,payload.idempotency_key,result)
            store.audit(c,user['id'],'data_deletion_confirmed',object_type='user',object_id=row['user_id'],stage='confirm')
            return result

    @api.get('/api/meet/tasks/{task_id}/comments')
    def comments(task_id: int,request: Request):
        user=current_user(request)
        with store.db() as c:
            task(c,user,task_id)
            return {'comments':[dict(r) for r in c.execute('SELECT id,user_id,text,created_at FROM task_comments WHERE task_id=? ORDER BY id',(task_id,))],
                    'history':[dict(r) for r in c.execute('SELECT user_id,before_json,after_json,created_at FROM task_history WHERE task_id=? ORDER BY id',(task_id,))]}

    @api.post('/api/meet/tasks/{task_id}/comments')
    def add_comment(task_id: int,payload: Comment,request: Request):
        user=current_user(request);require(user,'feedback.create',action='task.comment')
        with store.write_tx() as c:
            task(c,user,task_id)
            if not payload.text.strip():raise MeetError(422,'empty_comment','Введите комментарий.')
            ident=c.execute('INSERT INTO task_comments(task_id,user_id,text,created_at) VALUES (?,?,?,?)',(task_id,user['id'],payload.text.strip(),store.now())).lastrowid
            store.audit(c,user['id'],'task_comment',object_type='task',object_id=task_id)
            return {'comment_id':ident}

    return api


def install_background(app):
    stop=threading.Event();started=[];path=store.db_path().resolve()
    def loop():
        while not stop.is_set():
            if store.db_path().resolve()!=path:return
            try:
                with store.write_tx() as c:
                    deleted=retention.clean(c);created=notifications.tick(c)
                    from meetings.local_outbox import write
                    files=write(c)
                    store.audit(c,None,'retention_run',object_type='retention',deleted=deleted,notifications=created,outbox_files=files)
            except Exception:
                # No provider messages, paths or personal text in logs.
                import logging
                logging.getLogger(__name__).error('maintenance_failed')
            stop.wait(60)
    def start():
        thread=threading.Thread(target=loop,name='focus-maintenance',daemon=True);started.append(thread);thread.start()
    def finish():
        stop.set()
        for thread in started:thread.join(timeout=1)
    app.add_event_handler('startup',start);app.add_event_handler('shutdown',finish)
