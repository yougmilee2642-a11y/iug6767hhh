"""Scoped synthetic call records and cited rule-based conversation intelligence."""
from collections import Counter
from datetime import datetime,timedelta,timezone
import json
import re
import os
from fastapi import APIRouter,Request
from pydantic import BaseModel,ConfigDict,Field
from meetings import access,confirmations,store
from meetings.api import ConfirmTokenIn,denied
from meetings.auth import MeetError,MeetRoute,current_user,require
from meetings.connectors.mock import MockCRM,digest
from meetings.media import analytics

# Mirrors the 17 seeded Mary topic codes. Rule hits describe explicit words,
# not a hidden judgement about the customer's emotion or future behaviour.
TOPICS=[('брак',r'брак|дефект|переплет|перепечат'),('вопросы по ЛК',r'как.*кабинет|где.*кабинет'),
 ('по доставке',r'достав|европочт|белпочт|курьер|пвз'),('по загрузке файлов',r'загруз|файл'),
 ('по оплате',r'оплат|ерип|ассист|платеж'),('по оформлению заказов',r'оформ|как.*заказ'),
 ('по продукции',r'продукц|формат|фотокниг'),('по скидкам',r'скидк|промокод'),('по срокам',r'срок|когда.*готов'),
 ('вёрстка',r'верстк|макет'),('другое',r'(?!)'),('спасибо',r'спасибо|благодар'),('отзыв',r'отзыв'),
 ('ошибка клиента',r'ошиб.*клиент|не тот.*файл'),('проблемы с ЛК',r'не.*войти|ошиб.*кабинет|кабинет.*не работа'),
 ('просьба/жалоба/предложение',r'жалоб|предложени|верните деньги'),('уточнение прайса',r'прайс|сколько стоит|цен[аыу]')]
CHECKLIST=[('greeting','Приветствие',r'здравствуйте|добрый (день|вечер|утро)'),
 ('introduced','Представился',r'меня зовут|это [а-я]{3,}.*поддерж|оператор [а-я]{3,}'),
 ('order','Уточнил номер заказа',r'(назовите|уточни|подскажите).*номер|номер.*заказ|PP-\d{4}-\d{5}'),
 ('solution','Предложил решение',r'предлага|перепечата|оформим|заменим|проверим'),
 ('deadline','Озвучил срок',r'завтра|сегодня|до \d|\d+ (дн|рабоч)|три рабочих дня'),
 ('farewell','Попрощался',r'до свидания|всего доброго|хорошего (дня|вечера)')]
TRIGGERS=[('брак','брак'),('возврат','возврат'),('жалоба','жалоб'),('верните деньги','верните деньги'),('отзыв','отзыв'),('европочта','европочт')]


def normalized(text):return text.lower().replace('ё','е')


def call_scope(c,user,row):
    actor=access.load_user(c,user['id'])
    if not actor or not actor['active']:return False
    require(actor,'calls.read',action='calls.read')
    allowed=actor and (actor['level']=='director' or row['agent_user_id']==actor['id'] or
        actor['level'] in ('head','lead') and row['department_id'] in [actor['department_id'],*actor['_delegated_departments']])
    return bool(allowed and store.can_read_meeting(c,user['id'],row['meeting_id']))


def checked(c,user,cid):
    require(user,'calls.read',action='calls.read')
    if not 0<cid<=2**63-1:raise denied(user,'call',str(cid)[:30],'calls.read')
    row=c.execute('SELECT * FROM calls WHERE id=?',(cid,)).fetchone()
    if not row or not call_scope(c,user,row):raise denied(user,'call',cid,'calls.read')
    return row


def projection(c,row):
    return {k:row[k] for k in ('id','direction','channel','department_id','agent_user_id','client_ref','order_no','started_at','duration_ms','meeting_id')}


