"""Long-polling bot + outbox worker. Sanitized errors, no token/body logging."""
import json
import logging
import re
import os
import threading
import time
import uuid
from urllib.parse import urlsplit
import httpx
from services import telegram_store as store

class TokenRedaction(logging.Filter):
    def filter(self,record):
        def redact(value):
            if isinstance(value,(int,float)) or value is None:return value
            text=str(value)
            return re.sub(r'(/bot)[0-9]+:[A-Za-z0-9_-]+',r'\1[redacted]',text) if '/bot' in text else value
        if isinstance(record.args,tuple):record.args=tuple(redact(v) for v in record.args)
        elif isinstance(record.args,dict):record.args={k:redact(v) for k,v in record.args.items()}
        record.msg=redact(record.msg)
        return True


for _logger in ('httpx','httpcore'):
    logging.getLogger(_logger).addFilter(TokenRedaction())
logging.getLogger('httpx').setLevel(logging.WARNING)


class TelegramError(Exception):
    def __init__(self, category, retry_after=0):
        self.category, self.retry_after = category, retry_after
        super().__init__(category)


class TelegramClient:
    def __init__(self, token=None, transport=None):
        self._token = token or os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
        self.transport = transport

    def call(self, method, **payload):
        from providers.local_settings import local_only, LocalAIError
        if local_only(): raise LocalAIError('cloud_disabled')
        try:
            with httpx.Client(timeout=15, transport=self.transport, trust_env=False, follow_redirects=False) as client:
                response = client.post(f'https://api.telegram.org/bot{self._token}/{method}', json=payload)
            data = response.json()
        except (httpx.HTTPError, ValueError):
            # The remote side may have accepted sendMessage before a read timeout.
            raise TelegramError('unknown_delivery') from None
        if not isinstance(data, dict) or not data.get('ok'):
            code = data.get('error_code', response.status_code) if isinstance(data, dict) else response.status_code
            if code == 429:
                delay = (data.get('parameters') or {}).get('retry_after', 30)
                raise TelegramError('rate_limit', min(86400, max(1, int(delay))))
            if isinstance(code,int) and code >= 500: raise TelegramError('unknown_delivery')
            raise TelegramError({401:'invalid_token',403:'forbidden',409:'polling_conflict'}.get(code, 'rejected'))
        return data.get('result')


def miniapp_url():
    url = os.getenv('TELEGRAM_MINIAPP_URL', '').strip()
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.hostname in {'localhost','127.0.0.1','::1'} or parsed.username or parsed.password:
        return None
    return url


def message(client, chat_id, text, **kwargs):
    kwargs.setdefault('link_preview_options',{'is_disabled':True})
    return client.call('sendMessage', chat_id=chat_id, text=text[:3500], **kwargs)


