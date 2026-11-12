"""Explicit isolated Photoprint v2 seed. No deletion; deterministic source keys prevent duplicates."""
import hashlib
import json
import os
from pathlib import Path

from scripts.track3.paths import explicit_db

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'demo/track3'


def seed(db_path):
    from meetings import documents, store
    from meetings.auth import ensure_demo_users, hash_password
    from meetings.api import parse_transcript
    from scripts.track3.gen_fotoprint_data import TOPICS, STATUSES
    path = explicit_db(db_path)
    marker = Path(str(path) + '.track3.json')
    if marker.is_symlink() or marker.is_dir():
        raise ValueError('Маркер тестовой БД должен быть обычным файлом.')
    if marker.is_file() and json.loads(marker.read_text(encoding='utf-8')).get('db') != str(path):
        raise ValueError('Путь в маркере не совпадает с БД.')
    if path.exists() and not marker.is_file():
        raise ValueError('Существующая БД не помечена как тестовая. Укажите новый абсолютный путь.')
    manifest_raw = (DATA / 'v2/manifest.json').read_bytes()
    snapshot_raw = (DATA / 'v2/snapshots.json').read_bytes()
    fixture, snapshots = json.loads(manifest_raw), json.loads(snapshot_raw)
    digest = hashlib.sha256(manifest_raw + snapshot_raw)
    for item in [*fixture['documents'], *fixture['meetings']]:
        digest.update((DATA / item['path']).read_bytes())
    digest = digest.hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not marker.exists():
        with marker.open('x', encoding='utf-8') as output:
            json.dump({'version': 1, 'db': str(path), 'dataset': 'photoprint-v2'}, output)
    os.environ['MEETINGS_DB_PATH'] = str(path)
    store.reset_cache()
    ensure_demo_users()
    with store.db() as c:
        old = c.execute('SELECT * FROM demo_imports WHERE dataset=?', (fixture['version'],)).fetchone()
        if old:
            if old['manifest_sha256'] != digest:
                raise ValueError('Набор изменился: создайте новую тестовую БД или явно сбросьте демо.')
            from scripts.track3.seed_insights import seed as seed_insights
            seed_insights(c)
            return json.loads(old['object_ids'])
        for dep in fixture['departments']:
            c.execute('INSERT OR IGNORE INTO departments(code,name) VALUES (?,?)', (dep['code'], dep['name']))
        departments = {r['code']: r['id'] for r in c.execute('SELECT id,code FROM departments')}
        for number, user in enumerate(fixture['users'], 1):
            existing = c.execute('SELECT * FROM users WHERE login=?', (user['login'],)).fetchone()
            if existing and (existing['name'] != user['name'] or existing['level'] != user['level']):
                raise ValueError('Логин демо-пользователя уже занят: ' + user['login'])
            if not existing:
                c.execute('INSERT INTO users(login,name,role,password_hash,access_role,department_id,level,personnel_code) '
                          'VALUES (?,?,?,?,?,?,?,?)', (user['login'], user['name'], user['level'],
                          hash_password(user['login'] + '-demo'), 'reader', departments[user['department']],
                          user['level'], f'T{number:03d}'))
        users = {r['login']: r['id'] for r in c.execute('SELECT id,login FROM users')}
        for user in fixture['users']:
            c.execute('UPDATE users SET manager_id=? WHERE id=?', (users.get(user['manager']), users[user['login']]))
            if user['level'] in ('director', 'head', 'lead'):
                c.execute('UPDATE departments SET head_user_id=? WHERE id=?',
                          (users[user['login']], departments[user['department']]))
        result = {'dataset': fixture['version'], 'documents': {}, 'meetings': {}, 'users': users}
        for item in fixture['documents']:
            source = 'photoprint-v2:document:' + item['key']
            data = (DATA / item['path']).read_bytes()
            kind, fragments = documents.fragments(item['filename'], data)
            did = c.execute('INSERT INTO documents(owner_id,title,filename,kind,content,sha256,created_at,department_id,'
                            'confidentiality,doc_type,version,valid_until,authored_at,source_ref) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                            (users[item['owner']], item['title'], item['filename'], kind, data, hashlib.sha256(data).hexdigest(),
                             item['uploaded_at'], departments[item['department']], item['confidentiality'], item['doc_type'],
                             item['version'], item.get('valid_until'), item['authored_at'], source)).lastrowid
            c.executemany('INSERT INTO fragments(document_id,idx,location,text) VALUES (?,?,?,?)',
                          [(did, f['idx'], f['location'], f['text']) for f in fragments])
            c.executemany('INSERT INTO document_access VALUES (?,?)', [(did, users[u]) for u in item['access']])
            result['documents'][item['key']] = did
        for item in fixture['documents']:
            if item.get('supersedes_key'):
                c.execute('UPDATE documents SET supersedes_id=? WHERE id=?',
                          (result['documents'][item['supersedes_key']], result['documents'][item['key']]))
        for item in fixture['meetings']:
            mid = c.execute('INSERT INTO meetings(owner_id,title,topic,scheduled_at,participants,created_at,department_id,'
                            'confidentiality,source_ref) VALUES (?,?,?,?,?,?,?,?,?)',
                            (users[item['owner']], item['title'], item['title'], store.iso_utc(store.parse_aware(item['scheduled_at'])),
                             json.dumps([u['name'] for u in fixture['users'] if u['login'] in [item['owner'], *item['access']]], ensure_ascii=False),
                             fixture['as_of'], departments[item['department']], item['confidentiality'],
                             'photoprint-v2:meeting:' + item['key'])).lastrowid
            for i, utterance in enumerate(parse_transcript((DATA / item['path']).read_text(encoding='utf-8')), 1):
                c.execute('INSERT INTO utterances(meeting_id,idx,speaker_label,text,original_text,source,start_ms) VALUES (?,?,?,?,?,?,?)',
                          (mid, i, utterance['speaker_label'], utterance['text'], utterance['text'], 'manual', utterance['start_ms']))
            c.executemany('INSERT INTO meeting_access VALUES (?,?)', [(mid, users[u]) for u in item['access']])
            c.executemany('INSERT INTO meeting_documents VALUES (?,?)', [(mid, result['documents'][k]) for k in item['documents']])
            result['meetings'][item['key']] = mid
        table_map = {'products': 'products', 'customers': 'crm_customers', 'orders': 'erp_orders',
                     'order_events': 'order_events', 'interactions': 'support_interactions', 'deals': 'crm_deals',
                     'production_plan': 'production_plan', 'shifts': 'work_shifts', 'absences': 'hr_absences', 'finance': 'finance_aggregates'}
        for key, table in table_map.items():
            for original in snapshots[key]:
                row = dict(original)
                if 'scope_department' in row:
                    row['department_id'] = departments[row.pop('scope_department')]
                for src, dst in [('agent_login', 'agent_user_id'), ('responsible_login', 'responsible_user_id'), ('login', 'user_id')]:
                    if src in row:
                        row[dst] = users[row.pop(src)]
                columns = list(row)
                c.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", list(row.values()))
        for code, title in [('europost_courier', 'Европочта, курьер'), ('europost_pvz', 'Европочта, ПВЗ'), ('belpost', 'Белпочта'), ('ems', 'EMS')]:
            c.execute('INSERT INTO delivery_carriers VALUES (?,?,?)', (code, title, 'Демонстрационный справочник из ТЗ v2'))
        c.executemany('INSERT INTO support_topics VALUES (?,?,?)', [(f'topic-{i:02d}', name, 120 if i == 0 else 60) for i, name in enumerate(TOPICS)])
        c.executemany('INSERT INTO order_statuses VALUES (?,?,?)', [(code, name, i) for i, (code, name) in enumerate(STATUSES)])
        _history(c, users, departments, result, fixture['as_of'])
        from meetings.calendar.service import add_busy
        for item in fixture['meetings']:
            start = store.parse_aware(item['scheduled_at'])
            from datetime import timedelta
            for login in dict.fromkeys([item['owner'], *item['access']]):
                add_busy(c, users[login], store.iso_utc(start), store.iso_utc(start + timedelta(hours=1)),
                         'Синтетическая встреча Фотопринт', source=fixture['version'])
        # Source counters remain independently inspectable in the existing overview.
        completed = [o for o in snapshots['orders'] if o['completed_at']]
        fields = dict(source_id='fpv2-erp-20261111', scope='PROD', as_of=fixture['as_of'],
                      period_start='2026-09-30T00:00:00+00:00', period_end='2026-11-12T00:00:00+00:00',
                      on_time_orders=sum(o['completed_at'] <= o['promised_at'] for o in completed), completed_orders=len(completed),
                      defective_units=sum(o['defective'] for o in completed), produced_units=len(completed),
                      occupied_capacity=75, available_capacity=100, owner_id=users['prod_head'], created_at=fixture['as_of'],
                      department_id=departments['PROD'], confidentiality='department')
        c.execute(f"INSERT INTO production_metrics ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})", list(fields.values()))
        for user in fixture['users']:
            c.execute('INSERT INTO user_external_ids VALUES (?,?,?)', (users[user['login']], 'bitrix24-mock', 'demo-' + user['login']))
        c.execute('INSERT INTO demo_imports VALUES (?,?,?,?)', (fixture['version'], digest, store.now(), json.dumps(result, ensure_ascii=False)))
        from scripts.track3.seed_insights import seed as seed_insights
        seed_insights(c)
    return result


