"""Actual HTTP confirmation flow against a SQLite-only CRM; no model/network."""
import json
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from meetings import store
from meetings.api import install
from meetings.connectors.mock import MockCRM
from meetings.connectors.contracts import IntegrationError
from scripts.track3.seed_fotoprint import seed


@pytest.fixture
def env(tmp_path,monkeypatch):
    monkeypatch.setenv('MEETINGS_DB_PATH',str(tmp_path/'crm.db'))
    monkeypatch.setenv('MEETINGS_SECRET','crm-test-secret')
    monkeypatch.delenv('MOCK_CRM_FAULT',raising=False)
    ids = seed(str(tmp_path/'crm.db')); app = FastAPI(); install(app)
    clients = {}
    for login in ['director','prod_head','operator','admin','designer']:
        c = TestClient(app)
        assert c.post('/api/meet/login',json={'login':login,'password':login+'-demo'}).status_code==200
        clients[login] = c
    yield {**clients,'ids':ids,'monkeypatch':monkeypatch}
    store.reset_cache()


def task(env):
    return next(t for t in env['prod_head'].get('/api/meet/tasks').json()['tasks'] if t['status']=='open')


def preview(env,t=None):
    t = t or task(env)
    r = env['prod_head'].post('/api/meet/crm/preview',json={'action':'task.create','object_id':t['id']})
    assert r.status_code==200,r.text
    return r.json()


def token(p,key='crm-confirm-key'):
    return {'confirmation_id':p['confirmation_id'],'idempotency_key':key}


def counts():
    with store.db() as c:
        return tuple(c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in ['integration_outbox','mock_crm_objects'])


def test_create_repeat_restart_and_distinct_previews_do_not_duplicate(env):
    t = task(env); p = preview(env,t); other = preview(env,t)
    fields = p['preview']['fields']
    assert fields['assignee_external_id']=='demo-operator'
    assert fields['source_quote']['utterance_id'].startswith('U')
    assert fields['due']==t['due'] and counts()==(0,0)
    c = env['prod_head']; body = token(p)
    r = c.post('/api/meet/crm/confirm',json=body)
    assert r.status_code==200,r.text
    assert r.json()['status']=='sent' and r.json()['external_ref'].startswith('mock:task:')
    assert counts()==(1,1)
    store.reset_cache()
    repeat = c.post('/api/meet/crm/confirm',json=body)
    assert repeat.json()['already_confirmed'] and counts()==(1,1)
    assert c.post('/api/meet/crm/confirm',json=token(other,'other-preview-key')).status_code==409
    assert c.post('/api/meet/crm/preview',json={'action':'task.create','object_id':t['id']}).status_code==409
    status = c.get(f"/api/meet/crm/tasks/{t['id']}").json()
    assert status['outbox']['status']=='sent' and status['external']['status']=='open'
    saved = next(row for row in c.get('/api/meet/tasks').json()['tasks'] if row['id']==t['id'])
    assert saved['external_ref']==r.json()['external_ref']


def test_cancel_is_zero_writes(env):
    p = preview(env); c = env['prod_head']
    assert c.post(f"/api/meet/confirmations/{p['confirmation_id']}/cancel").status_code==200
    assert c.post('/api/meet/crm/confirm',json=token(p)).status_code==409
    assert counts()==(0,0)


def test_employee_denial_and_foreign_token_are_audited(env):
    t = task(env)
    for login in ['operator','admin']:
        r = env[login].post('/api/meet/crm/preview',json={'action':'task.create','object_id':t['id']})
        assert r.status_code==403
    p = preview(env)
    assert env['director'].post('/api/meet/crm/confirm',json=token(p)).status_code==404
    with store.db() as c:
        assert c.execute("SELECT COUNT(*) FROM audit WHERE result='denied' AND action IN ('crm.export','access_denied')").fetchone()[0]>=2
        with pytest.raises(IntegrationError,match='Ошибка интеграции'):
            MockCRM(c,env['ids']['users']['operator']).create_task({'task_id':t['id']},'adapter-denied')
    assert counts()==(0,0)