def analyze(c,user,row):
    if not call_scope(c,user,row):raise denied(user,'call',row['id'],'calls.analyze')
    utterances=store.utterances(c,row['meeting_id'])
    meeting=c.execute('SELECT * FROM meetings WHERE id=?',(row['meeting_id'],)).fetchone()
    timing=analytics.build(c,meeting)
    def quote(u):return {'kind':'utterance','id':u['id'],'title':'Реплика звонка','quote':u['text'],
                         'source_at':row['started_at'],'locator':f"meeting:{row['meeting_id']}"}
    topics=[]
    for i,(label,pattern) in enumerate(TOPICS):
        hits=[u for u in utterances if re.search(pattern,normalized(u['text']),re.I)]
        if hits:topics.append({'code':f'topic-{i:02d}','title':label,'sources':[quote(u) for u in hits]})
    if not topics and utterances:topics=[{'code':'topic-10','title':'другое','sources':[quote(utterances[0])]}]
    agent_name=store.user_name(c,row['agent_user_id']);agent_rows=[u for u in utterances if u['speaker'] in ('Оператор','Агент',agent_name)]
    checklist=[]
    for key,label,pattern in CHECKLIST:
        hits=[u for u in agent_rows if re.search(pattern,normalized(u['text']),re.I)]
        checklist.append({'code':key,'title':label,'passed':bool(hits),'sources':[quote(u) for u in hits]})
    triggers=[]
    for term,pattern in TRIGGERS:
        hits=[u for u in utterances if pattern in normalized(u['text'])]
        if hits:triggers.append({'text':term,'sources':[quote(u) for u in hits]})
    # Explicit dissatisfaction rule, not an inferred clinical/emotional score.
    risky=[u for u in utterances if re.search(r'больше не (буду|закаж)|верните деньги|жалоб|плохой отзыв',normalized(u['text']))]
    agent_ms=sum(s['speech_ms'] or 0 for s in timing['speakers'] if s['speaker'] in ('Оператор','Агент',agent_name))
    speech_ms=sum(s['speech_ms'] or 0 for s in timing['speakers'])
    steps=[]
    for u in utterances:
        text=normalized(u['text'])
        if re.search(r'перепечат|свяж.*европочт|связаться.*европочт|оформ.*возврат',text):
            steps.append({'text':u['text'],'sources':[quote(u)],'action':{'kind':'task','meeting_id':row['meeting_id'],
                          'text':u['text'],'basis':{'kind':'call','id':'C'+str(row['id'])}},'notice':'Предложение из реплики. Проверьте ответственного и срок в preview.'})
    return {'call':projection(c,row),'topics':topics,'checklist':checklist,'checklist_passed':all(i['passed'] for i in checklist),
            'speaker_mapping_complete':bool(agent_rows),'triggers':triggers,
            'risk':{'flag':bool(risky),'sources':[quote(u) for u in risky],
                    'rule':'Явная жалоба, требование возврата денег или отказ от следующих заказов; это сигнал для проверки человеком.'},
            'talk_percent':round(agent_ms/speech_ms*100,1) if speech_ms and agent_rows else None,
            'overlap_ms':timing['overlap_ms'],'long_pauses':timing['long_pauses'],'next_steps':steps[:10],
            'model':None,'source_at':row['started_at'],
            'model_topics_enabled':os.getenv('MEETINGS_CALL_TOPIC_MODEL','0')=='1',
            'notice':'Правила по тексту; пропуск в чек-листе означает «не найдено в репликах оператора». Перекрытие сегментов не доказывает перебивание.'}


def week_problems(c,user,department_id=None):
    require(user,'calls.read',action='calls.problems')
    end=datetime.now(timezone.utc);start=end-timedelta(days=7)
    scope='';args=[start.isoformat(),end.isoformat()]
    if department_id is not None:scope=' AND department_id=?';args.append(department_id)
    # Reuse the same local scope before reading transcript/analysis.
    if user['level']!='director':
        if user['level'] in ('head','lead'):
            deps=[user['department_id'],*user['_delegated_departments']]
            scope+=' AND department_id IN ('+','.join('?' for _ in deps)+')';args+=deps
        else:scope+=' AND agent_user_id=?';args.append(user['id'])
    rows=c.execute('SELECT * FROM calls WHERE julianday(started_at)>=julianday(?) AND julianday(started_at)<julianday(?)'+scope+
                   ' ORDER BY started_at DESC,id DESC LIMIT 501',args).fetchall()
    visible=[r for r in rows if call_scope(c,user,r)];truncated=len(visible)>500;visible=visible[:500]
    topics={}
    for row in visible:
        a=analyze(c,user,row)
        for topic in a['topics']:
            if topic['code'] in ('topic-10','topic-11'):continue
            group=topics.setdefault(topic['code'],{'code':topic['code'],'title':topic['title'],'count':0,'sources':[]})
            group['count']+=1;group['sources'].append({'kind':'call','id':'C'+str(row['id']),
                'title':'Звонок '+str(row['id']),'source_at':row['started_at']})
    problems=[]
    for group in sorted(topics.values(),key=lambda t:(-t['count'],t['code']))[:3]:
        problems.append({**group,'text':f"{group['title']} — {group['count']} звонков за7 дней в доступной выборке."})
    return {'problems':problems,'period_start':start.isoformat(),'period_end':end.isoformat(),
            'sample_count':len(visible),'truncated':truncated,'method':'Ключевые слова по доступным звонкам, до500 записей; одна запись может относиться к нескольким темам.'}


