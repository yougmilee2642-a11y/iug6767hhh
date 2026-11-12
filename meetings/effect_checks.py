"""Human-approved delayed metric checks. No inference of causality or task changes."""
import json
from datetime import datetime,timedelta,timezone
from meetings import access,store,notifications
from meetings.auth import MeetError,require
from meetings.decisions import basis
from meetings.management import service
from meetings.connectors.mock import digest

KEYS={key:(label,top,bottom) for key,label,top,bottom in service.RATIOS}


def measure(c,user,department,key,now):
    warnings=[];rows=service.metric_rows(c,user['id'],now,warnings,department_id=department)
    if key not in KEYS or not rows:return {'value':None,'as_of':None,'warnings':['Доступного снимка метрики нет.'],'snapshots':[]}
    label,top,bottom=KEYS[key];value,n,d=service.ratio(rows,top,bottom,label,warnings)
    stamp=min((store.parse_aware(r['as_of']) for r in rows))
    return {'value':value,'as_of':store.iso_utc(stamp),'warnings':warnings,'snapshots':rows,'numerator':n,'denominator':d}


def plan(c,user,data,observed):
    require(user,'overview.read',action='effect.preview')
    item,quote,proof=basis(c,user,data['protocol_item_id'],write=True)
    if not item['confirmed_at'] or not quote or not store.can_read_meeting(c,user['id'],item['meeting_id'],model=True):
        raise MeetError(422,'confirmed_decision_required','Нужно подтверждённое решение с доступной проверенной цитатой.')
    measurement=measure(c,user,item['department_id'],data['metric_key'],datetime.now(timezone.utc))
    if measurement['value'] is None:raise MeetError(422,'metric_no_data','Нет доступной метрики с ненулевым знаменателем для исходного значения.')
    return {'input':data,'decision_proof':proof,'meeting_id':item['meeting_id'],'department_id':item['department_id'],
        'baseline':measurement,'check_at':store.iso_utc(store.parse_aware(observed)+timedelta(days=data['days'])),
        'observed':observed,'actor':digest([user['id'],user.get('level'),user.get('department_id'),user.get('_delegated_departments',[])])}


def visible(c,user):
    require(user,'overview.read',action='effect.read');result=[]
    for row in c.execute('SELECT e.*,i.meeting_id FROM task_effect_checks e JOIN protocol_items i ON i.id=e.protocol_item_id WHERE e.owner_id=? ORDER BY e.id DESC',(user['id'],)):
        if not store.can_read_meeting(c,user['id'],row['meeting_id'],model=True):continue
        baseline=json.loads(row['baseline_json']);saved=json.loads(row['result_json']) if row['result_json'] else None
        metric_ids=[r['id'] for r in baseline['snapshots']]+((saved or {}).get('metric_ids',[]))
        if any(not access.object_decision(c,user['id'],'metric',mid,'model.read').allowed for mid in metric_ids):continue
        data={k:row[k] for k in ('id','protocol_item_id','meeting_id','metric_key','baseline','target_value','direction','check_at','status','created_at')}
        data['result']=saved;result.append(data)
    return result


def tick(c,now=None):
    now=now or datetime.now(timezone.utc);count=0
    rows=c.execute("SELECT * FROM task_effect_checks WHERE status IN ('scheduled','waiting_data') AND julianday(check_at)<=julianday(?)",(store.iso_utc(now),)).fetchall()
    for row in rows:
        user=access.load_user(c,row['owner_id'])
        try:
            if not user or not user['active']:continue
            require(user,'overview.read',action='effect.check')
            baseline=json.loads(row['baseline_json'])
            if any(not access.object_decision(c,user['id'],'metric',r['id'],'model.read').allowed for r in baseline['snapshots']):continue
            item,quote,_=basis(c,user,row['protocol_item_id'])
            if not quote or not store.can_read_meeting(c,user['id'],item['meeting_id'],model=True):continue
            result=measure(c,user,row['department_id'],row['metric_key'],now)
        except MeetError:continue
        fresh=result['as_of'] and store.parse_aware(result['as_of'])>store.parse_aware(row['created_at']) and now-store.parse_aware(result['as_of'])<=timedelta(hours=48)
        if result['value'] is None or not fresh:
            if row['status']!='waiting_data':
                c.execute("UPDATE task_effect_checks SET status='waiting_data',result_json=?,version=version+1 WHERE id=?",(json.dumps({'notice':'Нужен свежий снимок после настройки контроля. Результат не оценён.'},ensure_ascii=False),row['id']))
            continue
        value=result['value'];reached=value<=row['target_value'] if row['direction']=='le' else value>=row['target_value']
        summary={'before':row['baseline'],'after':value,'target':row['target_value'],'as_of':result['as_of'],'reached':reached,
                 'metric_ids':[r['id'] for r in result['snapshots']],
                 'warnings':result['warnings'],'notice':'Сравнение после решения. Причинная связь с решением не доказана.'}
        c.execute("UPDATE task_effect_checks SET status='evaluated',result_json=?,version=version+1 WHERE id=?",(json.dumps(summary,ensure_ascii=False),row['id']))
        store.audit(c,user['id'],'effect_evaluated',object_type='meeting',object_id=item['meeting_id'],effect_check_id=row['id'],reached=reached)
        notifications.emit(c,user['id'],'decision_effect','meeting',item['meeting_id'],'Готова проверка метрики решения. Откройте встречу.',f'effect:{row["id"]}')
        count+=1
    return count
