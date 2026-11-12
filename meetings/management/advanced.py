"""Scoped, deterministic extra reports; signed sources rehydrate under current ACL."""
from datetime import datetime,timedelta,timezone
from decimal import Decimal
import math,re
from meetings import access,store
from meetings.auth import MeetError,has_capability,require
from meetings.management import service,domain
from meetings.knowledge.common import aware,iso,not_found


def mean_ratio(rows):
    if not rows or any(r['available_hours']<=0 for r in rows):return None
    try:
        value=sum((Decimal(str(r['occupied_hours']))/Decimal(str(r['available_hours']))*100 for r in rows),Decimal(0))/len(rows)
        value=float(value)
        return value if math.isfinite(value) else None
    except (ValueError,ArithmeticError,OverflowError):return None


def samples(c,user,cutoff,warnings):
    scope,args=access.snapshot_predicate(c,user['id'],'s')
    result=[]
    for r in c.execute('SELECT s.* FROM seasonality_samples s WHERE '+scope+' AND julianday(as_of)<=julianday(?) ORDER BY source_id',[*args,iso(cutoff)]):
        row=dict(r)
        try:
            if aware(row['period_start'])>=aware(row['period_end']):raise ValueError()
            if any(not math.isfinite(row[k]) or row[k]<0 for k in ('occupied_hours','available_hours')):raise ValueError()
        except (ValueError,TypeError):warnings.append('Некорректная строка сезонной истории исключена.');continue
        result.append(row)
    return result


