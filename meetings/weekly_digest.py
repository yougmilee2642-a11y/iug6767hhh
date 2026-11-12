"""Current scoped weekly digest, reviewed local outbox only."""
from datetime import date,datetime,time,timedelta,timezone
import json
from email.message import EmailMessage
from email.policy import SMTP
from meetings import access,store
from meetings.auth import MeetError,require
from meetings.management import service
from meetings.knowledge.index import current_clause
from meetings.connectors.mock import digest


def build(c,user,end,observed):
    require(user,'overview.read',action='weekly.read')
    try:last=date.fromisoformat(end)
    except (ValueError,TypeError):raise MeetError(422,'weekly_date','Дата окончания недели: ГГГГ-ММ-ДД.') from None
    if not 1970<=last.year<=9998:raise MeetError(422,'weekly_date','Дата вне поддерживаемого диапазона.')
    first=last-timedelta(days=6);a=datetime.combine(first,time.min,service.MINSK);b=datetime.combine(last+timedelta(days=1),time.min,service.MINSK)
    observed=store.parse_aware(observed);cutoff=min(b-timedelta(microseconds=1),observed)
    overview,_=service.build(c,user['id'],cutoff,observed);claims=[]
    for task in service.visible_tasks(c,user['id']):
        try:recent=a<=store.parse_aware(task['updated_at'])<b
        except store.TimeError:recent=False
        due=task['due'] and first.isoformat()<=task['due']<=last.isoformat()
        if not recent and not due:continue
        status={'open':'открыто','in_progress':'в работе','blocked':'заблокировано','done':'готово','cancelled':'отменено'}.get(task['status'],'требует проверки')
        claims.append({'text':task['text']+f'. Текущий статус: {status}; срок: {task["due"] or "не уточнён"}.',
            'sources':[{'kind':'task','id':'T'+str(task['id']),'title':task['text'],'source_at':task['updated_at']}]})
    scope,args=access.predicate(c,user['id'],'meeting','m',model=True)
    for meeting in c.execute('SELECT m.* FROM meetings m WHERE '+scope,args):
        if not meeting['scheduled_at']:continue
        try:inside=a<=store.parse_aware(meeting['scheduled_at'])<b
        except store.TimeError:inside=False
        if inside:claims.append({'text':'Встреча: '+meeting['title']+'. Время: '+meeting['scheduled_at'],
            'sources':[{'kind':'meeting','id':str(meeting['id']),'title':meeting['title'],'source_at':meeting['created_at']}]})
    scope,args=access.predicate(c,user['id'],'document','d',model=True);current,more=current_clause(c,user['id'])
    for doc in c.execute('SELECT d.* FROM documents d WHERE '+scope+' AND '+current,[*args,*more]):
        try:inside=a<=store.parse_aware(doc['created_at'])<b
        except store.TimeError:inside=False
        if not inside:continue
        fragment=c.execute('SELECT id FROM fragments WHERE document_id=? ORDER BY idx LIMIT 1',(doc['id'],)).fetchone()
        if fragment:claims.append({'text':'Новый документ: '+doc['title'], 'sources':[{'kind':'document','id':'F'+str(fragment[0]),'title':doc['title'],'source_at':doc['created_at']}]})
    for metric in overview['metrics']:
        if metric['value'] is not None:claims.append({'text':f'{metric["label"]}: {metric["value"]} {metric["unit"]}. Доступный срез на конец периода.', 'sources':[metric['source']]})
    return {'period_start':first.isoformat(),'period_end':last.isoformat(),'generated_at':store.iso_utc(observed),
        'claims':claims[:100],'partial':len(claims)>100,'warnings':overview['warnings'],
        'actor_context':digest([user['id'],user.get('level'),user.get('department_id'),user.get('_delegated_departments',[])]),
        'notice':'Недельный срез по текущим правам; статусы актуальны сейчас. Это не восстановление исторических состояний. Письмо только вам в локальную очередь.'}


def message(c,user,row):
    original=json.loads(row['payload'])
    current=build(c,user,row['period_end'],original['generated_at'])
    if digest(current)!=row['payload_hash']:raise MeetError(409,'stale','Данные или доступ изменились. Подготовьте дайджест заново.')
    mail=EmailMessage(policy=SMTP);mail['From']='focus@demo.invalid';mail['To']=f'user-{user["id"]}@demo.invalid'
    mail['Subject']='Недельный дайджест Фокус';mail['Message-ID']=f'<weekly-{row["id"]}@focus.invalid>'
    mail.set_content(current['notice']+'\n\n'+'\n'.join(claim['text']+'\nИсточники: '+', '.join(s['id'] for s in claim['sources']) for claim in current['claims']))
    return mail.as_bytes()
