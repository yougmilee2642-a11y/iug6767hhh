"""Server policy, pre-context filtering, delegation revocation and role separation."""
from datetime import datetime, timedelta, timezone
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from meetings import access, llm, store
from meetings.api import install
from scripts.track3.seed_fotoprint import seed


@pytest.fixture(scope='module')
def env(tmp_path_factory):
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv('MEETINGS_DB_PATH', str(tmp_path_factory.mktemp('policy') / 'roles.db'))
        patch.setenv('MEETINGS_SECRET', 'policy-test-secret')
        ids = seed(__import__('os').environ['MEETINGS_DB_PATH'])
        app = FastAPI(); install(app)
        clients = {}
        for login in ids['users']:
            client = TestClient(app)
            assert client.post('/api/meet/login', json={'login': login, 'password': login + '-demo'}).status_code == 200
            clients[login] = client
        yield {'ids': ids, **clients}
        llm.set_llm(None); store.reset_cache()


ROLES = [('director','director'), ('prod_head','head'), ('mod_lead','lead'), ('operator','employee'),
         ('designer','contractor'), ('admin','admin'), ('auditor','auditor')]


@pytest.mark.parametrize('login,level', ROLES)
@pytest.mark.parametrize('kind', ['document', 'meeting', 'metric'])
@pytest.mark.parametrize('classification', ['public', 'internal', 'department', 'confidential', 'secret'])
@pytest.mark.parametrize('shared', [False, True])
def test_classification_matrix_matches_sql(env, login, level, kind, classification, shared):
    with store.db() as c:
        actor = access.load_user(c, env['ids']['users'][login])
        department = actor['department_id']
        owner = env['ids']['users']['fin_head']
        obj = {'owner_id': owner, 'department_id': department, 'confidentiality': classification, '_shared': shared}
        expected = level not in ('admin', 'auditor') and (shared or
                   classification == 'public' or classification == 'internal' and level != 'contractor' or
                   classification == 'department' and level in ('director','head','lead') or
                   classification == 'confidential' and level == 'director')
        for model in (False, True):
            wanted = expected and not (model and classification == 'secret')
            assert access.decide(actor, 'model.read' if model else kind + '.read', obj).allowed == wanted
            # A real SQL subquery exercises classification BEFORE selecting content.
            table, acl, fk = access.TABLES[kind]
            test_id = 8000001
            if shared:
                # Existing real source as the ACL carrier; alias row supplies tested attributes.
                existing = c.execute(f'SELECT id FROM {table} LIMIT 1').fetchone()[0]
                added = c.execute(f'INSERT OR IGNORE INTO {acl} VALUES (?,?)', (existing, actor['id'])).rowcount
                test_id = existing
            sql, params = access.predicate(c, actor['id'], kind, 'o', model=model)
            actual = c.execute('SELECT 1 FROM (SELECT ? AS id,? AS owner_id,? AS department_id,? AS confidentiality) o WHERE ' + sql,
                               [test_id, owner, department, classification, *params]).fetchone() is not None
            assert actual == wanted
            if shared and added:
                c.execute(f'DELETE FROM {acl} WHERE {fk}=? AND user_id=?', (existing, actor['id']))


@pytest.mark.parametrize('login,level', ROLES)
@pytest.mark.parametrize('action', ['meeting.read','document.read','metric.read','model.read','meetings.edit',
                                   'transcript.edit','protocol.confirm','tasks.change','documents.share','crm.write',
                                   'audit.read','retention.manage'])
