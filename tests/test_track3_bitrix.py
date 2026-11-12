import json
import logging
import httpx
import pytest
from meetings import store
from meetings.connectors.bitrix24 import Bitrix24Connector
from meetings.connectors.contracts import IntegrationError
from meetings.connectors.mock import digest
from tests.test_track3_briefing import env

WEBHOOK='https://portal.invalid/rest/1/synthetic-key-only/'


def setup(env,handler,who='prod_head'):
    with store.db() as c:
        task=c.execute('SELECT * FROM tasks WHERE assignee_user_id IS NOT NULL LIMIT 1').fetchone()
        c.execute("INSERT OR REPLACE INTO user_external_ids VALUES (?,'bitrix24','123')",(task['assignee_user_id'],))
    return task['id'],httpx.MockTransport(handler)


def draft(tid):
    return {'task_id':tid,'text':'Проверить картон','assignee_external_id':'123','due':'2026-11-20',
            'source_path':'/api/meet/utterances/U1','source_quote':{'text':'Проверить картон'}}


def test_task_mapping_marker_and_remote_dedup(env):
    calls=[];created=[]
    def handler(request):
        method=request.url.path.rsplit('/',1)[1];body=json.loads(request.content);calls.append((method,body))
        if method=='tasks.task.list.json':return httpx.Response(200,json={'result':{'tasks':created}})
        assert method=='tasks.task.add.json'
        fields=body['fields'];assert fields['RESPONSIBLE_ID']==123 and fields['TAGS']==['callwise:idem']
        created.append({'id':'77','description':fields['DESCRIPTION']})
        return httpx.Response(200,json={'result':{'task':{'id':'77'}}})
    tid,transport=setup(env,handler)
    with store.db() as c:
        connector=Bitrix24Connector(c,env['ids']['users']['prod_head'],enabled=True,webhook=WEBHOOK,transport=transport)
        first=connector.create_task(draft(tid),'idem');second=connector.create_task(draft(tid),'idem')
        assert first['ref']==second['ref']=='bitrix24:task:77'
        assert len([r for r in calls if r[0]=='tasks.task.add.json'])==1


def test_timeout_on_write_is_uncertain_no_library_retry(env):
    calls=[]
    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith('tasks.task.list.json'):return httpx.Response(200,json={'result':{'tasks':[]}})
        raise httpx.ReadTimeout('synthetic timeout',request=request)
    tid,transport=setup(env,handler)
    with store.db() as c:
        connector=Bitrix24Connector(c,env['ids']['users']['prod_head'],enabled=True,webhook=WEBHOOK,transport=transport)
        with pytest.raises(IntegrationError) as error:connector.create_task(draft(tid),'one-try')
        assert error.value.code=='uncertain' and error.value.uncertain and len(calls)==2
        assert 'synthetic-key' not in str(error.value)


@pytest.mark.parametrize('url',['http://portal.invalid/rest/1/test-token/','https://user:pass@portal.invalid/rest/1/test-token/',
                               'https://portal.invalid/','https://portal.invalid/rest/1/test-token/?key=private'])
def test_invalid_config_never_reaches_transport(env,url):
    with store.db() as c:
        with pytest.raises(IntegrationError):Bitrix24Connector(c,env['ids']['users']['director'],enabled=True,webhook=url)


def test_disabled_connector_never_calls_network(env):
    def handler(request):raise AssertionError('disabled')
    with store.db() as c:
        connector=Bitrix24Connector(c,env['ids']['users']['director'],enabled=False,transport=httpx.MockTransport(handler))
        with pytest.raises(IntegrationError) as error:connector.call('department.get')
        assert error.value.code=='disabled'


def test_redirect_and_foreign_write_blocked(env):
    calls=[]
    def handler(request):calls.append(1);return httpx.Response(302,headers={'Location':'https://outside.invalid'})
    tid,transport=setup(env,handler)
    with store.db() as c:
        connector=Bitrix24Connector(c,env['ids']['users']['director'],enabled=True,webhook=WEBHOOK,transport=transport)
        with pytest.raises(IntegrationError) as error:connector.call('department.get')
        assert error.value.code=='config' and len(calls)==1
        connector=Bitrix24Connector(c,env['ids']['users']['operator'],enabled=True,webhook=WEBHOOK,transport=transport)
        with pytest.raises(IntegrationError) as error:connector.create_task(draft(tid),'forbidden')
        assert error.value.code=='forbidden' and len(calls)==1


def test_request_logging_redacts_webhook_and_pagination_is_complete(env,caplog):
    def handler(request):
        start=json.loads(request.content)['start']
        return httpx.Response(200,json={'result':[{'ID':'1' if start==0 else '2','NAME':'Демо'}],**({'next':50} if start==0 else {})})
    with store.db() as c:
        connector=Bitrix24Connector(c,env['ids']['users']['admin'],enabled=True,webhook=WEBHOOK,transport=httpx.MockTransport(handler))
        with caplog.at_level(logging.INFO,logger='httpx'):
            rows=connector.list_external_users()
        assert len(rows)==2 and 'synthetic-key-only' not in caplog.text
        assert all(set(r)=={'external_id','name'} for r in rows)


