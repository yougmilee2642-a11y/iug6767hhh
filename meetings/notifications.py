"""Internal notifications and opt-in outbox. Tick never changes tasks or meetings."""
import json
from datetime import date,timedelta
from meetings import access,store
from meetings.auth import has_capability


def readable(c,user_id,kind,ident):
    user=access.load_user(c,user_id)
    if not user or not user['active']:return False
    if kind=='task':
        row=c.execute('SELECT meeting_id FROM tasks WHERE id=?',(ident,)).fetchone()
        return bool(row and store.can_read_meeting(c,user_id,row[0],model=True))
    if kind=='meeting':return store.can_read_meeting(c,user_id,int(ident),model=True)
    if kind=='media_job':
        row=c.execute('SELECT meeting_id FROM media_jobs WHERE id=?',(ident,)).fetchone()
        return bool(row and row[0] and store.can_read_meeting(c,user_id,row[0],model=True))
    return kind=='briefing' and has_capability(user,'overview.read')


def emit(c,user_id,kind,obj_type,obj_id,message,dedupe):
    if not readable(c,user_id,obj_type,obj_id):return None
    stamp=store.now()
    cursor=c.execute('INSERT OR IGNORE INTO notifications(user_id,kind,object_type,object_id,message,created_at,dedupe_key) VALUES (?,?,?,?,?,?,?)',
                     (user_id,kind,obj_type,str(obj_id),message,stamp,dedupe))
    if not cursor.rowcount:return None
    nid=cursor.lastrowid
    settings=c.execute('SELECT * FROM notification_settings WHERE user_id=?',(user_id,)).fetchone()
    if settings:
        for channel in ('email','telegram','bitrix'):
            if settings[channel+'_enabled']:
                # External text is intentionally generic; never copies PII/document/task text.
                payload={'text':'Новое уведомление в Фокусе. Откройте рабочее место ассистента.','path':'/meetings'}
                c.execute('INSERT INTO notification_outbox(notification_id,channel,payload,created_at) VALUES (?,?,?,?)',
                          (nid,channel,json.dumps(payload,ensure_ascii=False),stamp))
    return nid


def assigned(c,task_id):
    row=c.execute('SELECT assignee_user_id,version FROM tasks WHERE id=?',(task_id,)).fetchone()
    if row and row[0]:emit(c,row[0],'task_assigned','task',task_id,'Вам назначено поручение.',f'assigned:{task_id}:{row[0]}:{row[1]}')


def tick(c,now=None):
    from meetings.management.service import MINSK
    now=now or store.parse_aware(store.now());day=now.astimezone(MINSK).date()
    before=c.execute('SELECT count(*) FROM notifications').fetchone()[0]
    for task in c.execute("SELECT * FROM tasks WHERE status NOT IN ('done','cancelled') AND assignee_user_id IS NOT NULL"):
        try:due=date.fromisoformat(task['due'])
        except (ValueError,TypeError):continue
        uid=task['assignee_user_id'];late=(day-due).days
        if late==-1:emit(c,uid,'due_tomorrow','task',task['id'],'Срок поручения завтра.',f"due:{task['id']}:{day}")
        if late>1:emit(c,uid,'overdue','task',task['id'],'Поручение просрочено более чем на день.',f"overdue:{task['id']}:{day}")
        if late>3:
            manager=c.execute('SELECT manager_id FROM users WHERE id=? AND active=1',(uid,)).fetchone()
            if manager and manager[0]:emit(c,manager[0],'escalation','task',task['id'],'Поручение подчинённого просрочено более трёх дней.',f"escalation:{task['id']}:{day}")
    for event in c.execute("SELECT * FROM calendar_events WHERE status='confirmed'"):
        try:start=store.parse_aware(event['start_at'])
        except store.TimeError:continue
        if now <=start <=now+timedelta(minutes=15):
            people={event['organizer_id'],*[r[0] for r in c.execute('SELECT user_id FROM calendar_event_participants WHERE event_id=?',(event['id'],))]}
            for uid in people:
                if event['meeting_id']:emit(c,uid,'meeting_soon','meeting',event['meeting_id'],'Встреча начнётся в течение 15 минут.',f"meeting:{event['id']}:{uid}:{event['start_at']}")
    if now.astimezone(MINSK).hour>=9:
        for user in c.execute('SELECT id FROM users WHERE active=1'):
            emit(c,user[0],'daily_briefing','briefing',day,'Доступен брифинг дня.',f'briefing:{user[0]}:{day}')
    return c.execute('SELECT count(*) FROM notifications').fetchone()[0]-before