def test_action_matrix_never_turns_technical_roles_into_content_readers(env, login, level, action):
    expected = {
        'director': {'meeting.read','document.read','metric.read','model.read','meetings.edit','transcript.edit','protocol.confirm','tasks.change','documents.share','crm.write','audit.read'},
        'head': {'meeting.read','document.read','metric.read','model.read','meetings.edit','transcript.edit','protocol.confirm','tasks.change','documents.share','crm.write','audit.read'},
        'lead': {'meeting.read','document.read','metric.read','model.read','meetings.edit','transcript.edit','protocol.confirm','tasks.change','documents.share'},
        'employee': {'meeting.read','document.read','metric.read','model.read','transcript.edit','tasks.change','documents.share'},
        'contractor': {'meeting.read','document.read','metric.read','model.read','documents.share'},
        'admin': set(), 'auditor': set()}
    with store.db() as c:
        actor = access.load_user(c, env['ids']['users'][login])
        obj = {'owner_id': actor['id'], 'department_id': actor['department_id'], 'confidentiality': 'confidential', 'assignee_user_id': actor['id']}
        assert access.decide(actor, action, obj).allowed == (action in expected[level])


def test_http_admin_auditor_and_foreign_department_denials_are_audited(env):
    did = env['ids']['documents']['v2_budget']; mid = env['ids']['meetings']['delay']
    for login in ['admin','auditor','designer']:
        client = env[login]
        assert client.get(f'/api/meet/documents/{did}/download').status_code == 404
        assert client.get(f'/api/meet/meetings/{mid}').status_code == 404
    assert env['admin'].get('/api/meet/admin/users').status_code == 200
    assert env['director'].get('/api/meet/admin/users').status_code == 403
    assert env['prod_head'].get(f'/api/meet/documents/{did}').status_code == 404
    with store.db() as c:
        events = c.execute("SELECT * FROM audit WHERE result='denied'").fetchall()
        assert len(events) == 8
        assert all('48000' not in row['details'] and 'Бюджет' not in row['details'] for row in events)


class RecordingDouble:
    model = 'scripted-access-double'
    def __init__(self): self.calls = []
    def json(self, system, user, schema, predict=1500):
        self.calls.append((system, user))
        return {'excerpt_ids': []}


def test_designer_budget_and_secret_never_reach_model(env):
    double = RecordingDouble(); llm.set_llm(double)
    response = env['designer'].post('/api/meet/qa', json={'question': 'Какой бюджет акции Premium?'})
    assert response.status_code == 200 and response.json()['status'] == 'insufficient_data'
    assert all('48000' not in prompt and '650000' not in prompt for _, prompt in double.calls)
    with store.db() as c:
        secret = c.execute("SELECT id,title FROM documents WHERE confidentiality='secret'").fetchone()
        users = [r[0] for r in c.execute('SELECT id FROM users')]
        for actor in users:
            assert not store.can_read_document(c, actor, secret['id'], model=True)
    double.calls.clear()
    response = env['director'].post('/api/meet/qa', json={'question': 'Каков фонд оплаты труда?'})
    assert response.status_code == 200 and response.json()['status'] == 'insufficient_data'
    assert 'закрыт для ассистента' in response.json()['answer']
    assert double.calls == []
    assert env['director'].get(f"/api/meet/documents/{secret['id']}/download").status_code == 200
    llm.set_llm(None)


def test_employee_only_changes_own_task_status(env):
    client = env['operator']
    tasks = client.get('/api/meet/tasks').json()['tasks']; assert tasks
    tid = tasks[0]['id']
    assert client.post(f'/api/meet/tasks/{tid}/preview', json={'changes': {'due': '2026-12-01'}}).status_code == 403
    preview = client.post(f'/api/meet/tasks/{tid}/preview', json={'changes': {'status': 'done'}})
    assert preview.status_code == 200, preview.text
    cid = preview.json()['confirmation_id']
    assert client.post(f'/api/meet/confirmations/{cid}/cancel').status_code == 200
    assert client.post(f'/api/meet/tasks/{tid}/confirm', json={'confirmation_id': cid, 'idempotency_key': 'cancel-test'}).status_code == 409
    # An invited employee cannot edit somebody else's transcript.
    mid = env['ids']['meetings']['delay']
    assert client.put(f'/api/meet/meetings/{mid}/transcript', json={'text': 'Нельзя менять'}).status_code == 403


