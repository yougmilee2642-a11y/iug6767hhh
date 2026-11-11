import hashlib
import hmac
import json
import time
from urllib.parse import urlencode, urlsplit, parse_qs
import httpx
import pytest
from fastapi.testclient import TestClient
import app
import storage
from services import telegram_store as store
from services.telegram_bot import TelegramClient, TelegramError, TelegramWorker, process_update, send_next, miniapp_url
from services.telegram_identity import verify_init_data
from services import owner_access
from test_track1_quick import IntakeProvider, create_agent, call


FAKE_TOKEN='999999:synthetic-test-only'


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'DB_PATH',tmp_path/'test.sqlite')
    monkeypatch.setattr(storage,'DATA_DIR',tmp_path)
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN',FAKE_TOKEN)
    monkeypatch.setenv('TELEGRAM_ENABLED','true')
    monkeypatch.setattr(app,'get_provider',IntakeProvider)
    storage.initialize_db();store.initialize()
    with store.session() as db:
        db.execute('INSERT INTO tg_runtime (bot_key,username,status,heartbeat) VALUES (?,?,?,?)',(store.bot_key(),'callwise_qa_bot','ready',time.time()))
    return TestClient(app.app)


class FakeBot:
    def __init__(self,error=None): self.calls=[];self.error=error
    def call(self,method,**payload):
        self.calls.append((method,payload))
        if self.error: raise self.error
        return {'message_id':42}


def update(text,user_id=100):
    return {'update_id':1,'message':{'chat':{'type':'private','id':user_id},'from':{'id':user_id,'first_name':'Синтетический'},'text':text}}


def bind(client,aid,user_id=100):
    link=client.post('/api/telegram/link',json={'agent_id':aid}).json()
    code=parse_qs(urlsplit(link['url']).query)['start'][0]
    process_update(FakeBot(),update('/start '+code,user_id))
    assert client.post('/api/telegram/link/approve',json={'agent_id':aid,'link_id':link['link_id']}).status_code==200
    return link,code


def signed(user_id=100,when=None,token=FAKE_TOKEN):
    data={'auth_date':str(int(time.time() if when is None else when)), 'query_id':'qa',
          'user':json.dumps({'id':user_id,'first_name':'Синтетический'},ensure_ascii=False)}
    secret=hmac.new(b'WebAppData',token.encode(),hashlib.sha256).digest()
    data['hash']=hmac.new(secret,'\n'.join(f'{k}={v}' for k,v in sorted(data.items())).encode(),hashlib.sha256).hexdigest()
    return urlencode(data)


def test_link_requires_start_then_owner_confirmation(client):
    aid=create_agent(client)
    link=client.post('/api/telegram/link',json={'agent_id':aid}).json()
    payload={'agent_id':aid,'link_id':link['link_id']}
    assert client.post('/api/telegram/link/approve',json=payload).status_code==409
    code=parse_qs(urlsplit(link['url']).query)['start'][0]
    assert store.stage_link(code,100,'QA')
    assert not store.stage_link(code,200,'Hijack')
    assert not store.status(aid)['connected']
    assert client.post('/api/telegram/link/status',json=payload).json()['pending_recipient']['chat_id']==100
    assert client.post('/api/telegram/link/approve',json=payload).status_code==200
    assert client.post('/api/telegram/link/approve',json=payload).status_code==409


def test_expired_links_and_wrong_agent(client):
    aid=create_agent(client);other=create_agent(client)
    link=store.create_link(aid)
    assert client.post('/api/telegram/link/approve',json={'agent_id':other,'link_id':link['link_id']}).status_code==409
    with store.session() as db: db.execute('UPDATE tg_links SET expires=0')
    assert client.post('/api/telegram/link/status',json={'agent_id':aid,'link_id':link['link_id']}).status_code==409


