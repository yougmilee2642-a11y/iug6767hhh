from uuid import uuid4
from email.parser import BytesParser
from email.policy import default
from meetings import store
from meetings.local_outbox import write
from tests.test_track3_briefing import env


def confirmed(env):
    client=env['prod_head'];mid=env['ids']['meetings']['delay']
    r=client.post('/api/meet/assistant/actions/preview',json={'kind':'task','meeting_id':mid,'text':'Ручное подтверждённое поручение проверить картон'})
    assert r.status_code==200,r.text
    r=client.post('/api/meet/assistant/actions/confirm',json={'confirmation_id':r.json()['confirmation_id'],'idempotency_key':str(uuid4())})
    assert r.status_code==200,r.text
    return client,mid


def test_protocol_export_confirmed_only_and_scoped(env):
    client,mid=confirmed(env)
    for format in ('md','html'):
        r=client.get(f'/api/meet/meetings/{mid}/protocol/export',params={'format':format})
        assert r.status_code==200,r.text
        assert 'Ручное подтверждённое поручение' in r.text and 'Подтвердил' in r.text
    assert env['designer'].get(f'/api/meet/meetings/{mid}/protocol/export').status_code==404


def test_mail_cancel_confirm_replay_permission_and_files(env,tmp_path,monkeypatch):
    client,mid=confirmed(env);route=f'/api/meet/meetings/{mid}/protocol/mail'
    recipients=[env['ids']['users']['prod_head']]
    p=client.post(route+'/preview',json={'recipient_ids':recipients});assert p.status_code==200,p.text
    old=p.json()['confirmation_id'];client.post(f'/api/meet/confirmations/{old}/cancel')
    data={'confirmation_id':old,'idempotency_key':str(uuid4())}
    assert client.post(route+'/confirm',json=data).status_code==409
    data['confirmation_id']=client.post(route+'/preview',json={'recipient_ids':recipients}).json()['confirmation_id']
    r=client.post(route+'/confirm',json=data);assert r.status_code==200,r.text
    assert client.post(route+'/confirm',json=data).json()['already_confirmed']
    oid=r.json()['outbox_ids'][0]
    response=client.get(f'/api/meet/protocol-outbox/{oid}/download.eml');assert response.status_code==200,response.text
    message=BytesParser(policy=default).parsebytes(response.content)
    assert message['To'].endswith('@demo.invalid') and 'Ручное' in message.get_body().get_content()
    monkeypatch.setenv('MEETINGS_OUTBOX_DIR',str(tmp_path/'outbox'))
    with store.db() as c:
        assert write(c)>=1
        assert write(c)==0
    assert list((tmp_path/'outbox').glob('protocol-*.eml'))
    assert env['designer'].get(f'/api/meet/protocol-outbox/{oid}/download.eml').status_code==404
