"""Bitrix24 REST v1 boundary. Disabled by default; tests inject MockTransport.

Writes are invoked only by the human-confirmed outbox. A write timeout is
uncertain, never retried automatically. ERP data remains in the local scoped mirror.
"""
import logging
import json
import os
import re
from datetime import timedelta
from urllib.parse import urlsplit
import httpx
from meetings import access,store
from meetings.auth import has_capability
from meetings.connectors.contracts import IntegrationError
from meetings.connectors.mock import MockCRM,digest


class RedactWebhook(logging.Filter):
    def filter(self,record):
        message=record.getMessage()
        record.msg=re.sub(r'(/rest/\d+/)[^/\s?]+',r'\1[redacted]',message);record.args=()
        return True


if not any(isinstance(f,RedactWebhook) for f in logging.getLogger('httpx').filters):
    logging.getLogger('httpx').addFilter(RedactWebhook())


class Bitrix24Connector(MockCRM):
    name='bitrix24';mode='bitrix24'
    METHODS={'user.get','department.get','crm.contact.get','crm.contact.list','crm.deal.get','crm.deal.list',
             'crm.activity.list','tasks.task.add','tasks.task.get','tasks.task.update','tasks.task.list',
             'task.commentitem.add','task.commentitem.getlist','crm.timeline.comment.add','crm.timeline.comment.list',
             'calendar.accessibility.get','calendar.event.add','calendar.event.getbyid','calendar.event.delete',
             'im.notify.personal.add'}

    def __init__(self,connection,actor,*,read_faults=True,transport=None,webhook=None,enabled=None):
        super().__init__(connection,actor,read_faults=read_faults)
        self.enabled=(os.getenv('MEETINGS_BITRIX_ENABLED','0')=='1') if enabled is None else enabled
        self.webhook=webhook or os.getenv('MEETINGS_BITRIX_WEBHOOK','')
        self.transport=transport
        if self.enabled:
            p=urlsplit(self.webhook)
            if p.scheme!='https' or not p.hostname or p.username or p.password or p.query or p.fragment or not re.fullmatch(r'/rest/\d+/[A-Za-z0-9_-]{8,128}/?',p.path):
                raise IntegrationError('config')
            self.webhook=self.webhook.rstrip('/')+'/'

    def call(self,method,params=None,*,write=False,pagination=False):
        if not self.enabled:raise IntegrationError('disabled')
        if method not in self.METHODS:raise IntegrationError('forbidden')
        try:
            with httpx.Client(transport=self.transport,timeout=10,trust_env=False,follow_redirects=False,
                              verify=os.getenv('MEETINGS_BITRIX_CA_FILE') or True) as client:
                response=client.post(self.webhook+method+'.json',json=params or {})
            if 300<=response.status_code<400:raise IntegrationError('config')
            if response.status_code in (401,403):raise IntegrationError('forbidden')
            if response.status_code>=500:raise IntegrationError('uncertain' if write else 'unavailable',uncertain=write)
            if response.status_code>=400:raise IntegrationError('unavailable')
            body=response.json()
            if not isinstance(body,dict):raise ValueError()
            if body.get('error'):
                raise IntegrationError('forbidden' if body['error'] in ('ACCESS_DENIED','INVALID_CREDENTIALS','insufficient_scope') else 'unavailable')
            if 'result' not in body:raise ValueError()
            return body if pagination else body['result']
        except IntegrationError:
            raise
        except httpx.TransportError:
            raise IntegrationError('uncertain' if write else 'unavailable',uncertain=write) from None
        except (ValueError,TypeError):
            raise IntegrationError('uncertain' if write else 'unavailable',uncertain=write) from None

    def list_all(self,method,params=None):
        rows=[];start=0
        for _ in range(100):
            body=self.call(method,{**(params or {}),'start':start},pagination=True)
            if not isinstance(body['result'],list):raise IntegrationError('unavailable')
            rows.extend(body['result'])
            following=body.get('next')
            if following is None:return rows
            if type(following) is not int or following<=start:raise IntegrationError('unavailable')
            start=following
        raise IntegrationError('unavailable')

    def check(self,write=False):
        if not self.enabled:raise IntegrationError('disabled')

    def stamp(self,source_id,as_of=None):
        # A real provider must not inherit MOCK_CRM_FAULT.
        fetched=store.now();as_of=as_of or fetched
        try:
            limit=float(os.getenv('CRM_STALE_AFTER','86400'))
            if not 0<limit<=31536000:raise ValueError()
        except ValueError:raise IntegrationError('config') from None
        return {'source_id':source_id,'fetched_at':fetched,'as_of':as_of,
                'stale':(store.parse_aware(fetched)-store.parse_aware(as_of)).total_seconds()>limit}

    def entity_mapping(self,kind,local_id):
        # Owner-managed synthetic->portal IDs, never model-generated remote IDs.
        try:
            raw=os.getenv('MEETINGS_BITRIX_ENTITY_MAP','{}')
            if len(raw)>100000:raise ValueError()
            data=json.loads(raw)
            value=data.get(kind,{}).get(str(local_id))
            if value is None:return None
            if not re.fullmatch(r'[1-9]\d{0,17}',str(value)):raise ValueError()
            return str(value)
        except (ValueError,AttributeError,TypeError):raise IntegrationError('config') from None

    def list_external_users(self):
        if not self.actor or not has_capability(self.actor,'integrations.manage'):raise IntegrationError('forbidden')
        rows=self.list_all('user.get',{'FILTER':{'ACTIVE':True}})
        if not isinstance(rows,list):raise IntegrationError('unavailable')
        # No contacts, phones, addresses or pay fields are returned.
        return [{'external_id':str(r['ID']),'name':(str(r.get('NAME',''))+' '+str(r.get('LAST_NAME',''))).strip()[:200]}
                for r in rows if str(r.get('ID','')).isdigit()]

    def get_employee(self,external_id):
        if not str(external_id).isdigit():return None
        if not self.actor or not self.actor['active']:return None
        mapping=self.c.execute('SELECT u.id,u.name,u.department_id FROM users u JOIN user_external_ids x ON x.user_id=u.id '
            "WHERE x.connector=? AND x.external_id=? AND u.active=1 AND u.level NOT IN ('admin','auditor')",(self.name,str(external_id))).fetchone()
        if not mapping:return None
        if self.actor['level']!='director' and mapping['id']!=self.actor['id'] and mapping['department_id'] not in [self.actor['department_id'],*self.actor.get('_delegated_departments',[])]:return None
        rows=self.call('user.get',{'ID':str(external_id)})
        row=next((r for r in rows if str(r.get('ID'))==str(external_id)),None) if isinstance(rows,list) else None
        if not row or row.get('ACTIVE') in (False,'N','0'):return None
        return {**dict(mapping),'external_id':str(external_id),**self.stamp('bitrix24:employee:'+str(external_id))}

    def list_departments(self):
        rows=self.list_all('department.get')
        if not isinstance(rows,list):raise IntegrationError('unavailable')
        return [{'id':str(r['ID']),'name':str(r.get('NAME',''))[:200],**self.stamp('bitrix24:department:'+str(r['ID']))}
                for r in rows if str(r.get('ID','')).isdigit()]

    def _authorized(self,kind,object_id):
        if not self.actor or not has_capability(self.actor,'crm.write'):raise IntegrationError('forbidden')
        mid=object_id
        if kind=='task':
            row=self.c.execute('SELECT meeting_id FROM tasks WHERE id=?',(object_id,)).fetchone()
            if not row:raise IntegrationError('forbidden')
            mid=row[0]
        meeting=self.c.execute('SELECT * FROM meetings WHERE id=?',(mid,)).fetchone()
        if not meeting or meeting['confidentiality']=='secret' or not access.object_decision(self.c,self.actor['id'],'meeting',mid,'crm.write').allowed:
            raise IntegrationError('forbidden')
        if self.actor['level']=='head' and meeting['department_id'] not in [self.actor['department_id'],*self.actor.get('_delegated_departments',[])]:raise IntegrationError('forbidden')

    def create_task(self,draft,idempotency_key):
        self._authorized('task',draft['task_id'])
        task=self.c.execute('SELECT assignee_user_id FROM tasks WHERE id=?',(draft['task_id'],)).fetchone()
        mapping=self.c.execute('SELECT external_id FROM user_external_ids WHERE connector=? AND user_id=?',
                               (self.name,task['assignee_user_id'])).fetchone()
        if not mapping or mapping[0]!=draft['assignee_external_id']:raise IntegrationError('conflict')
        marker='callwise:'+idempotency_key;proof='CallWise sha256:'+digest(draft)
        result=self.call('tasks.task.list',{'filter':{'TAG':marker},'select':['ID','DESCRIPTION','TAGS']})
        if not isinstance(result,dict) or not isinstance(result.get('tasks'),list):raise IntegrationError('unavailable')
        existing=result['tasks']
        if existing:
            if len(existing)!=1 or proof not in str(existing[0].get('description',existing[0].get('DESCRIPTION',''))):raise IntegrationError('conflict')
            ident=str(existing[0].get('id',existing[0].get('ID','')))
        else:
            fields={'TITLE':draft['text'][:255],'RESPONSIBLE_ID':int(draft['assignee_external_id']),
                    'DESCRIPTION':proof+'\n'+draft['source_path']+'\n'+draft['source_quote']['text'],'TAGS':[marker]}
            if draft.get('due'):fields['DEADLINE']=draft['due']+'T23:59:59+03:00'
            result=self.call('tasks.task.add',{'fields':fields},write=True)
            task=result.get('task',{}) if isinstance(result,dict) else {}
            ident=str(task.get('id',task.get('ID','')))
        if not ident.isdigit():raise IntegrationError('uncertain',uncertain=True)
        return {'ref':'bitrix24:task:'+ident,**self.stamp('bitrix24:task:'+ident)}

    def get_task_status(self,ref):
        match=re.fullmatch(r'bitrix24:task:(\d{1,18})',ref or '')
        if not match:return None
        row=self.c.execute("SELECT object_id FROM integration_outbox WHERE connector=? AND external_ref=? AND object_type='task'",(self.name,ref)).fetchone()
        if not row:return None
        task=self.c.execute('SELECT meeting_id FROM tasks WHERE id=?',(row[0],)).fetchone()
        if not task or not store.can_read_meeting(self.c,self.actor['id'],task[0]):return None
        result=self.call('tasks.task.get',{'taskId':match[1],'select':['ID','TITLE','STATUS']})
        value=result.get('task',{}) if isinstance(result,dict) else {}
        return {'ref':ref,'status':str(value.get('status',value.get('STATUS','unknown'))),**self.stamp(ref)}

    def get_deal(self,deal_id):
        # Local mirror authorizes the entity before the remote read.
        mirror=super().get_deal(deal_id)
        if not mirror:return None
        external=self.entity_mapping('deals',deal_id)
        if not external:return None
        row=self.call('crm.deal.get',{'id':external})
        if not isinstance(row,dict):raise IntegrationError('unavailable')
        if str(row.get('ID'))!=external:raise IntegrationError('conflict')
        return {'id':str(deal_id),'external_id':external,'title':'Сделка '+str(deal_id),**self.stamp('bitrix24:deal:'+external)}

    def get_customer(self,customer_id):
        mirror=super().get_customer(customer_id)
        if not mirror:return None
        external=self.entity_mapping('contacts',customer_id)
        if not external:return None
        row=self.call('crm.contact.get',{'id':external})
        if not isinstance(row,dict) or str(row.get('ID'))!=external:raise IntegrationError('unavailable')
        # Do not project names/phone/mail/address, even when the provider returns them.
        return {'id':str(customer_id),'kind':mirror['kind'],'display_name':'Клиент '+str(customer_id),
                **self.stamp('bitrix24:contact:'+external)}

    def list_activities(self,deal_id):
        deal=self.get_deal(deal_id)
        if not deal:return []
        rows=self.list_all('crm.activity.list',{'filter':{'OWNER_TYPE_ID':2,'OWNER_ID':int(deal['external_id'])},
            'select':['ID','OWNER_ID','OWNER_TYPE_ID','TYPE_ID','COMPLETED']})
        result=[]
        for row in rows:
            if str(row.get('OWNER_ID'))!=deal['external_id'] or str(row.get('OWNER_TYPE_ID'))!='2':
                raise IntegrationError('conflict')
            if not str(row.get('ID','')).isdigit():raise IntegrationError('unavailable')
            result.append({'id':str(row['ID']),'deal_id':str(deal_id),'type':str(row.get('TYPE_ID','')),
                           'completed':row.get('COMPLETED')=='Y',**self.stamp('bitrix24:activity:'+str(row['ID']))})
        return result

    def attach_protocol(self,entity_ref,protocol,idempotency_key):
        self._authorized('protocol',protocol['meeting_id'])
        marker='[CallWise:'+idempotency_key+']';proof='CallWise sha256:'+digest([entity_ref,protocol])
        text=marker+'\n'+proof+'\n'+protocol['title']+'\n'+'\n'.join(i['text'] for i in protocol['items'])+'\n'+protocol['source_path']
        if entity_ref.startswith('deal:'):
            ident=entity_ref[5:]
            deal=self.get_deal(ident)
            if not deal:raise IntegrationError('forbidden')
            ident=deal['external_id']
            result=self.call('crm.timeline.comment.list',{'filter':{'ENTITY_ID':int(ident),'ENTITY_TYPE':'deal'},'select':['ID','COMMENT']})
            if not isinstance(result,list):raise IntegrationError('unavailable')
            rows=result
            found=[r for r in rows if marker in str(r.get('COMMENT',''))]
            if found:
                if len(found)!=1 or proof not in str(found[0].get('COMMENT','')):raise IntegrationError('conflict')
                external=str(found[0]['ID'])
            else:external=str(self.call('crm.timeline.comment.add',{'fields':{'ENTITY_ID':int(ident),'ENTITY_TYPE':'deal','COMMENT':text}},write=True))
        else:
            if not self.get_task_status(entity_ref):raise IntegrationError('forbidden')
            target=self.c.execute("SELECT object_id FROM integration_outbox WHERE connector=? AND external_ref=? AND object_type='task'",(self.name,entity_ref)).fetchone()
            if not target:raise IntegrationError('forbidden')
            self._authorized('task',target[0])
            ident=entity_ref.rsplit(':',1)[1]
            rows=self.call('task.commentitem.getlist',{'TASKID':int(ident)})
            if not isinstance(rows,list):raise IntegrationError('unavailable')
            found=[r for r in rows if marker in str(r.get('POST_MESSAGE',''))]
            if found and (len(found)!=1 or proof not in str(found[0].get('POST_MESSAGE',''))):raise IntegrationError('conflict')
            external=str(found[0]['ID']) if found else str(self.call('task.commentitem.add',{'TASKID':int(ident),'FIELDS':{'POST_MESSAGE':text}},write=True))
        if not external.isdigit():raise IntegrationError('uncertain',uncertain=True)
        return {'ref':'bitrix24:comment:'+external,**self.stamp('bitrix24:comment:'+external)}