def _history(c, users, departments, result, as_of):
    """Confirmed fixture tasks are outside the five unprocessed extraction controls."""
    owner = users['prod_head']
    mid = c.execute('INSERT INTO meetings(owner_id,title,scheduled_at,created_at,department_id,confidentiality,source_ref) '
                    'VALUES (?,?,?,?,?,?,?)', (owner, 'Фотопринт — контроль прежних поручений', '2026-11-03T09:00:00+00:00',
                     as_of, departments['PROD'], 'department', 'photoprint-v2:history')).lastrowid
    c.execute('INSERT INTO meeting_access VALUES (?,?)', (mid, users['operator']))
    c.execute('INSERT INTO protocols(meeting_id,generated_at,model) VALUES (?,?,?)', (mid, as_of, 'synthetic-fixture-not-model'))
    cases = [('Проверить остаток картона', '2026-11-05', 'open'), ('Сверить очередь Premium', '2026-11-06', 'in_progress'),
             ('Проверить настройку Kolbus', '2026-11-09', 'open'), ('Подготовить акт ОТК', '2026-11-10', 'done'),
             ('Согласовать вторую смену', None, 'open')]
    for i, (text, due, status) in enumerate(cases, 1):
        raw = f'Денис Петров, {text.lower()}' + (f' до {due}.' if due else '. Срок не определён.')
        uid = c.execute('INSERT INTO utterances(meeting_id,idx,speaker_label,text,original_text) VALUES (?,?,?,?,?)', (mid, i, 'Марина Зелёнова', raw, raw)).lastrowid
        quote = {'utterance_id': f'U{uid}', 'speaker': 'Марина Зелёнова', 'text': raw, 'verified': True}
        pid = c.execute("INSERT INTO protocol_items(meeting_id,position,kind,text,assignee,assignee_status,due,due_status,quotes,confirmed_by,confirmed_at) VALUES (?,?,'task',?,?,'stated',?,?,?,?,?)",
                        (mid, i, text, 'Денис Петров', due, 'stated' if due else 'unknown', json.dumps([quote], ensure_ascii=False), owner, as_of)).lastrowid
        tid = c.execute("INSERT INTO tasks(meeting_id,protocol_item_id,text,assignee,assignee_status,due,due_status,status,source_quote,confirmed_by,confirmed_at,created_at,updated_at,department_id,assignee_user_id) VALUES (?,?,?,?,'stated',?,?,?,?,?,?,?,?,?,?)",
                        (mid, pid, text, 'Денис Петров', due, 'stated' if due else 'unknown', status, json.dumps(quote, ensure_ascii=False), owner, as_of, as_of, as_of, departments['PROD'], users['operator'])).lastrowid
        c.execute('UPDATE protocol_items SET task_id=? WHERE id=?', (tid, pid))
    c.execute('UPDATE meetings SET followup_of=? WHERE id=?', (mid, result['meetings']['delay']))
    result['meetings']['history'] = mid