def build(c,user,cutoff,observed):
    user=access.load_user(c,user['id'])
    if not user or not user['active']:raise MeetError(401,'not_authenticated','Войдите снова.')
    require(user,'overview.read',action='advanced.read')
    warnings=[];manifests={};metrics=[]
    def emit(key,label,value,unit,formula,rows,data):
        stamp=min((aware(r['as_of']) for r in rows),default=observed)
        source=service.aggregate_source(key,cutoff,observed,[*rows,{'projection':data}],iso(stamp),label);source['kind']='insight'
        metric={'key':key,'label':label,'value':value,'unit':unit,'formula':formula,'as_of':iso(stamp) if rows else None,'source':source}
        manifests[source['id']]={'metric':metric,'data':data,'snapshots':rows,'evaluated_at':iso(observed)};metrics.append(metric)
        if rows and observed-stamp>timedelta(hours=48):warnings.append(label+': источники старше 48 часов.')
        return source
    plan=domain.selected(c,user['id'],'production_plan',cutoff,warnings);history=samples(c,user,cutoff,warnings)
    forecast=[]
    groups=sorted({(r['department_id'],r['section']) for r in plan if not r['forecast']},key=lambda p:(str(p[0]),p[1]))
    for department,section in groups:
        actual=[r for r in plan if not r['forecast'] and r['department_id']==department and r['section']==section and aware(r['period_end'])<=cutoff]
        by_period={}
        for row in sorted(actual,key=lambda r:(aware(r['as_of']),r['source_id'])):by_period[row['period_start']]=row
        recent=sorted(by_period.values(),key=lambda r:aware(r['period_end']))[-3:]
        hist=[r for r in history if r['department_id']==department and r['section']==section and aware(r['period_end'])<=cutoff]
        dec=[r for r in hist if aware(r['period_start']).month==12];base=[r for r in hist if aware(r['period_start']).month!=12]
        moving=mean_ratio(recent) if len(recent)==3 else None;winter=mean_ratio(dec);normal=mean_ratio(base)
        coefficient=winter/normal if winter is not None and normal and normal>0 else None
        if moving is None or coefficient is None:
            warnings.append(section+': для сезонного прогноза нужны 3 последние недели и история декабря/обычных месяцев с ненулевой мощностью.');continue
        if not math.isfinite(coefficient):warnings.append(section+': коэффициент вне числового диапазона.');continue
        first=cutoff.astimezone(service.MINSK).date();first+=timedelta(days=7-first.weekday())
        points=[]
        for i in range(6):
            day=first+timedelta(weeks=i);season=coefficient if (day+timedelta(days=3)).month==12 else 1
            value=moving*season
            if not math.isfinite(value):warnings.append(section+': прогноз вне числового диапазона.');continue
            points.append({'start':day.isoformat(),'end':(day+timedelta(days=6)).isoformat(),'value':round(value,2),'deficit_percent':round(max(value-100,0),2)})
        owner=c.execute('SELECT head_user_id FROM departments WHERE id=?',(department,)).fetchone()
        data={'department_id':department,'section':section,'moving_average':round(moving,4),'december_coefficient':round(coefficient,6),
            'owner_user_id':owner[0] if owner else None,'points':points,'method':'Синтетическая история в демо; это сценарный расчёт, не обученная прогнозная модель.'}
        key='seasonal_'+str(department or 0)+'_'+str(len(forecast))
        source=emit(key,section+' · сезонный прогноз',max((p['value'] for p in points),default=None),'%',
            'mean(last 3 weekly occupied/available ×100) × (mean(December history utilization)/mean(non-December history utilization)); coefficient only for December weeks',recent+hist,data)
        forecast.append({**data,'source':source})
    # Logistics is an explicit minimal projection, not a grant to underlying ERP/customer cards.
    scope,args=access.snapshot_predicate(c,user['id'],'s');storage=[]
    for r in c.execute('SELECT s.* FROM pickup_storage s WHERE '+scope+' AND julianday(as_of)<=julianday(?) ORDER BY order_no',[*args,iso(cutoff)]):
        try:
            expiry=aware(r['expires_at'])
            if cutoff<=expiry<=cutoff+timedelta(days=2):storage.append(dict(r))
        except (ValueError,TypeError):warnings.append('У заказа ПВЗ некорректный срок хранения.')
    pickup_source=emit('pickup_soon','Срок хранения в ПВЗ ≤ 2 дней',len(storage),'заказов',
        "count(cutoff <= explicit storage expiry <= cutoff+2days); logistics projection",storage,{'orders':storage})
    pickup=[{'order_no':r['order_no'],'expires_at':r['expires_at'],'carrier_code':r['carrier_code'],'source':pickup_source,
        'proposed_action':{'kind':'task','text':'Напомнить клиенту о получении заказа '+r['order_no']+'. Срок хранения: '+r['expires_at'],
            'due':aware(r['expires_at']).astimezone(service.MINSK).date().isoformat(),'basis':{'kind':'insight','id':pickup_source['id']}}} for r in storage[:100]]
    orders=domain.selected(c,user['id'],'erp_orders',cutoff,warnings)
    interactions=domain.selected(c,user['id'],'support_interactions',cutoff,warnings,own='agent_user_id')
    defects=[r for r in orders if r['defective'] and 'premium' in r['product_code'].lower()]
    complaints=[r for r in interactions if r['topic_code']=='topic-00' and 'premium' in r['body'].lower()]
    from meetings.decisions import visible
    quality_text=lambda text: bool(re.search('premium|перепл',text,re.I) and re.search('брак|дефект|качеств|отк',text,re.I))
    decisions=[r for r in visible(c,user['id'],model=True) if r['status']=='open' and quality_text(r['text'])]
    tasks=[r for r in service.visible_tasks(c,user['id']) if quality_text(r['text']) and service.overdue(r,cutoff.astimezone(service.MINSK).date())]
    call_rows=[]
    if has_capability(user,'calls.read'):
        from meetings import calls
        for r in c.execute('SELECT * FROM calls ORDER BY id'):
            if not calls.call_scope(c,user,r) or not store.can_read_meeting(c,user['id'],r['meeting_id'],model=True):continue
            if aware(r['started_at'])>cutoff:continue
            utterances=store.utterances(c,r['meeting_id']);text=' '.join(u['text'] for u in utterances)
            if re.search('premium|перепл',text,re.I) and re.search('брак|дефект',text,re.I):
                call_rows.append({**dict(r),'utterances':utterances,'source_id':'call:'+str(r['id']),'as_of':r['started_at']})
    proof=[*defects,*complaints,*call_rows,*[dict(r,source_id='decision:'+str(r['id']),as_of=r['updated_at']) for r in decisions],
           *[dict(r,source_id='task:'+str(r['id']),as_of=r['updated_at']) for r in tasks]]
    quality={'defective_premium_orders':len(defects),'support_defect_cases':len(complaints),
             'defect_calls':len(call_rows) if has_capability(user,'calls.read') else None,'controlled_decisions':len(decisions),'overdue_tasks':len(tasks)}
    quality_source=emit('quality_radar','Радар качества Premium',None,'',
        'separate counts of explicit Premium/переплёт quality evidence in current authorized snapshots; not causal inference',proof,
        {'counts':quality,'orders':[r['order_no'] for r in defects],'interaction_ids':[r['id'] for r in complaints],
         'call_ids':[r['id'] for r in call_rows],'decision_ids':[r['id'] for r in decisions],'task_ids':[r['id'] for r in tasks]})
    return {'seasonal_forecast':forecast,'pickup_orders':pickup,'quality':{'counts':quality,'source':quality_source},'metrics':metrics,
        'warnings':list(dict.fromkeys(warnings)),'partial':len(storage)>100,'generated_at':iso(observed),'cutoff':iso(cutoff),
        'notice':'Только доступные данные; отсутствие доступа не означает нулевое число по компании. Корреляция сигналов не доказывает причину или эффект.'},manifests


def resolve(c,user,key):
    match=re.fullmatch(r'A~([a-z_0-9]+)~(\d{1,18})~(\d{1,18})~([0-9a-f]{64})',str(key))
    if not match:raise not_found()
    try:cutoff=service.EPOCH+timedelta(microseconds=int(match[2]));observed=service.EPOCH+timedelta(microseconds=int(match[3]))
    except (ValueError,OverflowError):raise not_found() from None
    _,manifests=build(c,user,cutoff,observed)
    data=manifests.get(key)
    if data is None:raise not_found()
    return {'source':data['metric']['source'],'data':data}
