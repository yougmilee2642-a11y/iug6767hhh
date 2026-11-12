"""SQLite CRM/ERP mirror, scoped before reading. Never sends HTTP requests.

Mock objects and outbox share a transaction. This proves local idempotency, not
distributed exactly-once delivery to a real Bitrix24 installation.
"""
import hashlib
import json
import os
from datetime import timedelta
from meetings import access, store
from meetings.connectors.contracts import IntegrationError


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class MockCRM:
    name = 'bitrix24-mock'

    def __init__(self, connection, actor, *, read_faults=True):
        self.c, self.actor = connection, access.load_user(connection, actor)
        self.read_faults = read_faults

    def check(self, write=False):
        if not write and not self.read_faults: return
        fault = os.getenv('MOCK_CRM_FAULT', '')
        if fault not in ('', 'timeout', 'stale', 'down'):
            raise IntegrationError('config')
        if fault == 'timeout':
            raise IntegrationError('uncertain' if write else 'unavailable', uncertain=write)
        if fault == 'down': raise IntegrationError('unavailable')

    def stamp(self, source_id, as_of=None):
        fetched = store.now()
        as_of = as_of or fetched
        if os.getenv('MOCK_CRM_FAULT') == 'stale':
            as_of = store.iso_utc(store.parse_aware(fetched) - timedelta(days=7))
        try:
            limit = float(os.getenv('CRM_STALE_AFTER', '86400'))
            if not 0 < limit <= 31536000: raise ValueError()
        except ValueError: raise IntegrationError('config') from None
        return {'source_id':source_id, 'fetched_at':fetched, 'as_of':as_of,
                'stale':(store.parse_aware(fetched)-store.parse_aware(as_of)).total_seconds() > limit}

    def _row(self, table, key, value, own=None):
        self.check()
        predicate, args = access.snapshot_predicate(self.c, self.actor['id'], 's', own_column=own)
        row = self.c.execute(f'SELECT s.* FROM {table} s WHERE s.{key}=? AND '+predicate, [value, *args]).fetchone()
        return {**dict(row), **self.stamp(row['source_id'], row['as_of'])} if row else None

    def get_employee(self, external_id):
        self.check()
        if not self.actor or not self.actor['active'] or self.actor.get('level') not in access.CONTENT_LEVELS:
            return None
        row = self.c.execute('SELECT u.id,u.name,u.department_id,x.external_id FROM users u '
            'JOIN user_external_ids x ON x.user_id=u.id WHERE u.active=1 AND x.connector=? AND x.external_id=? '
            "AND u.level NOT IN ('admin','auditor')", (self.name, external_id)).fetchone()
        if not row: return None
        actor = self.actor or {}
        if actor.get('level') != 'director' and row['id'] != actor.get('id') and row['department_id'] not in [actor.get('department_id'), *actor.get('_delegated_departments', [])]:
            return None
        return {**dict(row), **self.stamp('mock:employee:'+external_id)}

    def list_departments(self):
        self.check()
        return [{**dict(r), **self.stamp('mock:department:'+r['code'])}
                for r in self.c.execute('SELECT id,code,name FROM departments ORDER BY id')]

    def get_customer(self, customer_id):
        row = self._row('crm_customers','id',customer_id)
        if not row: return None
        # Explicit allowlist: future contact fields in the source never escape.
        return {**{k:row[k] for k in ('id','kind','source_id','fetched_at','as_of','stale')},
                'display_name':'Клиент '+row['id']}

    def get_order(self, order_no):
        row = self._row('erp_orders','order_no',order_no)
        if row:
            row['events'] = [dict(r) for r in self.c.execute('SELECT status,at FROM order_events WHERE order_no=? ORDER BY at',(order_no,))]
        return row

    def get_deal(self, deal_id):
        return self._row('crm_deals','id',deal_id,'responsible_user_id')

    def find_interactions(self, *, order_no=None, customer_id=None):
        self.check()
        if not (order_no or customer_id): return []
        predicate,args = access.snapshot_predicate(self.c,self.actor['id'],'s',own_column='agent_user_id')
        query = 'SELECT s.* FROM support_interactions s WHERE '+predicate
        if order_no: query += ' AND order_no=?'; args.append(order_no)
        if customer_id: query += ' AND client_ref=?'; args.append(customer_id)
        from meetings.privacy import Masker
        masker = Masker(r[0] for r in self.c.execute('SELECT display_name FROM crm_customers'))
        return [{**dict(r), 'body':masker.text(r['body']), **self.stamp(r['source_id'],r['as_of'])}
                for r in self.c.execute(query+' ORDER BY opened_at,id',args)]

    def _create(self, kind, object_id, payload, idem, entity_ref=None):
        from meetings.auth import has_capability
        if not self.actor: raise IntegrationError('forbidden')
        actor = access.load_user(self.c,self.actor['id'])
        if not has_capability(actor,'crm.write'): raise IntegrationError('forbidden')
        if kind=='task':
            task = self.c.execute('SELECT meeting_id FROM tasks WHERE id=?',(object_id,)).fetchone()
            meeting_id = task['meeting_id'] if task else None
        else: meeting_id = object_id
        meeting = self.c.execute('SELECT confidentiality,department_id FROM meetings WHERE id=?',(meeting_id,)).fetchone()
        if not meeting or meeting['confidentiality']=='secret' or not access.object_decision(self.c,actor['id'],'meeting',meeting_id,'crm.write').allowed:
            raise IntegrationError('forbidden')
        if actor.get('level')=='head' and meeting['department_id'] not in [actor.get('department_id'),*actor.get('_delegated_departments',[])]:
            raise IntegrationError('forbidden')
        old = self.c.execute('SELECT * FROM mock_crm_objects WHERE idempotency_key=? OR '
            '(kind=? AND object_id=? AND entity_ref IS ?)', (idem,kind,object_id,entity_ref)).fetchone()
        if old:
            if old['payload_hash'] != digest(payload): raise IntegrationError('conflict')
            return {'ref':old['ref'], **self.stamp(old['source_id'],old['as_of'])}
        self.check(write=True)
        ref = 'mock:'+kind+':'+digest([kind,object_id,entity_ref])[:24]
        stamp = store.now()
        self.c.execute('INSERT INTO mock_crm_objects(ref,kind,object_id,entity_ref,payload,payload_hash,idempotency_key,source_id,as_of) VALUES (?,?,?,?,?,?,?,?,?)',
            (ref,kind,object_id,entity_ref,json.dumps(payload,ensure_ascii=False),digest(payload),idem,ref,stamp))
        return {'ref':ref, **self.stamp(ref,stamp)}

    def create_task(self, draft, idempotency_key):
        return self._create('task',draft['task_id'],draft,idempotency_key)

    def get_task_status(self, ref):
        self.check()
        row = self.c.execute("SELECT * FROM mock_crm_objects WHERE ref=? AND kind='task'",(ref,)).fetchone()
        if not row: return None
        task = self.c.execute('SELECT meeting_id FROM tasks WHERE id=?',(row['object_id'],)).fetchone()
        if not task or not store.can_read_meeting(self.c,self.actor['id'],task['meeting_id']): return None
        return {'ref':ref,'status':row['status'], **self.stamp(row['source_id'],row['as_of'])}

    def attach_protocol(self, entity_ref, protocol, idempotency_key):
        return self._create('protocol',protocol['meeting_id'],protocol,idempotency_key,entity_ref)
