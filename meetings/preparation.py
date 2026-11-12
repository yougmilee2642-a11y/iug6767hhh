"""Deterministic department context alongside model-generated document preparation."""
from datetime import datetime, timezone, timedelta
import json
import re

from meetings import access, store, textutil


def task_source(connection, task):
    source_at = store.stored_utc(task.get('updated_at') or task.get('confirmed_at') or task['created_at'])
    return {'kind':'task','id':f"T{task['id']}", 'title':task['text'],'source_at':source_at,
            'quote':(task.get('source_quote') or {}).get('text'), 'locator':(task.get('source_quote') or {}).get('utterance_id')}


def owner_suggestion(connection, task):
    if task.get('assignee'): return None
    text = task['text'].casefold().replace('ё','е')
    login, reason = None, None
    for pattern, candidate, explanation in [
        (r'достав|пвз|европочт|белпочт','log_head','Тема доставки'),
        (r'макет|модерац','mod_lead','Тема модерации'),
        (r'брак|перепечат|отк|картон|переплет|производ','prod_head','Тема производства')]:
        if re.search(pattern,text): login,reason = candidate,explanation; break
    person = connection.execute("SELECT id,name FROM users WHERE login=? AND active=1 AND level IN ('director','head','lead','employee')", (login,)).fetchone() if login else None
    return {'user_id':person['id'],'name':person['name'],'status':'assumption','reason':reason} if person else None


def department_context(connection, user, meeting, previous_tasks):
    department = meeting['department_id']
    if not user.get('level') or department is None:
        return {}, previous_tasks
    predicate, args = access.predicate(connection,user['id'],'meeting','m',model=True)
    rows = connection.execute('SELECT t.*,m.department_id AS meeting_department FROM tasks t JOIN meetings m ON m.id=t.meeting_id '
                              "WHERE t.status NOT IN ('done','cancelled') AND " + predicate + ' ORDER BY COALESCE(t.due,\'9999\'),t.id', args)
    tasks, seen = list(previous_tasks), {t['id'] for t in previous_tasks}
    order_ids = set(re.findall(r'PP-\d{4}-\d{5}', meeting['title'] + ' ' + meeting['topic']))
    for row in rows:
        links = json.loads(row['linked_entities'])
        if row['meeting_department'] != department and not any(link.get('kind')=='order' and link.get('id') in order_ids for link in links):
            continue
        if row['id'] in seen: continue
        task = store.task_out(connection,row); task['source'] = task_source(connection,task)
        tasks.append(task); seen.add(task['id'])
    for task in tasks:
        suggestion = owner_suggestion(connection,task)
        if suggestion: task['assignee_suggestion'] = suggestion
    questions, hidden = [], 0
    query = ('SELECT i.*,m.scheduled_at,m.created_at AS meeting_created,p.generated_at FROM protocol_items i JOIN meetings m ON m.id=i.meeting_id '
             'LEFT JOIN protocols p ON p.meeting_id=m.id WHERE i.kind=\'open_question\' AND m.department_id=? '
             'AND m.id!=? AND ' + predicate + ' ORDER BY m.scheduled_at DESC,i.id DESC LIMIT 30')
    for row in connection.execute(query, [department,meeting['id'],*args]):
        source = None
        for quote in json.loads(row['quotes']):
            raw_id = str(quote.get('utterance_id',''))
            if not re.fullmatch(r'U\d+',raw_id): continue
            original = connection.execute('SELECT * FROM utterances WHERE id=? AND meeting_id=? AND deleted=0',
                                          (int(raw_id[1:]),row['meeting_id'])).fetchone()
            if original and textutil.find_exact(quote.get('text',''),original['text']):
                source = {'kind':'utterance','id':raw_id,'title':'Открытый вопрос предыдущей встречи',
                          'source_at':store.stored_utc(row['scheduled_at']) or row['generated_at'] or row['meeting_created'],
                          'quote':original['text'],'locator':f"meeting:{row['meeting_id']}"}
                break
        if source: questions.append({'text':row['text'],'meeting_id':row['meeting_id'],'protocol_item_id':row['id'],'sources':[source]})
        else: hidden += 1
    from meetings.management.service import metric_rows, ratio, RATIOS
    now = datetime.now(timezone.utc); warnings = []
    snapshots = metric_rows(connection,user['id'],now,warnings,department_id=department)
    metrics = []
    for key,label,numerator,denominator in RATIOS if snapshots else []:
        value,top,bottom = ratio(snapshots,numerator,denominator,label,warnings)
        metrics.append({'key':key,'label':label,'value':value,'unit':'%', 'numerator':top,'denominator':bottom,
                        'formula':f'sum({numerator}) / sum({denominator}) × 100',
                        'sources':[{'kind':'metric','id':r['source_id'],'title':label+' · снимок отдела',
                                    'source_at':r['as_of'],'locator':f"[{r['period_start']}, {r['period_end']})"} for r in snapshots]})
    as_of = min(snapshots,key=lambda r:store.parse_aware(r['as_of']))['as_of'] if snapshots else None
    if as_of and now-store.parse_aware(as_of)>timedelta(hours=48): warnings.append('Снимок отдела старше 48 часов.')
    return {'previous_questions':questions,'kpi_context':{'department_id':department,'as_of':as_of,'metrics':metrics,'warnings':warnings},
            'unquoted_previous_questions':hidden},tasks