def test_delegation_confirm_expiry_and_scope(env):
    now = datetime.now(timezone.utc)
    with store.db() as c:
        fin = c.execute("SELECT id FROM departments WHERE code='FIN'").fetchone()[0]
    data = {'to_user': env['ids']['users']['operator'], 'department_id': fin,
            'starts_at': (now - timedelta(minutes=5)).isoformat(), 'ends_at': (now + timedelta(days=1)).isoformat(), 'reason': 'Синтетический отпуск'}
    cid = env['fin_head'].post('/api/meet/delegations', json=data).json()['confirmation_id']
    assert env['operator'].get('/api/meet/me').json()['delegations'] == []
    payload = {'confirmation_id': cid, 'idempotency_key': 'grant-demo'}
    confirmed = env['fin_head'].post('/api/meet/delegations/confirm', json=payload)
    assert confirmed.status_code == 200, confirmed.text
    assert env['fin_head'].post('/api/meet/delegations/confirm', json=payload).json()['already_confirmed']
    me = env['operator'].get('/api/meet/me').json()
    assert len(me['delegations']) == 1 and 'meetings.create' in me['capabilities']
    assert env['operator'].post('/api/meet/meetings', json={'title':'Вне делегированного отдела'}).status_code == 403
    own_task = env['operator'].get('/api/meet/tasks').json()['tasks'][0]
    assert env['operator'].post(f"/api/meet/tasks/{own_task['id']}/preview", json={'changes':{'due':'2026-12-01'}}).status_code == 403
    # Department delegation opens department content, never explicit confidential/secret.
    did = env['ids']['documents']['v2_budget']
    assert env['operator'].get(f'/api/meet/documents/{did}').status_code == 404
    assert env['prod_head'].post('/api/meet/delegations', json=data).status_code == 403
    with store.db() as c:
        c.execute('UPDATE delegations SET ends_at=? WHERE id=?', ((now - timedelta(seconds=1)).isoformat(), confirmed.json()['delegation_id']))
    me = env['operator'].get('/api/meet/me').json()
    assert me['delegations'] == [] and 'meetings.create' not in me['capabilities']


def test_admin_user_preview_cancel_and_immediate_deactivation(env):
    uid = env['ids']['users']['sales_head']
    preview = env['admin'].post('/api/meet/admin/users', json={'user_id': uid, 'active': False}).json()
    assert env['sales_head'].get('/api/meet/me').status_code == 200
    cid = preview['confirmation_id']
    env['admin'].post(f'/api/meet/confirmations/{cid}/cancel')
    payload = {'confirmation_id': cid, 'idempotency_key': 'deactivate-cancel'}
    assert env['admin'].post('/api/meet/admin/users/confirm', json=payload).status_code == 409
    cid = env['admin'].post('/api/meet/admin/users', json={'user_id': uid, 'active': False}).json()['confirmation_id']
    payload = {'confirmation_id': cid, 'idempotency_key': 'deactivate'}
    assert env['admin'].post('/api/meet/admin/users/confirm', json=payload).status_code == 200
    assert env['sales_head'].get('/api/meet/me').status_code == 401
    assert env['sales_head'].post('/api/meet/login', json={'login': 'sales_head','password':'sales_head-demo'}).status_code == 401


def test_demo_roles_only_when_enabled_and_auditor_all_scope(env):
    with pytest.MonkeyPatch.context() as patch:
        patch.delenv('MEETINGS_DEMO', raising=False)
        assert env['director'].get('/api/meet/demo-profiles').json() == {'enabled':False,'users':[]}
        patch.setenv('MEETINGS_DEMO', '1')
        assert len(env['director'].get('/api/meet/demo-profiles').json()['users']) >= 14
    data = env['auditor'].get('/api/meet/audit').json()
    assert data['scope'] == 'all' and data['events']
    assert env['prod_head'].get('/api/meet/audit').json()['scope'] == 'department'