@pytest.mark.parametrize('change',['mapping','source','task','role','secret'])
def test_confirm_revalidates_current_state(env,change):
    t = task(env); p = preview(env,t)
    with store.db() as c:
        if change=='mapping': c.execute('DELETE FROM user_external_ids WHERE user_id=?',(t['assignee_user_id'],))
        if change=='source': c.execute("UPDATE utterances SET text='Реплика исправлена' WHERE id=?",(int(t['source_quote']['utterance_id'][1:]),))
        if change=='task': c.execute("UPDATE tasks SET due='2026-12-01',version=version+1 WHERE id=?",(t['id'],))
        if change=='role': c.execute("UPDATE users SET level='employee' WHERE login='prod_head'")
        if change=='secret': c.execute("UPDATE meetings SET confidentiality='secret' WHERE id=?",(t['meeting_id'],))
    r = env['prod_head'].post('/api/meet/crm/confirm',json=token(p))
    assert r.status_code in (403,409,422),r.text
    assert counts()==(0,0)


@pytest.mark.parametrize('fault,expected',[('timeout','uncertain'),('down','failed')])
def test_fault_is_durable_and_replay_never_retries(env,fault,expected):
    p = preview(env); env['monkeypatch'].setenv('MOCK_CRM_FAULT',fault)
    r = env['prod_head'].post('/api/meet/crm/confirm',json=token(p))
    assert r.status_code==503 and r.json()['status']==expected,r.text
    assert counts()==(1,0)
    env['monkeypatch'].delenv('MOCK_CRM_FAULT')
    again = env['prod_head'].post('/api/meet/crm/confirm',json=token(p))
    assert again.status_code==503 and again.json()['already_confirmed']
    assert again.json()['status']==expected and counts()==(1,0)
    assert env['prod_head'].post('/api/meet/crm/preview',json={'action':'task.create','object_id':task(env)['id']}).status_code==409


def test_mock_sources_empty_scope_stale_and_unavailable(env):
    with store.db() as c:
        crm = MockCRM(c,env['ids']['users']['director'])
        order = crm.get_order('PP-2611-00042')
        assert order and order['source_id'] and order['fetched_at'] and order['events']
        customer = crm.get_customer(order['client_ref'])
        assert set(customer)=={'id','display_name','kind','source_id','fetched_at','as_of','stale'}
        assert crm.get_order('PP-9999-99999') is None
        assert crm.find_interactions()==[]
        assert MockCRM(c,env['ids']['users']['operator']).get_customer(order['client_ref']) is None
    env['monkeypatch'].setenv('MOCK_CRM_FAULT','stale')
    r = env['director'].get('/api/meet/crm/orders/PP-2611-00042')
    assert r.status_code==200 and r.json()['warning']=='Данные устарели.'
    assert env['designer'].get('/api/meet/crm/orders/PP-2611-00042').status_code==404
    env['monkeypatch'].setenv('MOCK_CRM_FAULT','down')
    assert env['director'].get('/api/meet/crm/orders/PP-2611-00042').status_code==503
    assert env['admin'].post('/api/meet/integrations/check').status_code==503
    env['monkeypatch'].delenv('MOCK_CRM_FAULT')
    assert env['admin'].get('/api/meet/integrations').json()['mapped_employees']==16
    assert env['admin'].post('/api/meet/integrations/check').json()['status']=='ok'
    assert env['prod_head'].get('/api/meet/integrations').status_code==403


def test_concurrent_confirm_one_object(env):
    p = preview(env); c = env['prod_head']
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _:c.post('/api/meet/crm/confirm',json=token(p)),range(2)))
    assert all(r.status_code==200 for r in replies)
    assert sorted(r.json()['already_confirmed'] for r in replies)==[False,True]
    assert counts()==(1,1)


def test_confirmed_protocol_attachment_has_source_and_replay(env):
    t = task(env); p = preview(env,t); c = env['prod_head']
    ref = c.post('/api/meet/crm/confirm',json=token(p)).json()['external_ref']
    p = c.post('/api/meet/crm/preview',json={'action':'protocol.attach','object_id':t['meeting_id'],'entity_ref':ref})
    assert p.status_code==200,p.text
    fields = p.json()['preview']['fields']
    assert fields['items'] and all(row['quotes'] for row in fields['items'])
    r = c.post('/api/meet/crm/confirm',json=token(p.json(),'attach-protocol-key'))
    assert r.status_code==200,r.text
    assert counts()==(2,2)
    assert c.post('/api/meet/crm/confirm',json=token(p.json(),'attach-protocol-key')).json()['already_confirmed']


