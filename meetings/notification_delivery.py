"""Opt-in generic notifications; durable claim before HTTP, no blind retry.

Tests inject transports. All three environment gates default closed. Old local
queues never become deliverable just because an administrator adds credentials.
"""
import json,os,re
from datetime import timedelta
from urllib.parse import urlsplit
from meetings import access,store,notifications
from meetings.auth import MeetError
from meetings.connectors.mock import digest

TEXT='Новое уведомление в Фокусе. Откройте рабочее место ассистента.'


def gate(channel):
    from providers.local_settings import local_only
    return (not local_only() and os.getenv('CALLWISE_CLOUD_INTEGRATIONS_ENABLED','false').lower()=='true'
            and os.getenv('MEETINGS_NOTIFICATION_DISPATCH_ENABLED','0')=='1'
            and (channel!='bitrix' or os.getenv('MEETINGS_BITRIX_ENABLED','0')=='1'))


def mapping(name,uid):
    try:
        raw=os.getenv(name,'{}')
        if len(raw)>100000:raise ValueError()
        value=json.loads(raw).get(str(uid))
        return str(value) if value is not None else ''
    except (ValueError,TypeError,AttributeError):return ''


def destination(c,uid,channel):
    if not gate(channel):return {'enabled':False,'mode':'local_outbox_only'}
    url=os.getenv('MEETINGS_PUBLIC_URL','').strip().rstrip('/')
    p=urlsplit(url)
    if p.scheme!='https' or not p.hostname or p.username or p.password or p.query or p.fragment:
        return {'enabled':False,'mode':'configuration_required'}
    if channel=='telegram':
        recipient=mapping('MEETINGS_TELEGRAM_RECIPIENTS',uid);secret=os.getenv('TELEGRAM_BOT_TOKEN','').strip()
        # Positive private chats only; groups are not notification recipients.
        if not re.fullmatch(r'[1-9]\d{0,17}',recipient) or not re.fullmatch(r'\d{4,15}:[A-Za-z0-9_-]{10,100}',secret):
            return {'enabled':False,'mode':'configuration_required'}
    elif channel=='bitrix':
        row=c.execute("SELECT external_id FROM user_external_ids WHERE user_id=? AND connector='bitrix24'",(uid,)).fetchone()
        recipient=str(row[0]) if row else '';secret=os.getenv('MEETINGS_BITRIX_WEBHOOK','')
        from meetings.connectors.bitrix24 import Bitrix24Connector
        try:Bitrix24Connector(c,uid,enabled=True,webhook=secret)
        except Exception:return {'enabled':False,'mode':'configuration_required'}
        if not re.fullmatch(r'[1-9]\d{0,17}',recipient):return {'enabled':False,'mode':'configuration_required'}
    else:return {'enabled':False,'mode':'local_outbox_only'}
    return {'enabled':True,'mode':'external_generic_only','recipient':recipient,'url':url+'/meetings',
            'config_hash':digest([channel,recipient,url,secret])}


def review(c,user,settings):
    return {channel:destination(c,user['id'],channel) for channel in ('telegram','bitrix') if settings[channel+'_enabled']}


def frozen(c,user_id,channel,settings):
    try:approved=json.loads(settings['delivery_proof']).get(channel)
    except (ValueError,TypeError):return None
    current=destination(c,user_id,channel)
    if not current.get('enabled') or approved!=current:return None
    return {'settings_version':settings['version'],'destination':current}


def valid(c,row):
    user=access.load_user(c,row['user_id'])
    if not user or not user['active'] or row['read_at'] or not notifications.readable(c,user['id'],row['object_type'],row['object_id']):return None
    settings=c.execute('SELECT * FROM notification_settings WHERE user_id=?',(user['id'],)).fetchone()
    if not settings or not settings[row['channel']+'_enabled']:return None
    payload=json.loads(row['payload']);proof=frozen(c,user['id'],row['channel'],settings)
    if not proof or payload.get('delivery')!=proof or payload.get('text')!=TEXT:return None
    if store.parse_aware(store.now())-store.parse_aware(row['created_at'])>timedelta(hours=24):return None
    return proof['destination']


def dispatch(*,telegram_transport=None,bitrix_transport=None):
    if not any(gate(ch) for ch in ('telegram','bitrix')):return 0
    sent=0
    with store.write_tx() as c:
        # A previous process may have exited after the provider accepted the send.
        c.execute("UPDATE notification_outbox SET status='uncertain',error_code='interrupted' WHERE status='sending'")
        ids=[r[0] for r in c.execute("SELECT id FROM notification_outbox WHERE channel IN ('telegram','bitrix') AND status='pending' ORDER BY id LIMIT 100")]
    for ident in ids:
        with store.write_tx() as c:
            row=c.execute('SELECT o.*,n.user_id,n.object_type,n.object_id,n.read_at FROM notification_outbox o JOIN notifications n ON n.id=o.notification_id WHERE o.id=?',(ident,)).fetchone()
            if not row or row['status']!='pending':continue
            dest=valid(c,row)
            if not dest:
                c.execute("UPDATE notification_outbox SET status='cancelled',error_code='consent_or_scope_changed',finished_at=? WHERE id=?",(store.now(),ident));continue
            c.execute("UPDATE notification_outbox SET status='sending' WHERE id=? AND status='pending'",(ident,))
            channel=row['channel'];uid=row['user_id']
        status='sent';code=None
        try:
            if channel=='telegram':
                from services.telegram_bot import TelegramClient,message
                message(TelegramClient(transport=telegram_transport),int(dest['recipient']),TEXT+'\n'+dest['url'])
            else:
                from meetings.connectors.bitrix24 import Bitrix24Connector
                with store.db() as c:
                    Bitrix24Connector(c,uid,transport=bitrix_transport).call('im.notify.personal.add',
                        {'USER_ID':dest['recipient'],'MESSAGE':TEXT+'\n'+dest['url']},write=True)
        except Exception as error:
            status='uncertain' if getattr(error,'uncertain',False) or getattr(error,'category','')=='unknown_delivery' else 'failed'
            # Only known stable categories, never exception strings/URLs/tokens.
            code='delivery_unknown' if status=='uncertain' else 'delivery_failed'
        with store.write_tx() as c:
            c.execute('UPDATE notification_outbox SET status=?,error_code=?,finished_at=? WHERE id=? AND status IN (\'sending\',\'uncertain\')',(status,code,store.now(),ident))
            store.audit(c,uid,'notification_delivery',object_type='notification_outbox',object_id=ident,result=status,channel=channel,error_code=code)
        sent+=status=='sent'
    return sent