def test_outbox_consent_idempotency_and_delivery(client):
    aid=create_agent(client);bind(client,aid)
    cid=client.post('/api/conversations',json={'agent_id':aid}).json()['interaction_id']
    call(client,cid,'Алексей');call(client,cid,'+375290000000');call(client,cid,'Создание сайта')
    assert store.delivery(cid)['status']=='not_queued'
    reply=call(client,cid,'Да','confirm')
    assert reply['interaction']['telegram_delivery']['status']=='pending'
    call(client,cid,'Да','confirm')
    bot=FakeBot()
    assert send_next(bot,store.bot_key())
    assert not send_next(bot,store.bot_key())
    assert len(bot.calls)==1 and bot.calls[0][1]['chat_id']==100
    assert 'parse_mode' not in bot.calls[0][1]
    item=client.get('/api/applications').json()['items'][0]
    assert item['telegram_delivery']['status']=='sent'
    assert 'чтение не подтверждено' in item['brief_summary']


def queue_callback(client):
    aid=create_agent(client);bind(client,aid)
    cid=client.post('/api/conversations',json={'agent_id':aid}).json()['interaction_id']
    for text in ['Алексей','+375290000000','Создание сайта','Да']: call(client,cid,text)
    return aid,cid


def test_disconnect_cancels_pending_without_sending(client):
    aid,cid=queue_callback(client)
    assert client.post('/api/telegram/disconnect',json={'agent_id':aid}).status_code==200
    bot=FakeBot();assert not send_next(bot,store.bot_key())
    assert store.delivery(cid)['status']=='cancelled' and not bot.calls


@pytest.mark.parametrize('category,expected',[('rate_limit','retry'),('forbidden','failed'),('unknown_delivery','unknown')])
def test_delivery_error_states(client,category,expected):
    _,cid=queue_callback(client)
    bot=FakeBot(TelegramError(category,60));send_next(bot,store.bot_key())
    assert store.delivery(cid)['status']==expected
    assert not send_next(bot,store.bot_key())


def test_new_token_does_not_use_old_recipient(client,monkeypatch):
    aid,cid=queue_callback(client)
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','another-token')
    assert not store.status(aid)['connected']
    assert not send_next(FakeBot(),store.bot_key())


def test_chat_registration_confirm_profile_and_delete(client):
    bot=FakeBot()
    for text in ['/register','Алексей','QA Company']: process_update(bot,update(text))
    assert store.user_profile(100) is None
    process_update(bot,update('Да'))
    assert store.user_profile(100)['business_name']=='QA Company'
    process_update(bot,update('/profile',200))
    assert 'Профиля пока нет' in bot.calls[-1][1]['text']
    process_update(bot,update('/confirm_delete'))
    assert store.user_profile(100)
    process_update(bot,update('/delete_profile'));process_update(bot,update('/confirm_delete'))
    assert store.user_profile(100) is None


def test_group_cannot_register_or_bind(client):
    event=update('/register');event['message']['chat']['type']='group'
    bot=FakeBot();process_update(bot,event)
    assert not bot.calls


def test_miniapp_valid_registration_and_user_isolation(client):
    raw=signed()
    assert client.post('/api/miniapp/profile',json={'init_data':raw}).status_code==200
    payload={'init_data':raw,'display_name':'Алексей','business_name':'QA','consent':True}
    assert client.post('/api/miniapp/register',json=payload).json()['profile']['telegram_id']==100
    assert client.post('/api/miniapp/profile',json={'init_data':signed(200)}).json()['profile'] is None
    payload['telegram_id']=200
    assert client.post('/api/miniapp/register',json=payload).status_code==422


@pytest.mark.parametrize('raw',[lambda:signed(when=time.time()-601),lambda:signed(when=time.time()+60),lambda:signed(token='wrong'),lambda:signed()+'&user=bad',lambda:'user=bad'])
def test_miniapp_rejects_bad_data(client,raw):
    assert client.post('/api/miniapp/profile',json={'init_data':raw()}).status_code==401


def test_miniapp_requires_consent_and_cannot_read_owner_data(client,monkeypatch):
    monkeypatch.setenv('CALLWISE_OWNER_PASSWORD','synthetic-owner-password')
    assert client.get('/api/applications').status_code==401
    assert client.get('/api/agents').status_code==401
    assert client.post('/api/miniapp/register',json={'init_data':signed(),'display_name':'QA','business_name':'QA','consent':False}).status_code==422
    assert client.post('/api/miniapp/register',json={'init_data':signed(),'display_name':'QA','business_name':'QA','consent':True}).status_code==200
    assert client.get('/api/agents').status_code==401


