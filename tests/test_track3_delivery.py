"""External delivery boundaries use injected transports only, no real accounts."""
from datetime import datetime,timedelta,timezone
import json,logging
import httpx
import pytest
from meetings import store,notifications,notification_delivery as delivery,smtp_delivery
from tests.test_track3_briefing import env


@pytest.fixture
def enabled(env,monkeypatch):
    monkeypatch.setenv('CALLWISE_LOCAL_ONLY','false');monkeypatch.setenv('CALLWISE_CLOUD_INTEGRATIONS_ENABLED','true')
    monkeypatch.setenv('MEETINGS_NOTIFICATION_DISPATCH_ENABLED','1');monkeypatch.setenv('MEETINGS_PUBLIC_URL','https://focus.example.invalid')
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','123456:synthetic_test_token_only')
    monkeypatch.setenv('MEETINGS_TELEGRAM_RECIPIENTS',json.dumps({str(env['ids']['users']['operator']):'1234567'}))
    return env


def settings(env,**values):
    client=env['operator'];p=client.post('/api/meet/notification-settings/preview',json=values);assert p.status_code==200,p.text
    token={'confirmation_id':p.json()['confirmation_id'],'idempotency_key':'settings-'+p.json()['confirmation_id']}
    r=client.post('/api/meet/notification-settings/confirm',json=token);assert r.status_code==200,r.text
    return r


def emit(env,key='synthetic'):
    with store.write_tx() as c:
        return notifications.emit(c,env['ids']['users']['operator'],'test','briefing','today','Внутренний учебный текст',key)


def test_default_closed_and_old_local_queue_cannot_start_after_configuration(enabled,monkeypatch):
    monkeypatch.setenv('MEETINGS_NOTIFICATION_DISPATCH_ENABLED','0')
    settings(enabled,telegram_enabled=True);emit(enabled)
    assert delivery.dispatch(telegram_transport=httpx.MockTransport(lambda r:pytest.fail('default must not send')))==0
    monkeypatch.setenv('MEETINGS_NOTIFICATION_DISPATCH_ENABLED','1')
    assert delivery.dispatch(telegram_transport=httpx.MockTransport(lambda r:pytest.fail('old unreviewed destination')))==0
    with store.db() as c:assert c.execute('SELECT status FROM notification_outbox').fetchone()[0]=='cancelled'


def test_telegram_review_generic_payload_commit_before_http_and_once(enabled):
    settings(enabled,telegram_enabled=True);emit(enabled);calls=[]
    def respond(request):
        with store.db() as c:assert c.execute('SELECT status FROM notification_outbox').fetchone()[0]=='sending'
        body=json.loads(request.content);calls.append(body)
        assert body['chat_id']==1234567 and body['link_preview_options']=={'is_disabled':True}
        assert body['text']==delivery.TEXT+'\nhttps://focus.example.invalid/meetings'
        assert 'Внутренний' not in body['text']
        return httpx.Response(200,json={'ok':True,'result':{'message_id':1}})
    transport=httpx.MockTransport(respond)
    assert delivery.dispatch(telegram_transport=transport)==1 and len(calls)==1
    assert delivery.dispatch(telegram_transport=transport)==0 and len(calls)==1


def test_destination_change_rejects_confirm_and_old_queue(enabled,monkeypatch):
    client=enabled['operator'];p=client.post('/api/meet/notification-settings/preview',json={'telegram_enabled':True}).json()
    monkeypatch.setenv('MEETINGS_TELEGRAM_RECIPIENTS',json.dumps({str(enabled['ids']['users']['operator']):'999999'}))
    assert client.post('/api/meet/notification-settings/confirm',json={'confirmation_id':p['confirmation_id'],'idempotency_key':'changed-destination'}).status_code==409
    settings(enabled,telegram_enabled=True);emit(enabled)
    monkeypatch.setenv('MEETINGS_TELEGRAM_RECIPIENTS','{}')
    assert delivery.dispatch(telegram_transport=httpx.MockTransport(lambda r:pytest.fail('changed destination')))==0


