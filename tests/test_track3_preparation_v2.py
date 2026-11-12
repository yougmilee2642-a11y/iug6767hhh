from tests.test_track3_task_controls import env
from meetings import llm, store
from tests.test_privacy_filter import BoundaryDouble


def create_source(client,title,department_id=None):
    payload = {'title':title}
    if department_id: payload['department_id'] = department_id
    response = client.post('/api/meet/meetings',json=payload); assert response.status_code==200,response.text
    mid = response.json()['meeting']['id']
    response = client.put(f'/api/meet/meetings/{mid}/transcript',json={'text':'Марина: Денис Петров, проверь картон до 20 ноября.\nДенис: Хватит ли картона на Premium?'}); assert response.status_code==200
    utterances = response.json()['utterances']
    items = [{'kind':'task','text':'Проверить дополнительный картон','assignee':'Денис Петров','due':'2026-11-20',
              'quotes':[{'utterance_id':utterances[0]['id']}]},
             {'kind':'open_question','text':'Хватит ли картона на Premium?', 'quotes':[{'utterance_id':utterances[1]['id']}]}]
    response = client.put(f'/api/meet/meetings/{mid}/protocol',json={'items':items}); assert response.status_code==200,response.text
    pid = next(i['id'] for i in response.json()['protocol']['items'] if i['kind']=='task')
    response = client.post(f'/api/meet/meetings/{mid}/protocol/confirm',json={'item_ids':[pid]}); assert response.status_code==200,response.text
    return mid,response.json()['created'][0]['id']


def test_department_context_independent_of_followup_chain_and_employee_scope(env):
    client = env['prod_head']; mid,tid = create_source(client,'Другая производственная встреча')
    target = env['ids']['meetings']['delay']
    response = client.get(f'/api/meet/meetings/{target}'); assert response.status_code==200
    context = response.json()['followup']
    assert tid in [t['id'] for t in context['open_tasks']]
    assert context['previous_questions'][0]['text']=='Хватит ли картона на Premium?'
    source = context['previous_questions'][0]['sources'][0]
    assert client.get('/api/meet/utterances/'+source['id']).status_code==200
    metrics = {m['key']:m for m in context['kpi_context']['metrics']}
    assert metrics['on_time_orders']['value']==97.6
    assert metrics['on_time_orders']['numerator']==488 and metrics['on_time_orders']['denominator']==500
    for metric in metrics.values():
        for source in metric['sources']: assert client.get('/api/meet/sources/metric/'+source['id']).status_code==200
    employee = env['operator'].get(f'/api/meet/meetings/{target}').json()['followup']
    assert tid not in [t['id'] for t in employee['open_tasks']]
    assert employee['previous_questions']==[]


def test_director_preparation_keeps_department_context_and_no_model_for_context(env):
    director = env['director']
    with store.db() as c: fin = c.execute("SELECT id FROM departments WHERE code='FIN'").fetchone()[0]
    foreign,tid = create_source(director,'Финансовый источник без доступа отдела',fin)
    target = env['ids']['meetings']['delay']
    llm.set_llm(BoundaryDouble())
    try:
        response = director.post(f'/api/meet/meetings/{target}/prepare')
        assert response.status_code==200,response.text
        prep = response.json()['prep']
        assert tid not in [t['id'] for t in prep['open_tasks']]
        assert prep['kpi_context']['metrics']
    finally: llm.set_llm(None)


def test_unknown_owner_suggestion_is_labelled_and_never_written(env):
    client = env['prod_head']; task = client.get('/api/meet/tasks').json()['tasks'][0]
    preview = client.post(f"/api/meet/tasks/{task['id']}/preview",json={'changes':{'assignee':None}}).json()
    response = client.post(f"/api/meet/tasks/{task['id']}/confirm",json={'confirmation_id':preview['confirmation_id'],'idempotency_key':'clear-owner-demo'})
    assert response.status_code==200
    saved = next(t for t in client.get('/api/meet/tasks').json()['tasks'] if t['id']==task['id'])
    assert saved['assignee'] is None and saved['assignee_user_id'] is None
    assert saved['assignee_suggestion']['status']=='assumption'
    with store.db() as c:
        row = c.execute('SELECT assignee,assignee_user_id FROM tasks WHERE id=?',(task['id'],)).fetchone()
        assert row['assignee'] is None and row['assignee_user_id'] is None