def test_privacy_restricted_intent_and_missing_mapping(env):
    t = task(env)
    with store.db() as c: c.execute("UPDATE tasks SET text='Проверить заявку +375291234567 test@example.invalid' WHERE id=?",(t['id'],))
    p = preview(env,t)
    assert '+375291234567' not in json.dumps(p,ensure_ascii=False)
    assert 'test@example.invalid' not in json.dumps(p,ensure_ascii=False)
    with store.db() as c: c.execute("UPDATE tasks SET text='Оплатить поставщику 500 BYN' WHERE id=?",(t['id'],))
    assert env['prod_head'].post('/api/meet/crm/preview',json={'action':'task.create','object_id':t['id']}).json()['code']=='restricted_action'
    with store.db() as c: c.execute("UPDATE tasks SET text='Проверить макет',assignee_user_id=NULL WHERE id=?",(t['id'],))
    r = env['prod_head'].post('/api/meet/crm/preview',json={'action':'task.create','object_id':t['id']})
    assert r.status_code==422 and r.json()['code']=='employee_mapping_required'
    assert counts()==(0,0)


def test_explicit_entity_links_are_scoped_and_export_rechecks_them(env):
    from meetings.connectors.entities import mentions
    assert mentions('PP-2611-00042; PP-2611-00042; client-0001; XPP-2611-00042')==[
        {'kind':'order','id':'PP-2611-00042'},{'kind':'customer','id':'client-0001'}]
    c=env['prod_head']
    mid=c.post('/api/meet/meetings',json={'title':'Проверка заказа'}).json()['meeting']['id']
    uid=c.put(f'/api/meet/meetings/{mid}/transcript',json={'text':'Марина: Денис Петров, проверь заказ PP-2611-00042 до 20 ноября.'}).json()['utterances'][0]['id']
    result=c.put(f'/api/meet/meetings/{mid}/protocol',json={'items':[{'kind':'task','text':'Проверить заказ PP-2611-00042','assignee':'Денис Петров','due':'2026-11-20','quotes':[{'utterance_id':uid}]}]}).json()
    item=result['protocol']['items'][0]
    assert item['linked_entities']==[{'kind':'order','id':'PP-2611-00042'}]
    response=c.post(f'/api/meet/meetings/{mid}/protocol/confirm',json={'item_ids':[item['id']]})
    assert response.status_code==200,response.text
    t=response.json()['created'][0]
    assert t['linked_entities']==item['linked_entities']
    p=preview(env,t)
    assert env['prod_head'].get(p['preview']['fields']['source_path']).status_code==200
    with store.db() as db: db.execute("UPDATE erp_orders SET confidentiality='secret' WHERE order_no='PP-2611-00042'")
    assert c.post('/api/meet/crm/confirm',json=token(p)).status_code==404
    assert counts()==(0,0)


def test_missing_data_and_fault_warning_in_cached_overview(env):
    c=env['prod_head'];mid=c.post('/api/meet/meetings',json={'title':'Пустой протокол'}).json()['meeting']['id']
    targets=c.get(f'/api/meet/crm/targets?meeting_id={mid}').json()['targets']
    # A head cannot see SALES deals; creating a local task is the available path.
    assert targets==[]
    env['monkeypatch'].setenv('MOCK_CRM_FAULT','stale')
    result=c.get('/api/meet/overview').json()
    assert any('Данные CRM устарели' in warning for warning in result['warnings'])
    p=preview(env)
    assert p['preview']['warning']=='Данные устарели.'
    env['monkeypatch'].setenv('MOCK_CRM_FAULT','down')
    result=c.get('/api/meet/overview').json()
    assert any('Источник CRM недоступен' in warning for warning in result['warnings'])


@pytest.mark.parametrize('status',['done','cancelled'])
def test_closed_task_is_not_recreated_as_open_crm_task(env,status):
    t=task(env)
    with store.db() as c: c.execute('UPDATE tasks SET status=? WHERE id=?',(status,t['id']))
    response=env['prod_head'].post('/api/meet/crm/preview',json={'action':'task.create','object_id':t['id']})
    assert response.status_code==422 and response.json()['code']=='task_closed'
    assert counts()==(0,0)
    assert env['prod_head'].post('/api/meet/crm/preview',json={'action':'taskXcreate','object_id':t['id']}).status_code==422
