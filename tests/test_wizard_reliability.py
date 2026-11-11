"""P1-04: wizard and version reliability on the server side. Temporary databases, no live AI, no external channels."""
import threading
import pytest
import storage
from test_track1_quick import client, create_agent, call
from services.agent_service import AgentService
from services.product_workspace import DraftInput


def put_draft(client, data, revision):
    return client.put('/api/track1/draft', json={'expected_revision': revision, 'data': data})


def step(client):
    return client.get('/api/track1/overview').json()['next_step']['code']


def preview(client, **changes):
    return client.post('/api/track1/preview', json={'business_name': 'Тест', **changes})


# ---- limits: exact boundaries accepted, one over rejected, nothing trimmed silently --------------------------------

@pytest.mark.parametrize('change', [
    {'facts': 'ф' * 3000},
    {'qa': [{'question': 'в' * 240, 'answer': 'о' * 1200, 'source': 'и' * 200}]},
    {'qa': [{'question': f'Вопрос {i}', 'answer': 'ответ'} for i in range(10)]},
])
def test_values_exactly_at_the_limit_are_accepted_untrimmed(client, change):
    response = preview(client, **change)
    assert response.status_code == 200, response.text
    knowledge = response.json()['config']['business']['knowledge']
    if 'facts' in change:
        assert knowledge['notes'] == change['facts']
    else:
        assert knowledge['qa'] == [{**q, 'source': q.get('source', '')} for q in change['qa']]


@pytest.mark.parametrize('change', [
    {'facts': 'ф' * 3001},
    {'qa': [{'question': 'в' * 241, 'answer': 'о'}]},
    {'qa': [{'question': 'в', 'answer': 'о' * 1201}]},
    {'qa': [{'question': 'в', 'answer': 'о', 'source': 'и' * 201}]},
    {'qa': [{'question': f'Вопрос {i}', 'answer': 'ответ'} for i in range(11)]},
])
def test_one_over_the_limit_is_rejected_not_cut(client, change):
    assert preview(client, **change).status_code == 422


def test_total_knowledge_limit_is_6500_in_both_directions(client):
    # facts 3000 + 3 x (question 9 + answer 1100) = 6327; a fourth item of 3 + 170 chars lands exactly on 6500.
    base = [{'question': f'Вопрос-{i:02d}', 'answer': 'о' * 1100} for i in range(3)]
    exact = {'facts': 'ф' * 3000, 'qa': base + [{'question': 'Ещё', 'answer': 'о' * 170}]}
    over = {'facts': 'ф' * 3000, 'qa': base + [{'question': 'Ещё', 'answer': 'о' * 171}]}
    assert preview(client, **exact).status_code == 200
    response = preview(client, **over)
    assert response.status_code == 422 and '6500' in response.text


# ---- draft survives incomplete / duplicated input, preview does not accept it ---------------------------------------

def test_incomplete_and_duplicate_faq_are_stored_in_draft_but_never_previewed(client):
    data = DraftInput(business_name='Тест', city='').model_dump()
    data['qa'] = [{'question': 'Цена?', 'answer': '', 'source': ''}, {'question': ' цена? ', 'answer': '50', 'source': ''}]
    saved = put_draft(client, data, 0)
    assert saved.status_code == 200
    assert client.get('/api/track1/draft').json()['data']['qa'] == data['qa']  # nothing dropped or merged
    for qa in (data['qa'], data['qa'][1:] + [{'question': 'ЦЕНА?', 'answer': '60', 'source': ''}]):
        assert preview(client, qa=qa, draft_revision=1).status_code == 422


# ---- revision conflicts: two tabs, stale preview, stale edit ---------------------------------------------------------

def test_two_tabs_second_writer_gets_409_and_first_text_is_intact(client):
    first = DraftInput(business_name='Вкладка 1', city='').model_dump()
    second = DraftInput(business_name='Вкладка 2', city='').model_dump()
    assert put_draft(client, first, 0).status_code == 200
    conflict = put_draft(client, second, 0)  # tab 2 still believes revision is 0
    assert conflict.status_code == 409
    assert client.get('/api/track1/draft').json()['data']['business_name'] == 'Вкладка 1'
    fresh = client.get('/api/track1/draft').json()
    assert put_draft(client, second, fresh['revision']).status_code == 200  # "keep mine" path: adopt revision, then write