def test_telegram_client_redacts_error_and_honors_retry_after(client):
    transport=httpx.MockTransport(lambda request:httpx.Response(429,json={'ok':False,'error_code':429,'description':FAKE_TOKEN,'parameters':{'retry_after':19}}))
    with pytest.raises(TelegramError) as error: TelegramClient(FAKE_TOKEN,transport).call('sendMessage')
    assert str(error.value)=='rate_limit' and error.value.retry_after==19
    assert FAKE_TOKEN not in str(error.value)


def test_https_miniapp_button_and_invalid_local_url(client,monkeypatch):
    monkeypatch.setenv('TELEGRAM_MINIAPP_URL','http://127.0.0.1:8000/miniapp')
    assert miniapp_url() is None
    monkeypatch.setenv('TELEGRAM_MINIAPP_URL','https://demo.example/miniapp')
    bot=FakeBot();process_update(bot,update('/register'))
    assert bot.calls[-1][1]['reply_markup']['inline_keyboard'][0][0]['web_app']['url']=='https://demo.example/miniapp'


def test_owner_cookie_login_logout_and_csrf(client,monkeypatch):
    monkeypatch.setenv('CALLWISE_OWNER_PASSWORD','synthetic-owner-password')
    with owner_access._lock: owner_access._attempts.clear()
    assert client.get('/api/config').status_code==401
    assert client.post('/api/access/login',json={'password':'bad'}).status_code==401
    response=client.post('/api/access/login',json={'password':'synthetic-owner-password'})
    assert response.status_code==200 and 'HttpOnly' in response.headers['set-cookie']
    assert client.get('/api/config').status_code==200
    assert client.post('/api/telegram/link',json={'agent_id':'bad'},headers={'origin':'https://evil.example'}).status_code==403
    client.post('/api/access/logout')
    assert client.get('/api/config').status_code==401


def test_owner_gate_rejects_remote_passwordless_and_invalid_host(client,monkeypatch):
    monkeypatch.setenv('PUBLIC_ORIGIN','https://demo.example')
    assert TestClient(app.app,base_url='https://demo.example').get('/api/config').status_code==503
    assert client.get('/api/config',headers={'host':'evil.example'}).status_code==400


def test_owner_login_throttling(client,monkeypatch):
    monkeypatch.setenv('CALLWISE_OWNER_PASSWORD','synthetic-owner-password')
    with owner_access._lock: owner_access._attempts.clear()
    for _ in range(5): assert client.post('/api/access/login',json={'password':'bad'}).status_code==401
    assert client.post('/api/access/login',json={'password':'bad'}).status_code==429
    with owner_access._lock: owner_access._attempts.clear()


def test_worker_polls_and_preserves_offset(client,monkeypatch):
    from services import telegram_bot
    worker=TelegramWorker()
    class Bot:
        def __init__(self): self.offsets=[]
        def call(self,method,**payload):
            if method=='getMe': return {'username':'qa_bot'}
            if method=='getWebhookInfo': return {'url':''}
            if method=='getUpdates':
                self.offsets.append(payload['offset']);worker.stop_event.set()
                return [{'update_id':10,'message':{}}]
    bot=Bot();monkeypatch.setattr(telegram_bot,'TelegramClient',lambda:bot)
    worker.run()
    with store.session() as db: assert db.execute('SELECT offset FROM tg_runtime').fetchone()[0]==11
    second=TelegramWorker();bot.call=lambda method,**kwargs: {'username':'qa_bot'} if method=='getMe' else {'url':'https://existing.example'}
    monkeypatch.setattr(telegram_bot,'TelegramClient',lambda:bot)
    second.run()
    assert store.status('')['error']=='webhook_active'


def test_invalid_hash_encoding_is_rejected(client):
    raw=signed();pairs=parse_qs(raw);pairs['hash']=['ё'*64]
    assert client.post('/api/miniapp/profile',json={'init_data':urlencode({k:v[0] for k,v in pairs.items()})}).status_code==401


def test_miniapp_allows_telegram_navigation_but_not_cross_site_posts(client):
    assert client.get('/miniapp',headers={'sec-fetch-site':'cross-site'}).status_code==200
    assert client.get('/api/config',headers={'sec-fetch-site':'cross-site'}).status_code==403
    assert client.post('/api/miniapp/profile',json={'init_data':signed()},headers={'sec-fetch-site':'cross-site'}).status_code==403
