"""One reviewed calendar invitation per SMTP outbox row. Default off; TLS only."""
import hashlib,json,os,re,smtplib,ssl
from datetime import timedelta
from email.message import EmailMessage
from email.policy import SMTP
from meetings import access,store
from meetings.auth import MeetError,require
from meetings.connectors.mock import digest
from meetings.notification_delivery import mapping


def gate():
    from providers.local_settings import local_only
    return (not local_only() and os.getenv('CALLWISE_CLOUD_INTEGRATIONS_ENABLED','false').lower()=='true'
            and os.getenv('MEETINGS_SMTP_ENABLED','0')=='1')


def address(value):
    if len(value)>254 or not re.fullmatch(r'[A-Za-z0-9.!#$%&*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?',value):
        raise MeetError(503,'smtp_config','Настройте проверенный адрес отправителя и получателя.')
    return value


def configuration(uid):
    if not gate():raise MeetError(503,'smtp_disabled','SMTP отключён. Используйте локальный EML.')
    host=os.getenv('MEETINGS_SMTP_HOST','');username=os.getenv('MEETINGS_SMTP_USERNAME','');password=os.getenv('MEETINGS_SMTP_PASSWORD','')
    try:port=int(os.getenv('MEETINGS_SMTP_PORT','465'))
    except ValueError:port=0
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}',host) or not 1<=port<=65535 or not username or not password:
        raise MeetError(503,'smtp_config','Настройте SMTP_SSL на сервере.')
    sender=address(os.getenv('MEETINGS_SMTP_FROM',''));recipient=address(mapping('MEETINGS_EMAIL_RECIPIENTS',uid))
    return {'host':host,'port':port,'username':username,'password':password,'sender':sender,'recipient':recipient}


def plan(c,user,invitation_id):
    require(user,'calendar.invite',action='smtp.preview')
    row=c.execute('SELECT o.*,e.organizer_id,e.meeting_id,e.status AS event_status FROM calendar_outbox o JOIN calendar_events e ON e.id=o.event_id WHERE o.id=? AND e.organizer_id=?',
                  (invitation_id,user['id'])).fetchone()
    if not row or not row['meeting_id'] or row['event_status']!='confirmed':raise MeetError(404,'not_found','Приглашение недоступно.')
    recipient=access.load_user(c,row['recipient_id'])
    if not recipient or not recipient['active'] or not store.can_read_meeting(c,user['id'],row['meeting_id'],model=True) or not store.can_read_meeting(c,recipient['id'],row['meeting_id'],model=True):
        raise MeetError(404,'not_found','Участник или материалы недоступны.')
    from meetings.calendar.interchange import export_events
    from meetings.calendar import ics
    event=export_events(c,user,row['event_id'])[0];config=configuration(row['recipient_id'])
    mail=EmailMessage(policy=SMTP);mail['From']=config['sender'];mail['To']=config['recipient']
    mail['Subject']='Приглашение: '+event['title'].replace('\r',' ').replace('\n',' ')
    mail['Message-ID']=f'<focus-invitation-{invitation_id}@focus.invalid>'
    text=event['title']+'\n'+event['start_at']+' — '+event['end_at']+'\nЧасовой пояс: '+event['timezone']
    mail.set_content(text);calendar=ics.calendar([event]);mail.add_attachment(calendar,maintype='text',subtype='calendar',filename='invitation.ics')
    # MIME boundary is random, so bind semantic content and exact ICS, not bytes.
    proof={'invitation_id':invitation_id,'event':event,'sender':config['sender'],'recipient':config['recipient'],
           'configuration_hash':digest(config),'ics_sha256':hashlib.sha256(calendar).hexdigest()}
    return proof,mail,config,{'sender':config['sender'],'recipient':config['recipient'],'subject':str(mail['Subject']),
        'text':text,'attachment':'invitation.ics','start_at':event['start_at'],'end_at':event['end_at'],'timezone':event['timezone']}


def send(mail,config):
    with smtplib.SMTP_SSL(config['host'],config['port'],timeout=10,context=ssl.create_default_context()) as client:
        client.login(config['username'],config['password'])
        refused=client.send_message(mail,from_addr=config['sender'],to_addrs=[config['recipient']])
        if refused:raise smtplib.SMTPRecipientsRefused(refused)


def dispatch(*,sender=None):
    if not gate():return 0
    sender=sender or send;count=0
    with store.write_tx() as c:
        c.execute("UPDATE smtp_outbox SET status='uncertain',error_code='interrupted' WHERE status='sending'")
        ids=[r[0] for r in c.execute("SELECT id FROM smtp_outbox WHERE status='pending' ORDER BY id LIMIT 100")]
    for ident in ids:
        with store.write_tx() as c:
            row=c.execute('SELECT * FROM smtp_outbox WHERE id=?',(ident,)).fetchone()
            if not row or row['status']!='pending':continue
            user=access.load_user(c,row['user_id'])
            try:
                if not user or not user['active']:raise MeetError(404,'not_found','')
                proof,mail,config,_=plan(c,user,row['invitation_id'])
                if digest(proof)!=row['proof'] or store.parse_aware(store.now())-store.parse_aware(row['created_at'])>timedelta(hours=24):
                    raise MeetError(409,'stale','')
            except MeetError:
                c.execute("UPDATE smtp_outbox SET status='cancelled',error_code='consent_or_scope_changed',finished_at=? WHERE id=?",(store.now(),ident));continue
            c.execute("UPDATE smtp_outbox SET status='sending' WHERE id=?",(ident,))
        status='sent';code=None
        try:sender(mail,config)
        except smtplib.SMTPRecipientsRefused:status='failed';code='recipient_rejected'
        except Exception:status='uncertain';code='delivery_unknown'
        with store.write_tx() as c:
            c.execute('UPDATE smtp_outbox SET status=?,error_code=?,finished_at=? WHERE id=? AND status IN (\'sending\',\'uncertain\')',(status,code,store.now(),ident))
            store.audit(c,user['id'],'smtp_delivery',object_type='calendar_invitation',object_id=row['invitation_id'],result=status,error_code=code)
        count+=status=='sent'
    return count