def test_timeout_interrupt_read_and_role_revocation_do_not_resend(enabled):
    settings(enabled,telegram_enabled=True);nid=emit(enabled);calls=[]
    def timeout(request):calls.append(request);raise httpx.ReadTimeout('synthetic')
    assert delivery.dispatch(telegram_transport=httpx.MockTransport(timeout))==0
    assert delivery.dispatch(telegram_transport=httpx.MockTransport(timeout))==0 and len(calls)==1
    with store.write_tx() as c:
        assert c.execute('SELECT status FROM notification_outbox').fetchone()[0]=='uncertain'
        notifications.emit(c,enabled['ids']['users']['operator'],'test','briefing','today','x','interrupted')
        c.execute("UPDATE notification_outbox SET status='sending' WHERE notification_id!=?",(nid,))
    assert delivery.dispatch(telegram_transport=httpx.MockTransport(lambda r:pytest.fail('interrupted send')))==0
    nid=emit(enabled,'read');enabled['operator'].post(f'/api/meet/notifications/{nid}/read')
    assert delivery.dispatch(telegram_transport=httpx.MockTransport(lambda r:pytest.fail('read notice')))==0
    emit(enabled,'role')
    with store.db() as c:c.execute("UPDATE users SET level='admin' WHERE id=?",(enabled['ids']['users']['operator'],))
    assert delivery.dispatch(telegram_transport=httpx.MockTransport(lambda r:pytest.fail('revoked role')))==0


def test_bitrix_transport_and_token_logs_are_redacted(enabled,monkeypatch,caplog):
    monkeypatch.setenv('MEETINGS_BITRIX_ENABLED','1');monkeypatch.setenv('MEETINGS_BITRIX_WEBHOOK','https://portal.example.invalid/rest/1/synthetic_token_only/')
    with store.db() as c:
        c.execute("INSERT OR REPLACE INTO user_external_ids(user_id,connector,external_id) VALUES (?,'bitrix24','777')",(enabled['ids']['users']['operator'],))
    settings(enabled,bitrix_enabled=True);emit(enabled)
    def respond(request):
        assert request.url.path.endswith('im.notify.personal.add.json')
        assert json.loads(request.content)=={'USER_ID':'777','MESSAGE':delivery.TEXT+'\nhttps://focus.example.invalid/meetings'}
        return httpx.Response(200,json={'result':1})
    assert delivery.dispatch(bitrix_transport=httpx.MockTransport(respond))==1
    from services.telegram_bot import TokenRedaction
    record=logging.LogRecord('httpx',20,'',1,'POST %s',('https://api.telegram.org/bot123456:synthetic_test_token_only/sendMessage',),None)
    TokenRedaction().filter(record);assert 'synthetic_test_token_only' not in record.getMessage()


def invitation(env):
    client=env['director'];uid=env['ids']['users']['operator']
    mid=client.post('/api/meet/meetings',json={'title':'Учебное приглашение SMTP','access_user_ids':[uid]}).json()['meeting']['id']
    p=client.post('/api/meet/calendar/preview',json={'meeting_id':mid,'participant_ids':[uid],'start_at':(datetime.now(timezone.utc)+timedelta(days=80)).replace(hour=12,minute=0,second=0,microsecond=0).isoformat(),'duration_minutes':30})
    assert p.status_code==200,p.text
    r=client.post('/api/meet/calendar/confirm',json={'confirmation_id':p.json()['confirmation_id'],'idempotency_key':'smtp-local-invitation'});assert r.status_code==200,r.text
    return r.json()['invitations'][0]['id'],mid


