"""Conservative rules for possible conflicts and promises, always with quotes.

No model, no autonomous task or status changes. Missing/different context is a
reason to ask a human; matching a key never proves a source is true.
"""
from datetime import date
import re
from fastapi import APIRouter,Request,Query
from meetings import access,store
from meetings.auth import MeetRoute,current_user,require
from meetings.document_versions import cited,freshness
from meetings.knowledge.index import visible_fragments
from meetings.knowledge.language import sentences
from meetings.privacy import source_is_injection

MONTHS=['январ','феврал','март','апрел','ма','июн','июл','август','сентябр','октябр','ноябр','декабр']
PROMISE=re.compile(r'\b(?:обеща(?:ет|ю|ем)|обязу(?:ется|юсь|емся)|подтвержда(?:ет|ю|ем)\s+поставк)',re.I)
NEGATIVE=re.compile(r'\b(?:не\s+(?:обещ|обяз|подтверж)|если|возможно|может|отмен|отказ)',re.I)


def dates(text):
    result=set()
    for value in re.findall(r'\b\d{4}-\d{2}-\d{2}\b',text):
        try:result.add(date.fromisoformat(value).isoformat())
        except ValueError:pass
    for month,stem in enumerate(MONTHS,1):
        for match in re.finditer(r'\b(\d{1,2})\s+'+stem+r'\w*\s+(\d{4})\b',text,re.I):
            try:result.add(date(int(match[2]),month,int(match[1])).isoformat())
            except ValueError:pass
    return sorted(result)


def entity(text):
    lowered=text.casefold().replace('ё','е')
    order=re.search(r'pp-\d{4}-\d{5}',lowered)
    if order:return order[0].upper()
    carton=re.search(r'картон\w*\s*(\d+[,.]\d+)\s*мм',lowered)
    if carton:return 'картон '+carton[1].replace('.',',')+' мм'
    if re.search(r'ламинат',lowered):return 'ламинат'
    if 'kolbus' in lowered:return 'Kolbus'
    return None


def facts(text):
    ident=entity(text)
    if not ident or NEGATIVE.search(text):return []
    result=[]
    if re.search(r'постав|достав',text,re.I):
        for value in dates(text):result.append((ident,'дата поставки',value))
    for value in re.findall(r'\b(?:цен\w*|стоимость)\s*[:—-]?\s*(\d+(?:[,.]\d+)?)\s*BYN\b',text,re.I):
        result.append((ident,'цена BYN',value.replace(',','.')))
    return result


def linked_tasks(c,user,kind,key):
    return [{'id':r['id'],'status':r['status'],'due':r['due']} for r in c.execute(
        "SELECT t.* FROM action_basis b JOIN tasks t ON b.object_type='task' AND t.id=b.object_id WHERE b.source_kind=? AND b.source_id=? ORDER BY t.id",(kind,key))
        if store.can_read_meeting(c,user['id'],r['meeting_id'],model=True)]


def build(c,user,meeting_id=None):
    require(user,'qa.ask',action='documents.insights')
    if meeting_id is not None:
        from meetings.api import _meeting
        _meeting(c,user,meeting_id)
    rows=visible_fragments(c,user['id'],meeting_id=meeting_id,model=True)
    partial=len(rows)>500;rows=rows[:500];groups={};commitments=[];warnings=[]
    for f in rows:
        if source_is_injection(f['text']):continue
        d=c.execute('SELECT * FROM documents WHERE id=?',(f['document_id'],)).fetchone()
        state=freshness(c,user['id'],d['id'])
        if state['stale']:warnings.append('Часть источников устарела; откройте актуальную редакцию.')
        source=cited(d,f)
        for statement in sentences(f['text']):
            for ident,attr,value in facts(statement):
                key=(ident,attr);groups.setdefault(key,[]).append({'value':value,'source':source,'document_id':d['id']})
            if PROMISE.search(statement) and not NEGATIVE.search(statement):
                when=dates(statement);who=statement[:PROMISE.search(statement).start()].strip(' .:;') or 'Требует уточнения'
                commitments.append({'who':who[:120],'what':statement,'due':when[0] if len(when)==1 else None,
                    'status':'linked_task' if linked_tasks(c,user,'document',source['id']) else 'requires_review',
                    'tasks':linked_tasks(c,user,'document',source['id']),'sources':[source],
                    'proposed_action':{'kind':'task','text':'Проверить исполнение обязательства: '+statement[:700],
                                       'due':when[0] if len(when)==1 else None,'basis':{'kind':'document','id':source['id']}}})
    conflicts=[]
    for (ident,attr),items in groups.items():
        for i,a in enumerate(items):
            b=next((b for b in items[i+1:] if b['document_id']!=a['document_id'] and b['value']!=a['value']),None)
            if b:
                conflicts.append({'entity':ident,'attribute':attr,'values':[a['value'],b['value']],
                    'text':f'Возможное противоречие: {ident}, {attr}: {a["value"]} / {b["value"]}.',
                    'sources':[a['source'],b['source']]});break
    scope,args=access.predicate(c,user['id'],'meeting','m',model=True)
    if meeting_id is not None:scope+=' AND m.id=?';args.append(meeting_id)
    utterances=c.execute('SELECT u.*,m.scheduled_at,m.created_at AS meeting_created,m.title FROM utterances u JOIN meetings m ON m.id=u.meeting_id '
        'WHERE u.deleted=0 AND '+scope+' ORDER BY u.id LIMIT 501',args).fetchall();partial|=len(utterances)>500
    for u in utterances[:500]:
        if source_is_injection(u['text']) or not PROMISE.search(u['text']) or NEGATIVE.search(u['text']):continue
        when=dates(u['text']);key='U'+str(u['id']);tasks=linked_tasks(c,user,'utterance',key)
        commitments.append({'who':u['speaker_label'] or 'Требует уточнения','what':u['text'],'due':when[0] if len(when)==1 else None,
            'status':'linked_task' if tasks else 'requires_review','tasks':tasks,
            'sources':[{'kind':'utterance','id':key,'title':u['title'],'quote':u['text'],'source_at':u['scheduled_at'] or u['meeting_created']}],
            'proposed_action':{'kind':'task','text':'Проверить исполнение обязательства: '+u['text'][:700],
                'meeting_id':u['meeting_id'],'due':when[0] if len(when)==1 else None,'basis':{'kind':'utterance','id':key}}})
    return {'conflicts':conflicts[:30],'commitments':commitments[:50],
            'partial':bool(partial or len(conflicts)>30 or len(commitments)>50),'warnings':list(dict.fromkeys(warnings)),
            'generated_at':store.now(),'notice':'Возможные противоречия и обязательства найдены правилами. Проверьте контекст и исполнение; задачи создаются только после вашего подтверждения.'}


def router():
    api=APIRouter(route_class=MeetRoute)
    @api.get('/api/meet/document-insights')
    def insights(request:Request,meeting_id:int|None=Query(default=None,gt=0,le=2**63-1)):
        user=current_user(request)
        with store.db() as c:
            result=build(c,user,meeting_id)
            store.audit(c,user['id'],'documents_insights',object_type='document',source_ids=[s['id'] for item in [*result['conflicts'],*result['commitments']] for s in item['sources']])
            return result
    return api
