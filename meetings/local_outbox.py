"""Exclusive local EML artifacts. No SMTP, Telegram or external service calls."""
import os
from pathlib import Path
import tempfile
from email.message import EmailMessage
from email.policy import SMTP
from meetings import access,store


def folder():
    path=Path(os.getenv('MEETINGS_OUTBOX_DIR') or store.db_path().resolve().parent/'outbox').absolute()
    if path.is_symlink():raise ValueError('outbox_symlink')
    path.mkdir(parents=True,exist_ok=True,mode=0o700)
    return path.resolve()


def exclusive(root,name,data):
    target=root/name
    if target.exists() or target.is_symlink():return False
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=root,prefix='.focus-',delete=False) as output:
            temporary=Path(output.name);output.write(data)
        try:os.link(temporary,target)
        except FileExistsError:return False
        return True
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)


def write(c):
    root=folder();count=0
    from meetings.calendar import service,ics
    from meetings.calendar.interchange import export_events,stamp_hash
    from meetings.auth import has_capability
    for row in c.execute('SELECT o.*,e.organizer_id,e.meeting_id FROM calendar_outbox o JOIN calendar_events e ON e.id=o.event_id'):
        user=access.load_user(c,row['organizer_id'])
        if not user or not has_capability(user,'calendar.view') or not row['meeting_id']:continue
        if not store.can_read_meeting(c,row['recipient_id'],row['meeting_id'],model=True):continue
        try:event=export_events(c,user,row['event_id'])[0]
        except Exception:continue
        message=EmailMessage(policy=SMTP)
        message['From']=f"user-{row['organizer_id']}@demo.invalid";message['To']=f"user-{row['recipient_id']}@demo.invalid"
        message['Subject']='Приглашение: '+event['title'].replace('\r',' ').replace('\n',' ')
        message['Date']=store.parse_aware(event['created_at'])
        message['Message-ID']=f"<{stamp_hash(event['uid']+':'+str(row['recipient_id']))}@callwise.invalid>"
        message.set_content('Локальная очередь. Письмо не отправлено.\n'+event['title']+'\n'+event['start_at'])
        message.add_attachment(ics.calendar([event]),maintype='text',subtype='calendar',filename='invitation.ics')
        count+=exclusive(root,f"invitation-{row['id']}.eml",message.as_bytes())
    from meetings.protocol_export import message_bytes
    for row in c.execute('SELECT * FROM protocol_mail_outbox'):
        if store.can_read_meeting(c,row['recipient_id'],row['meeting_id'],model=True):
            count+=exclusive(root,f"protocol-{row['id']}.eml",message_bytes(row))
    # Optional channels remain queued, except the file e-mail adapter.
    for row in c.execute("SELECT o.*,n.user_id,n.object_type,n.object_id FROM notification_outbox o JOIN notifications n ON n.id=o.notification_id WHERE o.channel='email'"):
        from meetings.notifications import readable
        if not readable(c,row['user_id'],row['object_type'],row['object_id']):continue
        import json
        payload=json.loads(row['payload']);message=EmailMessage(policy=SMTP)
        message['From']='focus@demo.invalid';message['To']=f"user-{row['user_id']}@demo.invalid"
        message['Subject']='Уведомление Фокус';message.set_content(payload['text']+'\n'+payload['path'])
        count+=exclusive(root,f"notification-{row['id']}.eml",message.as_bytes())
    from meetings.weekly_digest import message as weekly_message
    for row in c.execute('SELECT * FROM weekly_digest_outbox'):
        user=access.load_user(c,row['user_id'])
        if not user or not user['active']:continue
        try:data=weekly_message(c,user,row)
        except Exception:continue
        count+=exclusive(root,f"weekly-{row['id']}.eml",data)
    return count