def registration_message(client, peer, user_id, text):
    """Working chat fallback while a public HTTPS Mini App has not been deployed."""
    store.initialize()
    with store.session() as db:
        draft = db.execute('SELECT step,payload,expires FROM tg_registration WHERE telegram_id=?', (user_id,)).fetchone()
    if text in {'/register','/start'}:
        url = miniapp_url()
        if url:
            message(client, peer, 'Регистрация Callwise. Откройте приложение и заполните профиль. Регистрация не даёт доступа к чужим агентам.',
                    reply_markup={'inline_keyboard': [[{'text':'Открыть регистрацию','web_app':{'url':url}}]]})
            return
        with store.session() as db:
            db.execute('INSERT INTO tg_registration VALUES (?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET step=excluded.step,payload=excluded.payload,expires=excluded.expires',
                       (user_id,'name','{}',time.time()+1800))
        message(client, peer, 'Регистрация Callwise: сохраним Telegram ID, ваше имя и название бизнеса. Доступ к агентам отдельно. /cancel — отмена. Как к вам обращаться?')
        return
    if text == '/cancel':
        with store.session() as db:
            db.execute('DELETE FROM tg_registration WHERE telegram_id=?', (user_id,))
        message(client, peer, 'Регистрация отменена.')
        return
    if text == '/delete_profile':
        with store.session() as db:
            db.execute('INSERT INTO tg_registration VALUES (?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET step=excluded.step,payload=excluded.payload,expires=excluded.expires',
                       (user_id,'delete','{}',time.time()+300))
        message(client, peer, 'Удалим только регистрационный профиль: имя, название бизнеса и Telegram ID в профиле. Это необратимо; обращения и привязки уведомлений не удалятся. Для подтверждения в течение 5 минут: /confirm_delete. Для отмены: /cancel.')
        return
    if text == '/confirm_delete':
        if not draft or draft['step'] != 'delete' or draft['expires'] <= time.time():
            message(client,peer,'Сначала /delete_profile, затем подтвердите в течение 5 минут.'); return
        with store.session() as db:
            db.execute('DELETE FROM tg_users WHERE telegram_id=?',(user_id,))
            db.execute('DELETE FROM tg_registration WHERE telegram_id=?',(user_id,))
        message(client,peer,'Регистрационный профиль удалён без возможности восстановления. Привязки уведомлений и обращения не изменены.')
        return
    if text == '/profile':
        profile = store.user_profile(user_id)
        message(client, peer, f"Профиль: {profile['display_name']}\nБизнес: {profile['business_name']}" if profile else 'Профиля пока нет. /register — регистрация.')
        return
    if not draft or draft['expires'] <= time.time():
        message(client, peer, 'Callwise: /register — регистрация, /profile — ваш профиль. Привязка уведомлений выполняется в веб-мастере.')
        return
    if draft['step'] == 'delete':
        message(client,peer,'Подтверждение удаления: /confirm_delete. Отмена: /cancel.'); return
    data = json.loads(draft['payload'])
    if draft['step'] == 'consent':
        if text.casefold() != 'да':
            message(client, peer, 'Для сохранения профиля ответьте «Да» или /cancel.'); return
        store.register_user(user_id, data['display_name'], data['business_name'])
        message(client, peer, 'Профиль зарегистрирован. Это пока регистрация, не подключение телефонии или доступ к чужим агентам.')
        return
    if text.startswith('/') or not 2 <= len(text) <= 100:
        message(client, peer, 'Введите от 2 до 100 символов или /cancel.'); return
    if draft['step'] == 'name':
        data['display_name'] = text
        step, reply = 'business', 'Как называется ваш бизнес?'
    else:
        data['business_name'] = text
        step, reply = 'consent', f"Имя: {data['display_name']}\nБизнес: {text}\nСогласны сохранить эти данные и Telegram ID в Callwise? Ответьте «Да» или /cancel."
    with store.session() as db:
        db.execute('UPDATE tg_registration SET step=?,payload=? WHERE telegram_id=?', (step,json.dumps(data,ensure_ascii=False),user_id))
    message(client, peer, reply)


def process_update(client, update):
    msg = update.get('message') or {}
    chat, user = msg.get('chat') or {}, msg.get('from') or {}
    text = msg.get('text', '').strip()
    if chat.get('type') != 'private' or user.get('is_bot') or not isinstance(user.get('id'), int) or chat.get('id') != user['id'] or not text:
        return
    if text.startswith('/start '):
        code = text.split(' ',1)[1]
        label = ' '.join(str(user.get(k,'')) for k in ('first_name','last_name')).strip() or 'Пользователь Telegram'
        if user.get('username'): label += ' @' + user['username']
        staged = store.stage_link(code, chat['id'], label)
        message(client, chat['id'], 'Получатель найден. Вернитесь в Callwise, проверьте имя и подтвердите привязку.' if staged else 'Ссылка недействительна или уже использована. Создайте новую в Callwise.')
        return
    registration_message(client, chat['id'], user['id'], text)


def send_next(client, key):
    with store.session() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT * FROM tg_outbox WHERE bot_key=? AND status IN ('pending','retry') AND next_try<=? ORDER BY next_try LIMIT 1", (key,time.time())).fetchone()
        if not row: return False
        row = dict(row)
        binding = db.execute('SELECT 1 FROM tg_bindings WHERE agent_id=? AND bot_key=? AND chat_id=?', (row['agent_id'],key,row['chat_id'])).fetchone()
        if not binding:
            db.execute("UPDATE tg_outbox SET status='cancelled',error='recipient_changed' WHERE id=?", (row['id'],)); return True
        db.execute("UPDATE tg_outbox SET status='sending',attempts=attempts+1,next_try=? WHERE id=?", (time.time(),row['id']))
    try:
        from services.customer_safety import accepted
        from storage import get_interaction
        state = get_interaction(row['interaction_id'])
        if state is not None and not accepted(state):
            with store.session() as db:
                db.execute("UPDATE tg_outbox SET status='cancelled',error='privacy_withdrawn' WHERE id=?", (row['id'],))
            return True
        result = message(client, row['chat_id'], row['text'])
        message_id = result.get('message_id') if isinstance(result, dict) else None
        status, error, next_try = ('sent',None,0) if message_id else ('unknown','unknown_delivery',0)
    except TelegramError as exc:
        error, message_id, next_try = exc.category, None, 0
        if exc.category == 'rate_limit' and row['attempts'] < 4:
            status, next_try = 'retry', time.time()+exc.retry_after
        else:
            status = 'unknown' if exc.category == 'unknown_delivery' else 'failed'
    with store.session() as db:
        db.execute('UPDATE tg_outbox SET status=?,error=?,next_try=?,message_id=? WHERE id=?', (status,error,next_try,message_id,row['id']))
    return True


