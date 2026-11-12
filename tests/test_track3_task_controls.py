"""Task metadata, uncertainty filters and source links remain human-confirmed."""
import json
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from meetings import store
from meetings.api import install
from scripts.track3.seed_fotoprint import seed


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('MEETINGS_DB_PATH', str(tmp_path/'tasks.db'))
    monkeypatch.setenv('MEETINGS_SECRET','task-test-secret')
    ids = seed(str(tmp_path/'tasks.db')); app = FastAPI(); install(app)
    clients = {}
    for user in ['director','prod_head','operator','mod_lead']:
        client = TestClient(app)
        assert client.post('/api/meet/login',json={'login':user,'password':user+'-demo'}).status_code == 200
        clients[user] = client
    yield {'ids':ids,**clients}
    store.reset_cache()


def first_task(client):
    return next(task for task in client.get('/api/meet/tasks').json()['tasks'] if task['status']=='open')


def confirm(client, task, changes, key='change-task-once'):
    preview = client.post(f"/api/meet/tasks/{task['id']}/preview",json={'changes':changes})
    assert preview.status_code == 200,preview.text
    token = {'confirmation_id':preview.json()['confirmation_id'],'idempotency_key':key}
    response = client.post(f"/api/meet/tasks/{task['id']}/confirm",json=token)
    assert response.status_code == 200,response.text
    return response.json(),token


def test_priority_entities_cancel_confirm_and_restart(env):
    client = env['prod_head']; task = first_task(client)
    links = [{'kind':'order','id':'PP-2611-00042'}, {'kind':'document','id':str(env['ids']['documents']['v2_quality'])}]
    preview = client.post(f"/api/meet/tasks/{task['id']}/preview",json={'changes':{'priority':'urgent','linked_entities':links}}).json()
    assert preview['preview']['after']['linked_entities'] == links
    assert first_task(client)['priority']=='normal'
    client.post(f"/api/meet/confirmations/{preview['confirmation_id']}/cancel")
    rejected = client.post(f"/api/meet/tasks/{task['id']}/confirm",json={'confirmation_id':preview['confirmation_id'],'idempotency_key':'cancel-metadata'})
    assert rejected.status_code == 409
    changed,token = confirm(client,task,{'priority':'urgent','linked_entities':links,'status':'blocked'})
    assert changed['task']['priority']=='urgent' and changed['task']['linked_entities']==links
    assert changed['task']['source_quote'] == task['source_quote']
    assert client.post(f"/api/meet/tasks/{task['id']}/confirm",json=token).json()['already_confirmed']
    store.reset_cache()
    saved = next(t for t in client.get('/api/meet/tasks').json()['tasks'] if t['id']==task['id'])
    assert saved['status']=='blocked' and saved['linked_entities']==links
    assert client.get(f"/api/meet/meetings/{saved['meeting_id']}").status_code==200
    assert client.get(f"/api/meet/utterances/{saved['source_quote']['utterance_id']}").status_code==200


def test_missing_filters_counts_and_cancelled_task_not_overdue(env):
    client = env['prod_head']
    data = client.get('/api/meet/tasks',params={'missing':'due'}).json()
    assert len(data['tasks'])==1 and data['counts']['missing_due']==1
    assert client.get('/api/meet/tasks',params={'missing':'assignee'}).json()['tasks']==[]
    task = first_task(client)
    confirm(client,task,{'assignee':None,'due':None})
    missing = client.get('/api/meet/tasks',params={'missing':'either'}).json()
    assert missing['counts']['missing_assignee']==1 and missing['counts']['missing_due']==2
    assert len(missing['tasks'])==2
    # An overdue cancelled task is closed, rather than inflating open/late counters.
    remaining = next(t for t in client.get('/api/meet/tasks').json()['tasks'] if t['due'] and t['status']=='open')
    before = client.get('/api/meet/overview',params={'as_of':'2026-11-11T12:00:00+00:00'}).json()
    confirm(client,remaining,{'status':'cancelled'},key='cancel-actual-task')
    after = client.get('/api/meet/overview',params={'as_of':'2026-11-11T12:00:00+00:00'}).json()
    metrics = lambda value:{m['key']:m['value'] for m in value['metrics']}
    assert metrics(after)['overdue_tasks']==metrics(before)['overdue_tasks']-1
    assert metrics(after)['open_tasks']==metrics(before)['open_tasks']-1
    mid = env['ids']['meetings']['delay']
    followup = client.get(f'/api/meet/meetings/{mid}').json()['followup']['open_tasks']
    assert remaining['id'] not in [t['id'] for t in followup]


def test_employee_cannot_change_priority_and_foreign_links_are_denied(env):
    employee = env['operator']; task = first_task(employee)
    assert employee.post(f"/api/meet/tasks/{task['id']}/preview",json={'changes':{'priority':'high'}}).status_code==403
    head = env['prod_head']
    private = env['ids']['documents']['v2_budget']
    response = head.post(f"/api/meet/tasks/{task['id']}/preview",json={'changes':{'linked_entities':[{'kind':'document','id':str(private)}]}})
    assert response.status_code==404
    response = head.post(f"/api/meet/tasks/{task['id']}/preview",json={'changes':{'linked_entities':[{'kind':'customer','id':'client-0001'}]}})
    assert response.status_code==404
    assert head.post(f"/api/meet/tasks/{task['id']}/preview",json={'changes':{'external_ref':'forged'}}).status_code==422


def test_link_access_rechecked_after_preview_and_assignee_id_is_stable(env):
    head = env['prod_head']; task = first_task(head)
    chosen = env['ids']['users']['prod_head']
    changed,_ = confirm(head,task,{'assignee_user_id':chosen})
    assert changed['task']['assignee']=='Марина Зелёнова' and changed['task']['assignee_user_id']==chosen
    doc = env['ids']['documents']['v2_quality']
    preview = head.post(f"/api/meet/tasks/{task['id']}/preview",json={'changes':{'linked_entities':[{'kind':'document','id':str(doc)}]}}).json()
    with store.db() as c:
        c.execute("UPDATE documents SET owner_id=?,confidentiality='secret' WHERE id=?",(env['ids']['users']['director'],doc))
        c.execute('DELETE FROM document_access WHERE document_id=?',(doc,))
    response = head.post(f"/api/meet/tasks/{task['id']}/confirm",json={'confirmation_id':preview['confirmation_id'],'idempotency_key':'rights-recheck'})
    assert response.status_code==404
    saved = next(t for t in head.get('/api/meet/tasks').json()['tasks'] if t['id']==task['id'])
    assert saved['linked_entities']==[]


def test_lead_cannot_confirm_assignment_to_foreign_department(env):
    lead = env['mod_lead']
    mid = lead.post('/api/meet/meetings',json={'title':'Собственная встреча модерации'}).json()['meeting']['id']
    uid = lead.put(f'/api/meet/meetings/{mid}/transcript',json={'text':'Елена: Денис Петров, проверь макет до 20 ноября.'}).json()['utterances'][0]['id']
    items = lead.put(f'/api/meet/meetings/{mid}/protocol',json={'items':[{'kind':'task','text':'Проверить макет','assignee':'Денис Петров','due':'2026-11-20','quotes':[{'utterance_id':uid}]}]}).json()['protocol']['items']
    response = lead.post(f'/api/meet/meetings/{mid}/protocol/confirm',json={'item_ids':[items[0]['id']]})
    assert response.status_code==403
    with store.db() as c:
        assert c.execute('SELECT COUNT(*) FROM tasks WHERE meeting_id=?',(mid,)).fetchone()[0]==0