class Segment(BaseModel):
    model_config=ConfigDict(extra='forbid')
    speaker:str=Field(min_length=1,max_length=120)
    text:str=Field(min_length=1,max_length=8000)
    start_ms:int|None=Field(default=None,ge=0,le=14400000)
    end_ms:int|None=Field(default=None,ge=1,le=14400000)


class CallIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    direction:str=Field(pattern='^(in|out)$')
    channel:str=Field(default='phone',pattern='^(phone|telegram_voice|other)$')
    agent_user_id:int=Field(gt=0,le=2**63-1)
    agent_speaker_label:str|None=Field(default=None,min_length=1,max_length=120)
    client_ref:str|None=Field(default=None,max_length=30)
    order_no:str|None=Field(default=None,max_length=30)
    started_at:str=Field(max_length=40)
    duration_ms:int|None=Field(default=None,gt=0,le=14400000)
    consent:bool=False
    segments:list[Segment]=Field(min_length=1,max_length=500)


def draft(c,user,body):
    require(user,'calls.analyze',action='calls.import')
    if not body['consent']:raise MeetError(403,'consent_required','Требуется согласие участников на обработку записи и текста звонка.')
    agent=access.load_user(c,body['agent_user_id'])
    if not agent or not agent['active'] or agent['department_code'] not in ('SUP','SALES') or agent['level'] in ('admin','auditor'):
        raise MeetError(422,'call_agent','Выберите активного сотрудника поддержки или продаж.')
    permitted=user['level']=='director' or agent['id']==user['id'] or user['level'] in ('head','lead') and agent['department_id'] in [user['department_id'],*user['_delegated_departments']]
    if not permitted:raise denied(user,'call_agent',agent['id'],'calls.import')
    try:body={**body,'started_at':store.iso_utc(store.parse_aware(body['started_at']))}
    except store.TimeError as error:raise MeetError(422,error.code,'Время звонка должно содержать часовой пояс.') from None
    if sum(len(s['text']) for s in body['segments'])>100000:raise MeetError(422,'transcript_too_long','Стенограмма слишком длинная.')
    for s in body['segments']:
        if (s['start_ms'] is None)!=(s['end_ms'] is None) or s['start_ms'] is not None and (
                s['end_ms']<=s['start_ms'] or body['duration_ms'] is not None and s['end_ms']>body['duration_ms']):
            raise MeetError(422,'call_timing','Укажите оба таймкода; конец должен быть позже начала и не превышать длительность.')
    crm=MockCRM(c,user['id'],read_faults=False)
    customer=crm.get_customer(body['client_ref']) if body['client_ref'] else None
    order=crm.get_order(body['order_no']) if body['order_no'] else None
    if body['client_ref'] and not customer or body['order_no'] and not order:raise denied(user,'call_entity','linked','calls.import')
    if order and body['client_ref'] and order['client_ref']!=body['client_ref']:
        raise MeetError(422,'call_entity_conflict','Заказ относится к другому клиенту.')
    return {**body,'department_id':agent['department_id'],'agent_name':agent['name'],
            'agent_version':digest([agent['id'],agent['active'],agent['department_id'],agent['manager_id']])}