def test_parallel_writers_with_same_revision_only_one_wins(client):
    results, gate = [], threading.Barrier(6)
    def write(i):
        data = DraftInput(business_name=f'Писатель {i}', city='').model_dump()
        gate.wait()
        results.append(put_draft(client, data, 0).status_code)
    threads = [threading.Thread(target=write, args=(i,)) for i in range(6)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert sorted(results) == [200] + [409] * 5
    assert client.get('/api/track1/draft').json()['revision'] == 1


def test_stale_preview_is_a_409_and_changed_data_is_never_confirmed(client):
    data = DraftInput(business_name='Тест', city='').model_dump()
    put_draft(client, data, 0)
    assert preview(client, city='', draft_revision=0).status_code == 409   # revision behind
    assert preview(client, city='', facts='другое', draft_revision=1).status_code == 409  # form differs from stored draft
    ok = preview(client, city='', draft_revision=1)
    assert ok.status_code == 200 and ok.json()['draft_revision'] == 1


# ---- repeat / partial confirmation never duplicates the assistant ----------------------------------------------------

def test_activation_failure_after_save_can_be_retried_without_a_second_assistant(client, monkeypatch):
    candidate = preview(client, city='').json()
    confirm = {k: candidate[k] for k in ('candidate_id', 'review_token')}
    saved = client.post('/api/track1/agents', json=confirm).json()
    real = AgentService.activate
    monkeypatch.setattr(AgentService, 'activate', lambda self, agent_id: (_ for _ in ()).throw(ValueError('сбой активации')))
    assert client.post('/api/agents/' + saved['id'] + '/activate').status_code == 422
    overview = client.get('/api/track1/overview').json()
    assert overview['counts']['assistants'] == 1 and overview['next_step']['code'] == 'activate'
    monkeypatch.setattr(AgentService, 'activate', real)
    again = client.post('/api/track1/agents', json=confirm).json()   # user presses "confirm" again
    assert again['id'] == saved['id']
    assert client.post('/api/agents/' + saved['id'] + '/activate').status_code == 200
    assert client.get('/api/track1/overview').json()['counts']['assistants'] == 1


def test_double_click_confirm_in_parallel_creates_one_assistant(client):
    candidate = preview(client, city='').json()
    confirm = {k: candidate[k] for k in ('candidate_id', 'review_token')}
    ids, gate = [], threading.Barrier(5)
    def go():
        gate.wait(); ids.append(client.post('/api/track1/agents', json=confirm).json()['id'])
    threads = [threading.Thread(target=go) for _ in range(5)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert len(set(ids)) == 1 and client.get('/api/track1/overview').json()['counts']['assistants'] == 1


# ---- versions: edits apply to new conversations only; draft/import never activates ---------------------------------------

def test_edit_changes_new_conversations_but_open_one_keeps_its_snapshot(client):
    agent = create_agent(client, business_name='Версия 1', city='')
    old = client.post('/api/conversations', json={'agent_id': agent}).json()
    candidate = client.post('/api/track1/preview', json={'business_name': 'Версия 2', 'city': '', 'agent_id': agent}).json()
    assert client.post('/api/track1/agents', json={k: candidate[k] for k in ('candidate_id', 'review_token')}).status_code == 200
    new = client.post('/api/conversations', json={'agent_id': agent}).json()
    assert 'Версия 1' in old['greeting'] and 'Версия 2' in new['greeting']
    assert 'Версия 1' in storage.get_interaction(old['interaction_id'])['agent_config']['greeting']  # snapshot, not live config


def test_draft_or_imported_config_alone_never_creates_or_activates_an_assistant(client):
    data = DraftInput(business_name='Импорт из старого макета', city='', role='support').model_dump()
    assert put_draft(client, data, 0).status_code == 200
    overview = client.get('/api/track1/overview').json()
    assert overview['counts']['assistants'] == 0 and overview['agents'] == [] and overview['next_step']['code'] == 'finish_draft'
    assert client.get('/api/agents').json().get('agents', client.get('/api/agents').json()) is not None
    with storage.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM agents WHERE source='track1'").fetchone()[0] == 0


# ---- overview: next step follows the real state ------------------------------------------------------------------------

def test_overview_next_step_follows_state_changes(client):
    assert step(client) == 'create'
    data = DraftInput(business_name='Тест', city='').model_dump()
    put_draft(client, data, 0)
    assert step(client) == 'finish_draft'                       # typed, not confirmed
    candidate = preview(client, city='', draft_revision=1).json()
    saved = client.post('/api/track1/agents', json={k: candidate[k] for k in ('candidate_id', 'review_token')}).json()
    put_draft(client, {**data, 'agent_id': saved['id']}, 1)
    assert step(client) == 'activate'                           # saved, not selected for web test
    client.post('/api/agents/' + saved['id'] + '/activate')
    assert step(client) == 'test_web'
    client.post('/api/conversations', json={'agent_id': saved['id']})
    assert step(client) == 'improve_knowledge'
    put_draft(client, {**data, 'agent_id': saved['id'], 'facts': 'Правка не подтверждена'}, 2)
    overview = client.get('/api/track1/overview').json()
    assert overview['next_step'] == {'code': 'confirm_changes', 'agent_id': saved['id']}
    assert overview['counts']['assistants'] == 1                # the unconfirmed edit changed nothing live
