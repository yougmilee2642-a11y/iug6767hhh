from datetime import datetime,timedelta,timezone
from uuid import uuid4
import json
import pytest
from meetings import notifications,retention,store
from tests.test_track3_briefing import env,business_counts


def token(client,route,**kwargs):
    result=client.post(route+'/preview',**kwargs);assert result.status_code==200,result.text
    return {'confirmation_id':result.json()['confirmation_id'],'idempotency_key':str(uuid4())}


def test_csrf_origin_header_and_security_headers(env):
    r=env['director'].post('/api/meet/assistant/ask',json={'text':'Брифинг'},headers={'Origin':'https://untrusted.invalid'})
    assert r.status_code==403 and r.json()['code']=='csrf_denied' and r.headers['X-Request-ID']
    r=env['director'].post('/api/meet/assistant/ask',json={'text':'Брифинг'},headers={'Origin':'http://testserver'})
    assert r.status_code==403
    r=env['director'].post('/api/meet/assistant/ask',json={'text':'Брифинг'},headers={'Origin':'http://testserver','X-Focus-Request':'1'})
    assert r.status_code==200,r.text
    assert r.headers['X-Content-Type-Options']=='nosniff'
    assert 'https:' not in r.headers['Content-Security-Policy']
    with store.db() as c:assert c.execute("SELECT 1 FROM audit WHERE action='csrf_denied' AND result='denied'").fetchone()


def test_rate_limit_is_durable_and_does_not_report_success(env,monkeypatch):
    monkeypatch.setenv('MEETINGS_RATE_LIMIT_LOGIN','2')
    with store.db() as c:c.execute('DELETE FROM security_limits')
    for _ in range(2):assert env['director'].post('/api/meet/login',json={'login':'invalid','password':'bad'}).status_code==401
    r=env['director'].post('/api/meet/login',json={'login':'invalid','password':'bad'})
    assert r.status_code==429 and r.headers['Retry-After']=='60'
    store.reset_cache()
    assert env['director'].post('/api/meet/login',json={'login':'invalid','password':'bad'}).status_code==429


def test_notification_tick_scoped_idempotent_no_task_mutation_and_opt_in(env):
    stamp=datetime(2026,11,20,10,tzinfo=timezone.utc)
    before=business_counts()
    uid=env['ids']['users']['operator']
    with store.write_tx() as c:
        created=notifications.tick(c,stamp);assert created>0
        assert notifications.tick(c,stamp)==0
        assert c.execute('SELECT count(*) FROM notification_outbox').fetchone()[0]==0
    assert business_counts()==before
    mine=env['operator'].get('/api/meet/notifications').json()
    assert mine['notifications'] and all(row['user_id']==uid for row in mine['notifications'])
    notice=mine['notifications'][0]
    assert env['director'].post(f"/api/meet/notifications/{notice['id']}/read").status_code==404
    assert env['operator'].post(f"/api/meet/notifications/{notice['id']}/read").status_code==200
    draft=token(env['operator'],'/api/meet/notification-settings',json={'email_enabled':True})
    assert env['operator'].post('/api/meet/notification-settings/confirm',json=draft).status_code==200
    with store.write_tx() as c:
        notifications.tick(c,stamp+timedelta(days=1))
        rows=[r[0] for r in c.execute('SELECT payload FROM notification_outbox')]
        assert rows and all('Петров' not in x and '+375' not in x and '@' not in x for x in rows)


def test_policy_preview_cancel_repeat_and_role(env):
    client=env['admin'];p={'audio_after_confirm':False,'transcript_days':90,'chat_days':14,'audit_days':365}
    assert env['director'].get('/api/meet/retention').status_code==403
    d=token(client,'/api/meet/retention/policy',json=p)
    client.post('/api/meet/confirmations/'+d['confirmation_id']+'/cancel')
    assert client.post('/api/meet/retention/policy/confirm',json=d).status_code==409
    d=token(client,'/api/meet/retention/policy',json=p)
    assert client.post('/api/meet/retention/policy/confirm',json=d).status_code==200
    assert client.post('/api/meet/retention/policy/confirm',json=d).json()['already_confirmed']
    assert client.get('/api/meet/retention').json()['policy']['chat_days']==14