class TelegramWorker:
    def __init__(self):
        self.stop_event = threading.Event()
        self.thread = None
        self.owner = uuid.uuid4().hex

    def start(self):
        if not store.enabled(): return
        self.thread = threading.Thread(target=self.run, daemon=True, name='callwise-telegram')
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread: self.thread.join(timeout=20)

    def run(self):
        store.initialize()
        key, client = store.bot_key(), TelegramClient()
        while not self.stop_event.is_set():
            with store.session() as db:
                db.execute('BEGIN IMMEDIATE')
                db.execute("INSERT OR IGNORE INTO tg_runtime (bot_key,status,heartbeat) VALUES (?,'starting',?)", (key,time.time()))
                claimed = db.execute("UPDATE tg_runtime SET lease_owner=?,lease_until=?,status='starting' WHERE bot_key=? AND lease_until<?", (self.owner,time.time()+60,key,time.time())).rowcount
                if claimed:
                    # A crash may occur after Telegram accepts a message but before our ACK persists.
                    db.execute("UPDATE tg_outbox SET status='unknown',error='worker_interrupted' WHERE bot_key=? AND status='sending'", (key,))
            if claimed: break
            # Retry an expired lease after an abrupt restart instead of silently losing the worker.
            self.stop_event.wait(2)
        if self.stop_event.is_set(): return
        try:
            me = client.call('getMe')
            username = me['username']
            if client.call('getWebhookInfo').get('url'):
                raise TelegramError('webhook_active')
            with store.session() as db:
                db.execute("UPDATE tg_runtime SET username=?,status='ready',error=NULL,heartbeat=? WHERE bot_key=?", (username,time.time(),key))
            while not self.stop_event.is_set():
                with store.session() as db:
                    row = db.execute('SELECT offset,lease_owner FROM tg_runtime WHERE bot_key=?', (key,)).fetchone()
                    if row['lease_owner'] != self.owner: return
                    offset = row['offset']
                    db.execute('UPDATE tg_runtime SET heartbeat=?,lease_until=? WHERE bot_key=?', (time.time(),time.time()+60,key))
                try:
                    send_next(client,key)
                    updates = client.call('getUpdates', offset=offset, timeout=5, limit=20, allowed_updates=['message'])
                    for update in updates:
                        try:
                            process_update(client,update)
                        finally:
                            # Do not replay committed registration steps if the reply failed.
                            with store.session() as db:
                                db.execute('UPDATE tg_runtime SET offset=? WHERE bot_key=?', (update['update_id']+1,key))
                    with store.session() as db:
                        db.execute("UPDATE tg_runtime SET status='ready',error=NULL,heartbeat=? WHERE bot_key=?", (time.time(),key))
                except TelegramError as exc:
                    with store.session() as db:
                        db.execute("UPDATE tg_runtime SET status='error',error=?,heartbeat=? WHERE bot_key=?", (exc.category,time.time(),key))
                    if exc.category in {'invalid_token','polling_conflict','forbidden'}: break
                    self.stop_event.wait(max(5,exc.retry_after))
        except (TelegramError, KeyError, TypeError) as exc:
            with store.session() as db:
                db.execute("UPDATE tg_runtime SET status='error',error=?,heartbeat=? WHERE bot_key=?", (getattr(exc,'category','invalid_response'),time.time(),key))
        finally:
            with store.session() as db:
                db.execute('UPDATE tg_runtime SET lease_until=0,lease_owner=NULL WHERE bot_key=? AND lease_owner=?', (key,self.owner))
