"""Daily, read-only briefing over the same scoped registries as overview.

Dates select a day in Minsk; tasks and permissions are always current, not a
reconstruction of historical state. No model, external provider or new storage.
"""
from datetime import date, datetime, time, timedelta
import json

from fastapi import APIRouter, Request, Response

from meetings import access, store
from meetings.auth import MeetError
from meetings.knowledge.common import ExtensionRoute, iso, run, utc_now
from meetings.management import service, domain

LIMIT = 50


def parse_day(value, generated):
    if value is None:
        return generated.astimezone(service.MINSK).date()
    try:
        selected = date.fromisoformat(value)
        if not 1970 <= selected.year <= 9998 or selected.isoformat() != value:
            raise ValueError()
        return selected
    except (ValueError, TypeError):
        raise MeetError(422, 'invalid_date', 'Дата брифинга должна быть YYYY-MM-DD (Europe/Minsk).') from None


def source(kind, ident, title, at, *, quote=None):
    return {'kind': kind, 'id': str(ident), 'title': title, 'source_at': at, **({'quote':quote} if quote else {})}


def build(c, actor, day, generated):
    user = access.load_user(c, actor)
    cutoff = min(datetime.combine(day + timedelta(days=1), time.min, service.MINSK) - timedelta(microseconds=1), generated)
    overview, _ = service.build(c, actor, cutoff, generated)
    warnings = list(overview['warnings'])
    if day != generated.astimezone(service.MINSK).date():
        warnings.append('Дата выбирает расписание и сроки; статусы задач, документы и права взяты из текущего реестра.')
    meetings = []
    visible, params = access.predicate(c, actor, 'meeting', 'm', model=True)
    for row in c.execute('SELECT m.* FROM meetings m WHERE ' + visible + ' ORDER BY m.id', params):
        events = c.execute("SELECT e.* FROM calendar_events e WHERE e.meeting_id=? AND e.status='confirmed' AND "
            '(e.organizer_id=? OR EXISTS (SELECT 1 FROM calendar_event_participants p WHERE p.event_id=e.id AND p.user_id=?)) '
            'ORDER BY e.start_at,e.id', (row['id'],actor,actor)).fetchall()
        try:
            participants = json.loads(row['participants'])
        except (ValueError, TypeError):
            participants = []
        if not isinstance(participants,list): participants = []
        personal = row['owner_id'] == actor or user['name'] in participants or user['login'] in participants
        times = [e['start_at'] for e in events] or ([row['scheduled_at']] if personal and row['scheduled_at'] else [])
        for stamp in dict.fromkeys(times):
            try:
                if store.parse_aware(stamp).astimezone(service.MINSK).date() != day:
                    continue
            except store.TimeError:
                warnings.append('В доступном расписании есть встреча с некорректной датой.'); continue
            doc_ids = [r[0] for r in c.execute('SELECT document_id FROM meeting_documents WHERE meeting_id=?', (row['id'],))
                       if store.can_read_document(c, actor, r[0], model=True)]
            meetings.append({'id':row['id'], 'title':row['title'], 'scheduled_at':stamp,
                             'has_materials':bool(doc_ids), 'readiness':'materials_present' if doc_ids else 'materials_missing',
                             'source':source('meeting',row['id'],row['title'],row['created_at'])})
    meetings.sort(key=lambda m:(store.parse_aware(m['scheduled_at']),m['id']))

    def task_entry(row):
        return {'id':row['id'], 'meeting_id':row['meeting_id'], 'text':row['text'], 'due':row['due'],
                'assignee_user_id':row['assignee_user_id'], 'status':row['status'],
                'overdue':service.overdue(row,day),
                'source':source('task','T'+str(row['id']),row['text'],row['updated_at'],quote=row['text'])}
    tasks = [t for t in service.visible_tasks(c, actor) if t['status'] not in ('done','cancelled')]
    mine = [task_entry(t) for t in tasks if t['assignee_user_id']==actor and
            (service.overdue(t,day) or t['due']==day.isoformat())]
    subordinate_ids = set()
    if user['level'] in ('director','head','lead'):
        subordinate_ids = {r[0] for r in c.execute('WITH RECURSIVE team(id) AS (SELECT id FROM users WHERE manager_id=? AND active=1 '
              'UNION SELECT u.id FROM users u JOIN team t ON u.manager_id=t.id WHERE u.active=1) SELECT id FROM team', (actor,))}
        subordinate_ids.discard(actor)
    risky = []
    for t in tasks:
        if t['assignee_user_id'] not in subordinate_ids:
            continue
        try:
            soon = bool(t['due']) and date.fromisoformat(t['due']) <= day + timedelta(days=1)
        except (ValueError, TypeError):
            soon = False
        if soon or t['priority'] in ('high','urgent') or not t['due']:
            risky.append(task_entry(t))
    for rows in (mine,risky):
        rows.sort(key=lambda t:(not t['overdue'],t['due'] or '9999-12-31',t['id']))
    deviations = [m for m in overview['metrics'] if domain.status(m['key'],m['value']) in ('critical','warning')]
    deviations.sort(key=lambda m:(domain.status(m['key'],m['value'])!='critical',m['key']))
    deviations = deviations[:3]
    visible, params = access.predicate(c, actor, 'document', 'd', model=True)
    from meetings.knowledge.index import current_clause
    current, args = current_clause(c, actor)
    documents = []
    since = cutoff - timedelta(days=7)
    for row in c.execute('SELECT d.* FROM documents d WHERE ' + visible + ' AND ' + current, [*params,*args]):
        try:
            if not since <= store.parse_aware(row['created_at']) <= cutoff:
                continue
        except store.TimeError:
            continue
        first = c.execute('SELECT id FROM fragments WHERE document_id=? ORDER BY idx LIMIT 1',(row['id'],)).fetchone()
        if not first: continue
        documents.append({'id':row['id'],'title':row['title'],'created_at':row['created_at'],'version':row['version'],
                          'source':source('document','F'+str(first['id']),row['title'],row['created_at'])})
    documents.sort(key=lambda d:(store.parse_aware(d['created_at']),d['id']),reverse=True)
    groups = {'meetings':meetings,'my_tasks':mine,'team_risks':risky,'new_documents':documents}
    truncated = [key for key,rows in groups.items() if len(rows)>LIMIT]
    if truncated: warnings.append('Длинные списки ограничены первыми 50 строками; откройте полный реестр для остальных.')
    groups = {key:rows[:LIMIT] for key,rows in groups.items()}
    claims = []
    for m in groups['meetings']:
        claims.append({'text':f"Встреча «{m['title']}»: {m['scheduled_at']}; " + ('материалы доступны.' if m['has_materials'] else 'доступные материалы не найдены.'), 'sources':[m['source']]})
    for key in ('my_tasks','team_risks'):
        for t in groups[key]:
            claims.append({'text':('Моя задача: ' if key=='my_tasks' else 'Задача подчинённого с риском: ') + t['text'] + f". Срок: {t['due'] or 'не уточнён'}.", 'sources':[t['source']]})
    for metric in deviations:
        claims.append({'text':f"{metric['label']}: {metric['value']} {metric['unit']}.", 'sources':[metric['source']]})
    for d in groups['new_documents']:
        claims.append({'text':f"Новый документ: «{d['title']}», версия {d['version']}.", 'sources':[d['source']]})
    counts = {key:len(rows) for key,rows in {'meetings':meetings,'my_tasks':mine,'team_risks':risky,'new_documents':documents}.items()}
    spoken = f"На {day.isoformat()} встреч: {counts['meetings']}. Моих срочных задач: {counts['my_tasks']}, задач подчинённых с риском: {counts['team_risks']}. "
    spoken += (f"Главное отклонение: {deviations[0]['label']}, {deviations[0]['value']} {deviations[0]['unit']}." if deviations else 'В доступных показателях отклонений по настроенным порогам не найдено.')
    if warnings: spoken += ' Есть предупреждения об актуальности; проверьте экран.'
    return {'date':day.isoformat(),'timezone':'Europe/Minsk','generated_at':iso(generated),
            'status':'grounded' if claims else 'insufficient_data','model':None,'claims':claims,
            'sources':[s for claim in claims for s in claim['sources']], 'spoken':spoken,
            'deviations':deviations,'warnings':list(dict.fromkeys(warnings)),'truncated':truncated,'counts':counts,
            'documents_since':iso(since), **groups}


def daily(actor, value, audit):
    generated = utc_now(); day = parse_day(value, generated)
    with store.db() as c:
        c.execute('BEGIN')
        result = build(c,actor,day,generated)
    audit.update(source_ids=[s['id'] for s in result['sources']], date=day.isoformat())
    return result


def router():
    api = APIRouter(route_class=ExtensionRoute)

    @api.get('/api/meet/briefing')
    def briefing(request: Request, response: Response, date: str | None = None):
        return run(request,response,'briefing.read',lambda actor,audit:daily(actor,date,audit))

    return api