def test_retention_deletes_expired_chat_and_original_quotes_keeps_tasks(env):
    result=env['director'].post('/api/meet/assistant/ask',json={'text':'Что просрочено?'});assert result.status_code==200,result.text
    before=business_counts()['tasks']
    with store.write_tx() as c:
        c.execute("UPDATE assistant_messages SET created_at='2000-01-01T00:00:00+00:00'")
        c.execute("UPDATE assistant_evidence SET created_at='2000-01-01T00:00:00+00:00'")
        counts=retention.clean(c,datetime(2028,1,1,tzinfo=timezone.utc))
        assert counts['assistant_messages'] and counts['utterances']
        assert not c.execute('SELECT 1 FROM assistant_messages').fetchone()
        assert not c.execute('SELECT 1 FROM utterances').fetchone()
        assert c.execute('SELECT count(*) FROM tasks').fetchone()[0]==before
        assert all(json.loads(r[0])['kind']=='expired_source' for r in c.execute('SELECT source_quote FROM tasks'))


def test_test_cleanup_marker_cancel_confirmation_and_repeat(env):
    admin=env['admin'];before=business_counts()
    d=token(admin,'/api/meet/retention/cleanup')
    admin.post('/api/meet/confirmations/'+d['confirmation_id']+'/cancel')
    after=business_counts()
    assert {k:v for k,v in after.items() if k!='confirmations'}=={k:v for k,v in before.items() if k!='confirmations'}
    d=token(admin,'/api/meet/retention/cleanup')
    result=admin.post('/api/meet/retention/cleanup/confirm',json=d)
    assert result.status_code==200,result.text
    assert admin.post('/api/meet/retention/cleanup/confirm',json=d).json()['already_confirmed']
    assert business_counts()['tasks']==0 and business_counts()['documents']==0
    assert admin.get('/api/meet/retention').status_code==200


def test_cleanup_unmarked_database_refused(env):
    from pathlib import Path
    marker=Path(str(store.db_path().resolve())+'.track3.json');marker.unlink()
    assert env['admin'].post('/api/meet/retention/cleanup/preview').status_code==403


def test_user_deletion_requires_admin_and_erases_owned_data(env):
    user=env['prod_head'];admin=env['admin'];uid=env['ids']['users']['prod_head']
    request=user.post('/api/meet/privacy/delete-request').json()['request_id']
    route='/api/meet/privacy/delete-requests/'+str(request)
    assert user.post(route+'/preview').status_code==403
    d=token(admin,route)
    result=admin.post(route+'/confirm',json=d)
    assert result.status_code==200,result.text
    assert admin.post(route+'/confirm',json=d).json()['already_confirmed']
    assert user.get('/api/meet/me').status_code==401
    with store.db() as c:
        row=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
        assert row['name']=='Удалённый пользователь' and row['active']==0
        assert not c.execute('SELECT 1 FROM meetings WHERE owner_id=?',(uid,)).fetchone()
        assert not c.execute('SELECT 1 FROM documents WHERE owner_id=?',(uid,)).fetchone()
        assert c.execute("SELECT 1 FROM audit WHERE action='data_deletion_confirmed'").fetchone()


def test_comments_scope_and_history_after_confirm(env):
    client=env['prod_head'];tid=client.get('/api/meet/tasks').json()['tasks'][0]['id']
    r=client.post(f'/api/meet/tasks/{tid}/comments',json={'text':'Нужно уточнить срок у владельца.'})
    assert r.status_code==200,r.text
    assert env['designer'].get(f'/api/meet/tasks/{tid}/comments').status_code==404
    p=client.post(f'/api/meet/tasks/{tid}/preview',json={'changes':{'priority':'urgent'}})
    assert p.status_code==200,p.text
    r=client.post(f'/api/meet/tasks/{tid}/confirm',json={'confirmation_id':p.json()['confirmation_id'],'idempotency_key':str(uuid4())})
    assert r.status_code==200,r.text
    result=client.get(f'/api/meet/tasks/{tid}/comments').json()
    assert result['comments'] and result['history']
