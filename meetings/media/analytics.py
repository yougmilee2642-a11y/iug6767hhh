"""Deterministic conversation metrics. Timings describe segments, not emotion."""
import re
import json
from meetings import store


def tokens(text):return set(re.findall(r'[а-яёa-z0-9]{4,}',text.lower().replace('ё','е')))


def union_duration(intervals):
    total=0;end=None
    for a,b in sorted(intervals):
        total+=max(0,b-max(a,end if end is not None else a));end=max(end or b,b)
    return total


def build(c,meeting):
    rows=store.utterances(c,meeting['id']);timed=[u for u in rows if u.get('start_ms') is not None and u.get('end_ms') is not None]
    job=c.execute("SELECT duration_ms FROM media_jobs WHERE meeting_id=? AND imported_at IS NOT NULL ORDER BY id DESC LIMIT 1",(meeting['id'],)).fetchone()
    call=c.execute('SELECT duration_ms FROM calls WHERE meeting_id=?',(meeting['id'],)).fetchone()
    duration=job[0] if job and job[0] else call[0] if call and call[0] else max((u['end_ms'] for u in timed),default=None)
    groups={}
    for u in timed:groups.setdefault(u['speaker'],[]).append((u['start_ms'],u['end_ms']))
    speech={name:union_duration(intervals) for name,intervals in groups.items()}
    # Overlap makes speech sum exceed elapsed time. Speech share uses summed
    # per-speaker intervals, not fabricated exclusive turn ownership.
    total=sum(speech.values());people=[]
    names=list(dict.fromkeys([*json.loads(meeting['participants']),*groups]))
    for name in names:
        share=round(speech.get(name,0)/total*100,1) if total else None
        people.append({'speaker':name,'speech_ms':speech.get(name,0) if timed else None,'share_percent':share,
                       'little_speech':share is not None and share<5})
    boundaries={}
    for u in timed:
        boundaries.setdefault(u['start_ms'],[]).append((u['speaker'],1))
        boundaries.setdefault(u['end_ms'],[]).append((u['speaker'],-1))
    active={};overlap=0;last=None
    for at,changes in sorted(boundaries.items()):
        if last is not None and len(active)>1:overlap+=at-last
        for name,delta in changes:
            active[name]=active.get(name,0)+delta
            if not active[name]:active.pop(name)
        last=at
    pauses=[];cursor=0
    for a,b in sorted((u['start_ms'],u['end_ms']) for u in timed):
        if a-cursor>=5000:pauses.append({'start_ms':cursor,'end_ms':a,'duration_ms':a-cursor})
        cursor=max(cursor,b)
    if timed and duration and duration-cursor>=5000:pauses.append({'start_ms':cursor,'end_ms':duration,'duration_ms':duration-cursor})
    agenda=[]
    for title in str(meeting['topic'] or '').splitlines():
        words=tokens(title)
        matches=[u for u in timed if words & tokens(u['text'])]
        agenda.append({'text':title,'speech_ms':union_duration([(u['start_ms'],u['end_ms']) for u in matches]),
                       'source_ids':[u['id'] for u in matches], 'method':'Совпадение слов; время пунктов может пересекаться.'})
    counts=dict(c.execute("SELECT kind,count(*) FROM protocol_items WHERE meeting_id=? GROUP BY kind",(meeting['id'],)).fetchall())
    tasks=c.execute('SELECT assignee_status,due_status,status FROM tasks WHERE meeting_id=?',(meeting['id'],)).fetchall()
    return {'meeting_id':meeting['id'],'duration_ms':duration,'timing_available':bool(timed),'speakers':people,
            'overlap_ms':overlap if timed else None,'long_pauses':pauses,'agenda':agenda,'item_counts':counts,
            'missing_assignee':sum(t['assignee_status']=='unknown' for t in tasks),'missing_due':sum(t['due_status']=='unknown' for t in tasks),
            'method':'Сегменты записи; пересечения не доказывают перебивание, а доля речи не измеряет вовлечённость.',
            'source_at':meeting['scheduled_at'] or meeting['created_at']}