def router():
    api=APIRouter(route_class=MeetRoute)

    @api.get('/api/meet/calls/problems')
    def problems(request:Request):
        user=current_user(request)
        with store.db() as c:return week_problems(c,user)

    @api.post('/api/meet/calls/preview')
    def preview(payload:CallIn,request:Request):
        user=current_user(request)
        with store.write_tx() as c:
            body=draft(c,user,payload.model_dump())
            token=confirmations.create(c,user,'call.import','user',user['id'],None,{'input':payload.model_dump(),'hash':digest(body)})
            store.audit(c,user['id'],'call_import_preview',object_type='call',stage='preview',confirmation_id=token['confirmation_id'])
            return {**token,'preview':body,'notice':'Создастся источник-звонок с расшифровкой. Задачи и протокол не подтверждаются автоматически.'}

    @api.post('/api/meet/calls/confirm')
    def confirm(payload:ConfirmTokenIn,request:Request):
        user=current_user(request);require(user,'calls.analyze',action='calls.import')
        with store.write_tx() as c:
            p=confirmations.load(c,user,payload.confirmation_id,'call.import','user',user['id'],payload.idempotency_key)
            if p['already']:
                checked(c,user,p['result']['call_id'])
                return {**p['result'],'already_confirmed':True}
            body=draft(c,user,p['payload']['input'])
            if digest(body)!=p['payload']['hash']:raise MeetError(409,'stale','Сотрудник или связанная сущность изменились. Нужен новый предпросмотр.')
            stamp=store.now()
            mid=c.execute("INSERT INTO meetings(owner_id,title,topic,scheduled_at,participants,created_at,department_id,confidentiality) VALUES (?,?,?,?,?,?,?,'confidential')",
                (body['agent_user_id'],'Звонок · '+body['started_at'],'Анализ звонка',body['started_at'],
                 json.dumps([body['agent_name'],'Клиент'],ensure_ascii=False),stamp,body['department_id'])).lastrowid
            viewers=[r[0] for r in c.execute("SELECT id FROM users WHERE active=1 AND (level='director' OR (department_id=? AND level IN ('head','lead')))",(body['department_id'],))]
            for uid in set([user['id'],*viewers]):c.execute('INSERT OR IGNORE INTO meeting_access VALUES (?,?)',(mid,uid))
            cid=c.execute('INSERT INTO calls(direction,channel,department_id,agent_user_id,client_ref,order_no,started_at,duration_ms,consent_at,meeting_id,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                (body['direction'],body['channel'],body['department_id'],body['agent_user_id'],body['client_ref'],body['order_no'],body['started_at'],body['duration_ms'],stamp,mid,user['id'],stamp)).lastrowid
            for i,s in enumerate(body['segments']):
                speaker=body['agent_name'] if s['speaker'] in ('Оператор','Агент',body.get('agent_speaker_label')) else s['speaker']
                c.execute('INSERT INTO utterances(meeting_id,idx,speaker_label,text,original_text,source,start_ms,end_ms) VALUES (?,?,?,?,?,?,?,?)',
                    (mid,i+1,speaker,s['text'],s['text'],'call_import',s['start_ms'],s['end_ms']))
            result={'call_id':cid,'meeting_id':mid,'already_confirmed':False}
            confirmations.finish(c,payload.confirmation_id,payload.idempotency_key,result)
            store.audit(c,user['id'],'call_import_confirmed',object_type='call',object_id=cid,stage='confirm',confirmation_id=payload.confirmation_id)
            return result

    @api.get('/api/meet/calls')
    def listing(request:Request,date_from:str|None=None,date_to:str|None=None):
        user=current_user(request);require(user,'calls.read',action='calls.list')
        try:
            end=store.parse_aware(date_to) if date_to else datetime.now(timezone.utc)
            start=store.parse_aware(date_from) if date_from else end-timedelta(days=7)
            if not timedelta(0)<end-start<=timedelta(days=366):raise ValueError()
        except (store.TimeError,ValueError):raise MeetError(422,'call_period','Период — от1 до366 дней, время с часовым поясом.') from None
        with store.db() as c:
            # SQL restricts candidate rows before analysis; object ACL is rechecked.
            scope='';args=[start.isoformat(),end.isoformat()]
            if user['level']!='director':
                if user['level'] in ('head','lead'):
                    deps=[user['department_id'],*user['_delegated_departments']]
                    scope=' AND department_id IN ('+','.join('?' for _ in deps)+')';args+=deps
                else:scope=' AND agent_user_id=?';args.append(user['id'])
            rows=c.execute('SELECT * FROM calls WHERE julianday(started_at)>=julianday(?) AND julianday(started_at)<julianday(?)'+scope+' ORDER BY started_at DESC,id DESC LIMIT 501',args).fetchall()
            rows=[r for r in rows if call_scope(c,user,r)];truncated=len(rows)>500;rows=rows[:500]
            analyses=[analyze(c,user,r) for r in rows];topics=Counter();agents={}
            for a in analyses:
                for topic in a['topics']:topics[(topic['code'],topic['title'])]+=1
                agent=a['call']['agent_user_id'];stats=agents.setdefault(agent,{'agent_user_id':agent,'calls':0,'risk_calls':0,'checklist_passed':0})
                stats['calls']+=1;stats['risk_calls']+=a['risk']['flag'];stats['checklist_passed']+=a['checklist_passed']
            return {'calls':[projection(c,r) for r in rows],'count':len(rows),'truncated':truncated,
                'top_topics':[{'code':key[0],'title':key[1],'count':n} for key,n in topics.most_common()],
                'risk_calls':sum(a['risk']['flag'] for a in analyses),'checklist_pass_percent':round(sum(a['checklist_passed'] for a in analyses)/len(rows)*100,1) if rows else None,
                'agents':list(agents.values()),'source_at':store.now(),'period_start':store.iso_utc(start),'period_end':store.iso_utc(end)}

    @api.get('/api/meet/calls/{call_id}')
    def detail(call_id:int,request:Request):
        user=current_user(request)
        with store.db() as c:
            row=checked(c,user,call_id)
            return analyze(c,user,row)
    @api.get('/api/meet/calls/{call_id}/topics')
    def topic_model(call_id:int,request:Request):
        from meetings.call_topics import suggest
        return suggest(current_user(request),call_id)
    return api