def test_crm_http_transport_uses_frozen_preview_and_durable_uncertain(env,monkeypatch):
    from meetings.connectors import api
    calls=[]
    def handler(request):
        method=request.url.path.rsplit('/',1)[1];calls.append(method)
        if method=='user.get.json':return httpx.Response(200,json={'result':[{'ID':'123','ACTIVE':True}]})
        if method=='tasks.task.list.json':return httpx.Response(200,json={'result':{'tasks':[]}})
        raise httpx.ReadTimeout('write timeout',request=request)
    tid,transport=setup(env,handler)
    monkeypatch.setenv('MEETINGS_BITRIX_ENABLED','1')
    monkeypatch.setattr(api,'connector',lambda c,actor,**kw:Bitrix24Connector(c,actor,enabled=True,webhook=WEBHOOK,transport=transport,**kw))
    client=env['prod_head'];r=client.post('/api/meet/crm/preview',json={'action':'task.create','object_id':tid})
    assert r.status_code==200,r.text
    payload={'confirmation_id':r.json()['confirmation_id'],'idempotency_key':'uncertain-bitrix-http'}
    response=client.post('/api/meet/crm/confirm',json=payload)
    assert response.status_code==503 and response.json()['status']=='uncertain'
    count=len(calls)
    again=client.post('/api/meet/crm/confirm',json=payload)
    assert again.status_code==503 and again.json()['already_confirmed'] and len(calls)==count


def test_employee_mapping_requires_preview_and_no_role_updates(env):
    client=env['admin'];directory=client.get('/api/meet/integrations/employees')
    assert directory.status_code==200,directory.text
    old=directory.json()['mappings'][0];payload={'mappings':[old]}
    with store.db() as c:before=[tuple(r) for r in c.execute('SELECT id,level,department_id,active FROM users ORDER BY id')]
    r=client.post('/api/meet/integrations/employees/preview',json=payload);assert r.status_code==200,r.text
    data={'confirmation_id':r.json()['confirmation_id'],'idempotency_key':'sync-mapping-only'}
    r=client.post('/api/meet/integrations/employees/confirm',json=data);assert r.status_code==200,r.text
    assert client.post('/api/meet/integrations/employees/confirm',json=data).json()['already_confirmed']
    assert env['operator'].get('/api/meet/integrations/employees').status_code==403
    with store.db() as c:assert [tuple(r) for r in c.execute('SELECT id,level,department_id,active FROM users ORDER BY id')]==before


def test_contacts_and_activities_are_locally_scoped_and_anonymous(env,monkeypatch):
    calls=[]
    with store.db() as c:
        customer=c.execute('SELECT id FROM crm_customers LIMIT 1').fetchone()[0]
        deal=c.execute('SELECT id FROM crm_deals LIMIT 1').fetchone()[0]
    monkeypatch.setenv('MEETINGS_BITRIX_ENTITY_MAP',json.dumps({'contacts':{customer:'41'},'deals':{deal:'42'}}))
    def handler(request):
        method=request.url.path.rsplit('/',1)[1];calls.append(method)
        if method=='crm.contact.get.json':return httpx.Response(200,json={'result':{'ID':'41','NAME':'PRIVATE','PHONE':['PRIVATE']}})
        if method=='crm.deal.get.json':return httpx.Response(200,json={'result':{'ID':'42','TITLE':'PRIVATE'}})
        if method=='crm.activity.list.json':
            assert json.loads(request.content)['filter']=={'OWNER_TYPE_ID':2,'OWNER_ID':42}
            return httpx.Response(200,json={'result':[{'ID':'43','OWNER_TYPE_ID':'2','OWNER_ID':'42','DESCRIPTION':'PRIVATE','COMPLETED':'Y'}]})
        raise AssertionError(method)
    with store.db() as c:
        crm=Bitrix24Connector(c,env['ids']['users']['director'],enabled=True,webhook=WEBHOOK,transport=httpx.MockTransport(handler))
        contact=crm.get_customer(customer);activities=crm.list_activities(deal)
        assert contact and activities and 'PRIVATE' not in json.dumps([contact,activities])
        count=len(calls)
        assert crm.get_customer('client-not-in-mirror') is None and len(calls)==count
        crm=Bitrix24Connector(c,env['ids']['users']['admin'],enabled=True,webhook=WEBHOOK,transport=httpx.MockTransport(handler))
        assert crm.get_customer(customer) is None and len(calls)==count


def test_forged_assignee_never_reaches_transport(env):
    def handler(request):raise AssertionError('forged mapping reached network')
    tid,transport=setup(env,handler)
    with store.db() as c:
        crm=Bitrix24Connector(c,env['ids']['users']['director'],enabled=True,webhook=WEBHOOK,transport=transport)
        value=draft(tid);value['assignee_external_id']='999'
        with pytest.raises(IntegrationError) as error:crm.create_task(value,'forged')
        assert error.value.code=='conflict'
