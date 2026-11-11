"""Idempotent Photoprint seed for integrated Track 3, never resets a database."""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.track3.paths import explicit_db

DATA = ROOT / 'demo/track3'


def seed(db_path):
    path = explicit_db(db_path)
    marker = Path(str(path)+'.track3.json')
    if marker.is_symlink() or marker.is_dir():
        raise ValueError('Test marker must be a regular file')
    if marker.is_file() and json.loads(marker.read_text(encoding='utf-8')).get('db') != str(path):
        raise ValueError('Test marker path mismatch')
    if path.exists() and not marker.is_file():
        raise ValueError('Existing database lacks Track 3 test marker; use a new isolated DB')
    os.environ['MEETINGS_DB_PATH'] = str(path)
    from meetings import documents, store
    from meetings.api import parse_transcript
    from meetings.auth import ensure_demo_users
    from meetings.calendar.service import add_busy
    store.reset_cache()
    ensure_demo_users()
    fixture = json.loads((DATA/'manifest.json').read_text(encoding='utf-8'))
    result = {'dataset':fixture['version'], 'documents':{}, 'meetings':{}}
    with store.db() as c:
        if c.execute('PRAGMA user_version').fetchone()[0] < 8:
            raise RuntimeError('Requires integrated core migrations v8; do not patch store locally')
        users = {r['login']:r['id'] for r in c.execute('SELECT id,login FROM users')}
        for d in fixture['documents']:
            row = c.execute('SELECT id FROM documents WHERE filename=? AND owner_id=?', (d['filename'],users[d['owner']])).fetchone()
            if row:
                did = row['id']
            else:
                data = (DATA/'documents'/d['filename']).read_bytes()
                kind, frags = documents.fragments(d['filename'],data)
                did = c.execute('INSERT INTO documents(owner_id,title,filename,kind,content,sha256,created_at) VALUES (?,?,?,?,?,?,?)',
                                (users[d['owner']],d['title'],d['filename'],kind,data,hashlib.sha256(data).hexdigest(),d['uploaded_at'])).lastrowid
                c.executemany('INSERT INTO fragments(document_id,idx,location,text) VALUES (?,?,?,?)',
                              [(did,f['idx'],f['location'],f['text']) for f in frags])
                c.executemany('INSERT OR IGNORE INTO document_access VALUES (?,?)',[(did,users[u]) for u in d['access']])
            result['documents'][d['key']] = did
        previous = None
        for m in fixture['meetings']:
            row = c.execute('SELECT id FROM meetings WHERE title=? AND owner_id=?',(m['title'],users[m['owner']])).fetchone()
            if row:
                mid = row['id']
            else:
                mid = c.execute('INSERT INTO meetings(owner_id,title,topic,scheduled_at,participants,followup_of,created_at) VALUES (?,?,?,?,?,?,?)',
                                (users[m['owner']],m['title'],m['title'],m['scheduled_at'],json.dumps(['Ирина','Анна','Дмитрий','Пётр'],ensure_ascii=False),previous,store.now())).lastrowid
                for i,u in enumerate(parse_transcript((DATA/'transcripts'/m['transcript']).read_text(encoding='utf-8')),1):
                    c.execute('INSERT INTO utterances(meeting_id,idx,speaker_label,text,original_text,source,start_ms) VALUES (?,?,?,?,?,?,?)',
                              (mid,i,u['speaker_label'],u['text'],u['text'],'manual',u['start_ms']))
                c.executemany('INSERT OR IGNORE INTO meeting_access VALUES (?,?)',[(mid,users[u]) for u in m['access']])
                c.executemany('INSERT OR IGNORE INTO meeting_documents VALUES (?,?)',[(mid,result['documents'][key]) for key in m['documents']])
            result['meetings'][m['key']] = mid
            previous = mid
        # A separate historical meeting prevents preconfirmed synthetic tasks from contaminating control extraction.
        title = 'Фотопринт — История поручений (синтетические подтверждения)'
        old = c.execute('SELECT id FROM meetings WHERE title=? AND owner_id=?',(title,users['irina'])).fetchone()
        if not old:
            mid = c.execute('INSERT INTO meetings(owner_id,title,scheduled_at,created_at) VALUES (?,?,?,?)',
                            (users['irina'],title,'2026-11-03T10:00:00+03:00',store.now())).lastrowid
            c.execute('INSERT INTO protocols(meeting_id,generated_at,model) VALUES (?,?,?)',(mid,store.now(),'synthetic-fixture-not-model'))
            for idx,t in enumerate(fixture['history_tasks'],1):
                text = f"Анна, {t['text'].lower()} до {t['due']}."
                uid = c.execute('INSERT INTO utterances(meeting_id,idx,speaker_label,text,original_text,source) VALUES (?,?,?,?,?,?)',
                                (mid,idx,'Ирина',text,text,'manual')).lastrowid
                quote = {'utterance_id':f'U{uid}','speaker':'Ирина','text':text,'verified':True}
                pid = c.execute("INSERT INTO protocol_items(meeting_id,position,kind,text,assignee,assignee_status,due,due_status,quotes,confirmed_by,confirmed_at) VALUES (?,?,'task',?,?,'stated',?,'stated',?,?,?)",
                                (mid,idx,t['text'],'Анна',t['due'],json.dumps([quote],ensure_ascii=False),users['irina'],store.now())).lastrowid
                tid = c.execute("INSERT INTO tasks(meeting_id,protocol_item_id,text,assignee,assignee_status,due,due_status,status,source_quote,confirmed_by,confirmed_at,created_at,updated_at) VALUES (?,?,?,?,'stated',?,'stated',?,?,?,?,?,?)",
                                (mid,pid,t['text'],'Анна',t['due'],t['status'],json.dumps(quote,ensure_ascii=False),users['irina'],store.now(),store.now(),store.now())).lastrowid
                c.execute('UPDATE protocol_items SET task_id=? WHERE id=?',(tid,pid))
            c.execute('UPDATE meetings SET followup_of=? WHERE id=?',(mid,result['meetings']['delay']))
        for metric in fixture['metrics']:
            fields = ['source_id','scope','as_of','period_start','period_end','on_time_orders','completed_orders','defective_units','produced_units','occupied_capacity','available_capacity']
            c.execute(f"INSERT OR IGNORE INTO production_metrics ({','.join(fields)},owner_id,created_at) VALUES ({','.join('?' for _ in range(len(fields)+2))})",
                      [metric[k] for k in fields]+[users[metric['owner']],metric['as_of']])
            metric_id = c.execute('SELECT id FROM production_metrics WHERE source_id=?',(metric['source_id'],)).fetchone()[0]
            c.executemany('INSERT OR IGNORE INTO production_metric_access VALUES (?,?)',[(metric_id,users[u]) for u in metric['access']])
        for busy in fixture['calendar']:
            start, end = store.iso_utc(store.parse_aware(busy['start'])), store.iso_utc(store.parse_aware(busy['end']))
            if not c.execute('SELECT 1 FROM calendar_busy WHERE user_id=? AND start_at=? AND end_at=? AND source=?',
                             (users[busy['user']],start,end,fixture['version'])).fetchone():
                add_busy(c,users[busy['user']],start,end,'Синтетическая занятость',source=fixture['version'])
    # Marker declares the precise files cleanup may remove; no directories and no unrelated secret keys.
    marker = Path(str(path)+'.track3.json')
    if not marker.exists():
        marker.write_text(json.dumps({'version':1,'db':str(path),'dataset':fixture['version']}), encoding='utf-8')
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',required=True)
    args = p.parse_args()
    print(json.dumps(seed(args.db),ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
