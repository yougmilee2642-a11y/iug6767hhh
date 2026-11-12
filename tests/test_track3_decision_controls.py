from tests.test_track3_task_controls import env
from meetings import store


def decision(env,share=False):
    client = env['prod_head']
    payload = {'title':'Решение о запасе картона'}
    if share: payload['access_user_ids']=[env['ids']['users']['operator']]
    mid = client.post('/api/meet/meetings',json=payload).json()['meeting']['id']
    uid = client.put(f'/api/meet/meetings/{mid}/transcript',json={'text':'Марина: Решили проверить резерв картона перед запуском Premium.'}).json()['utterances'][0]['id']
    item = client.put(f'/api/meet/meetings/{mid}/protocol',json={'items':[{'kind':'decision','text':'Проверить резерв картона перед запуском Premium','quotes':[{'utterance_id':uid}]}]}).json()['protocol']['items'][0]
    return mid,item['id'],uid


def test_decision_control_preview_cancel_confirm_repeat_and_kpi(env):
    client = env['prod_head']; mid,pid,uid = decision(env,share=True)
    path = f'/api/meet/decisions/{pid}'
    body = {'owner_user_id':env['ids']['users']['operator'],'due':'2026-11-10','status':'open'}
    preview = client.post(path+'/preview',json=body); assert preview.status_code==200,preview.text
    cid = preview.json()['confirmation_id']
    assert client.get('/api/meet/decisions').json()['decisions']==[]
    client.post(f'/api/meet/confirmations/{cid}/cancel')
    assert client.post(path+'/confirm',json={'confirmation_id':cid,'idempotency_key':'cancelled-decision'}).status_code==409
    cid = client.post(path+'/preview',json=body).json()['confirmation_id']
    token = {'confirmation_id':cid,'idempotency_key':'one-decision-control'}
    first = client.post(path+'/confirm',json=token); assert first.status_code==200,first.text
    assert client.post(path+'/confirm',json=token).json()['already_confirmed']
    rows = client.get('/api/meet/decisions').json()['decisions']; assert len(rows)==1
    assert rows[0]['source_quote']['utterance_id']==uid and rows[0]['source_status']=='verified'
    assert len(env['operator'].get('/api/meet/decisions').json()['decisions'])==1
    assert env['operator'].post(path+'/preview',json=body).status_code==403
    response = client.get('/api/meet/overview',params={'as_of':'2026-11-11T12:00:00+00:00'}).json()
    metrics = {m['key']:m for m in response['metrics']}
    assert metrics['open_decisions']['value']==1 and metrics['overdue_decisions']['value']==1
    for cutoff,wanted in [('2026-11-10T20:59:59+00:00',0),('2026-11-10T21:00:00+00:00',1)]:
        point = client.get('/api/meet/overview',params={'as_of':cutoff}).json()
        assert {m['key']:m['value'] for m in point['metrics']}['overdue_decisions']==wanted
    source = metrics['overdue_decisions']['source']
    opened = client.get('/api/meet/sources/metric/'+source['id'])
    assert opened.status_code==200 and opened.json()['data']['decisions'][0]['protocol_item_id']==pid
    # A confirmed source point remains immutable through the ordinary protocol editor.
    edited = client.put(f'/api/meet/meetings/{mid}/protocol',json={'items':[{'id':pid,'kind':'decision','text':'Другое решение'}]})
    assert edited.status_code==200
    assert next(item for item in edited.json()['protocol']['items'] if item['id']==pid)['text']=='Проверить резерв картона перед запуском Premium'
    cid = client.post(path+'/preview',json={**body,'status':'done'}).json()['confirmation_id']
    assert client.post(path+'/confirm',json={'confirmation_id':cid,'idempotency_key':'finish-decision-control'}).status_code==200
    after = client.get('/api/meet/overview',params={'as_of':'2026-11-11T12:00:00+00:00'}).json()
    assert {m['key']:m['value'] for m in after['metrics']}['overdue_decisions']==0
    assert client.get('/api/meet/sources/metric/'+source['id']).status_code==404
    store.reset_cache()
    assert client.get('/api/meet/decisions').json()['decisions'][0]['status']=='done'


def test_decision_basis_and_permission_rechecked_at_confirm(env):
    client = env['director']; mid,pid,uid = decision(env)
    path = f'/api/meet/decisions/{pid}'
    body = {'owner_user_id':env['ids']['users']['prod_head'],'due':None,'status':'open'}
    cid = client.post(path+'/preview',json=body).json()['confirmation_id']
    with store.db() as c:
        c.execute("UPDATE meetings SET confidentiality='secret' WHERE id=?",(mid,))
        c.execute('DELETE FROM meeting_access WHERE meeting_id=?',(mid,))
    response = client.post(path+'/confirm',json={'confirmation_id':cid,'idempotency_key':'revoked-decision-source'})
    assert response.status_code==404
    with store.db() as c: assert c.execute('SELECT COUNT(*) FROM decision_controls').fetchone()[0]==0


def test_missing_quote_unknown_deadline_and_changed_basis(env):
    client = env['prod_head']; mid,pid,uid = decision(env)
    body = {'owner_user_id':None,'due':None,'status':'open'}
    path = f'/api/meet/decisions/{pid}'
    cid = client.post(path+'/preview',json=body).json()['confirmation_id']
    with store.db() as c: c.execute("UPDATE utterances SET text='Решение изменено человеком' WHERE id=?",(int(uid[1:]),))
    assert client.post(path+'/confirm',json={'confirmation_id':cid,'idempotency_key':'changed-decision-basis'}).status_code==409
    assert client.post(path+'/preview',json=body).status_code==422
    mid,pid,uid = decision(env)
    path = f'/api/meet/decisions/{pid}'
    cid = client.post(path+'/preview',json=body).json()['confirmation_id']
    assert client.post(path+'/confirm',json={'confirmation_id':cid,'idempotency_key':'unknown-decision-fields'}).status_code==200
    row = client.get('/api/meet/decisions').json()['decisions'][0]
    assert row['due'] is None and row['owner_user_id'] is None