def smtp_config(env,monkeypatch):
    monkeypatch.setenv('CALLWISE_LOCAL_ONLY','false');monkeypatch.setenv('CALLWISE_CLOUD_INTEGRATIONS_ENABLED','true');monkeypatch.setenv('MEETINGS_SMTP_ENABLED','1')
    for name,value in {'HOST':'smtp.example.invalid','USERNAME':'synthetic','PASSWORD':'synthetic_only','FROM':'focus@example.invalid','PORT':'465'}.items():monkeypatch.setenv('MEETINGS_SMTP_'+name,value)
    monkeypatch.setenv('MEETINGS_EMAIL_RECIPIENTS',json.dumps({str(env['ids']['users']['operator']):'operator@example.invalid'}))


def smtp_preview(env,ident):
    p=env['director'].post(f'/api/meet/calendar/outbox/{ident}/smtp/preview');assert p.status_code==200,p.text
    return {'confirmation_id':p.json()['confirmation_id'],'idempotency_key':'smtp-'+p.json()['confirmation_id']}


def test_smtp_default_off_cancel_repeat_exact_recipient_ics_and_commit(env,monkeypatch):
    ident,mid=invitation(env);route=f'/api/meet/calendar/outbox/{ident}/smtp'
    monkeypatch.setenv('MEETINGS_SMTP_ENABLED','0')
    assert env['director'].post(route+'/preview').status_code==503
    smtp_config(env,monkeypatch);token=smtp_preview(env,ident)
    env['director'].post('/api/meet/confirmations/'+token['confirmation_id']+'/cancel')
    assert env['director'].post(route+'/confirm',json=token).status_code==409
    token=smtp_preview(env,ident);r=env['director'].post(route+'/confirm',json=token);assert r.status_code==200,r.text
    assert env['director'].post(route+'/confirm',json=token).json()['already_confirmed']
    calls=[]
    def send(mail,config):
        with store.db() as c:assert c.execute('SELECT status FROM smtp_outbox').fetchone()[0]=='sending'
        calls.append(mail);assert mail['To']=='operator@example.invalid' and mail['From']=='focus@example.invalid'
        assert [p.get_filename() for p in mail.iter_attachments()]==['invitation.ics']
    assert smtp_delivery.dispatch(sender=send)==1 and len(calls)==1
    assert smtp_delivery.dispatch(sender=send)==0 and len(calls)==1
    assert env['operator'].get('/api/meet/smtp-outbox').json()['outbox']==[]
    assert env['operator'].post(route+'/preview').status_code in (403,404)


def test_smtp_changed_destination_or_acl_cancels_and_timeout_is_terminal(env,monkeypatch):
    ident,mid=invitation(env);smtp_config(env,monkeypatch);route=f'/api/meet/calendar/outbox/{ident}/smtp'
    token=smtp_preview(env,ident)
    monkeypatch.setenv('MEETINGS_EMAIL_RECIPIENTS',json.dumps({str(env['ids']['users']['operator']):'other@example.invalid'}))
    assert env['director'].post(route+'/confirm',json=token).status_code==409
    token=smtp_preview(env,ident);assert env['director'].post(route+'/confirm',json=token).status_code==200
    with store.db() as c:c.execute("UPDATE meetings SET confidentiality='secret' WHERE id=?",(mid,))
    assert smtp_delivery.dispatch(sender=lambda *a:pytest.fail('revoked secret'))==0
    with store.db() as c:
        assert c.execute('SELECT status FROM smtp_outbox').fetchone()[0]=='cancelled'
        c.execute("UPDATE meetings SET confidentiality='department' WHERE id=?",(mid,))
        # Model a distinct newly-confirmed invitation; never requeue the old one.
        c.execute('DELETE FROM smtp_outbox')
    token=smtp_preview(env,ident);env['director'].post(route+'/confirm',json=token)
    calls=[]
    def timeout(*args):calls.append(1);raise TimeoutError('not logged')
    assert smtp_delivery.dispatch(sender=timeout)==0
    assert smtp_delivery.dispatch(sender=timeout)==0 and calls==[1]
    with store.db() as c:assert c.execute('SELECT status FROM smtp_outbox').fetchone()[0]=='uncertain'
