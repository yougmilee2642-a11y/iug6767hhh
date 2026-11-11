"""Per-agent bindings and a durable outbox. No global chat recipient."""
import hashlib
import json
import os
import secrets
import time
from contextlib import contextmanager, closing
import storage


def bot_key():
    token = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
    return hashlib.sha256(token.encode()).hexdigest() if token else ''


def enabled():
    from providers.local_settings import local_only
    if local_only(): return False
    return bool(bot_key()) and os.getenv('TELEGRAM_ENABLED', 'true').lower() == 'true'


@contextmanager
def session():
    with closing(storage.connect()) as db:
        with db:
            yield db


def initialize(db=None):
    if db is None:
        with session() as connection:
            initialize(connection)
        return
    # execute rather than executescript: preserve the caller's callback transaction.
    for sql in (
        'CREATE TABLE IF NOT EXISTS tg_bindings (agent_id TEXT PRIMARY KEY, bot_key TEXT NOT NULL, chat_id INTEGER NOT NULL, label TEXT NOT NULL)',
        'CREATE TABLE IF NOT EXISTS tg_links (id TEXT PRIMARY KEY, digest TEXT UNIQUE NOT NULL, agent_id TEXT NOT NULL, bot_key TEXT NOT NULL, expires REAL NOT NULL, chat_id INTEGER, label TEXT, used INTEGER NOT NULL DEFAULT 0)',
        'CREATE TABLE IF NOT EXISTS tg_outbox (id TEXT PRIMARY KEY, interaction_id TEXT UNIQUE NOT NULL, agent_id TEXT NOT NULL, bot_key TEXT NOT NULL, chat_id INTEGER NOT NULL, text TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, next_try REAL NOT NULL, error TEXT, message_id INTEGER)',
        'CREATE TABLE IF NOT EXISTS tg_runtime (bot_key TEXT PRIMARY KEY, username TEXT, status TEXT NOT NULL, error TEXT, heartbeat REAL NOT NULL, offset INTEGER NOT NULL DEFAULT 0, lease_owner TEXT, lease_until REAL NOT NULL DEFAULT 0)',
        'CREATE TABLE IF NOT EXISTS tg_users (telegram_id INTEGER PRIMARY KEY, display_name TEXT NOT NULL, business_name TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL, consent_version TEXT NOT NULL)',
        'CREATE TABLE IF NOT EXISTS tg_registration (telegram_id INTEGER PRIMARY KEY, step TEXT NOT NULL, payload TEXT NOT NULL, expires REAL NOT NULL)',
    ):
        db.execute(sql)


def status(agent_id):
    initialize()
    key = bot_key()
    with session() as db:
        binding = db.execute('SELECT chat_id,label FROM tg_bindings WHERE agent_id=? AND bot_key=?', (agent_id, key)).fetchone()
        worker = db.execute('SELECT username,status,error,heartbeat FROM tg_runtime WHERE bot_key=?', (key,)).fetchone()
    worker = dict(worker) if worker else {}
    if time.time() - worker.get('heartbeat', 0) > 60:
        worker['status'] = 'offline'
    return {'configured': enabled(), 'connected': bool(binding) and enabled(),
            'recipient': dict(binding) if binding else None,
            'worker': worker.get('status', 'offline'), 'error': worker.get('error'),
            'username': worker.get('username')}


def create_link(agent_id):
    current = status(agent_id)
    if not current['configured'] or current['worker'] != 'ready' or not current['username']:
        raise ValueError('Бот не готов: проверьте токен и перезапустите Callwise.')
    code, identifier = secrets.token_urlsafe(24), secrets.token_hex(16)
    with session() as db:
        db.execute('UPDATE tg_links SET used=1 WHERE agent_id=? AND used=0', (agent_id,))
        db.execute('INSERT INTO tg_links (id,digest,agent_id,bot_key,expires) VALUES (?,?,?,?,?)',
                   (identifier, hashlib.sha256(code.encode()).hexdigest(), agent_id, bot_key(), time.time()+600))
    return {'link_id': identifier, 'url': f"https://t.me/{current['username']}?start={code}", 'expires_in': 600}


def stage_link(code, chat_id, label):
    initialize()
    with session() as db:
        cursor = db.execute('UPDATE tg_links SET chat_id=?,label=? WHERE digest=? AND bot_key=? AND used=0 AND expires>? AND chat_id IS NULL',
                            (chat_id, label[:150], hashlib.sha256(code.encode()).hexdigest(), bot_key(), time.time()))
        return cursor.rowcount == 1


def link_status(identifier, agent_id):
    initialize()
    with session() as db:
        row = db.execute('SELECT chat_id,label,used,expires FROM tg_links WHERE id=? AND agent_id=? AND bot_key=?',
                         (identifier, agent_id, bot_key())).fetchone()
    if not row or row['used'] or row['expires'] <= time.time():
        raise ValueError('Ссылка истекла или уже использована. Создайте новую.')
    return {'pending_recipient': {'chat_id': row['chat_id'], 'label': row['label']} if row['chat_id'] else None}


def approve_link(identifier, agent_id):
    initialize()
    with session() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM tg_links WHERE id=? AND agent_id=? AND bot_key=? AND used=0 AND expires>?',
                         (identifier, agent_id, bot_key(), time.time())).fetchone()
        if not row or not row['chat_id']:
            raise ValueError('Сначала откройте ссылку в Telegram и нажмите Start, затем проверьте получателя.')
        db.execute('UPDATE tg_outbox SET status=\'cancelled\',error=\'recipient_changed\' WHERE agent_id=? AND status IN (\'pending\',\'retry\')', (agent_id,))
        db.execute('INSERT INTO tg_bindings VALUES (?,?,?,?) ON CONFLICT(agent_id) DO UPDATE SET bot_key=excluded.bot_key,chat_id=excluded.chat_id,label=excluded.label',
                   (agent_id, bot_key(), row['chat_id'], row['label']))
        db.execute('UPDATE tg_links SET used=1 WHERE id=?', (identifier,))
    return status(agent_id)


def disconnect(agent_id):
    initialize()
    with session() as db:
        db.execute('DELETE FROM tg_bindings WHERE agent_id=?', (agent_id,))
        db.execute('UPDATE tg_links SET used=1 WHERE agent_id=?', (agent_id,))
        db.execute('UPDATE tg_outbox SET status=\'cancelled\',error=\'disconnected\' WHERE agent_id=? AND status IN (\'pending\',\'retry\')', (agent_id,))


def enqueue_callback(db, saved, context):
    """Called inside the same transaction as callback INSERT, after real consent."""
    initialize(db)
    binding = db.execute('SELECT * FROM tg_bindings WHERE agent_id=? AND bot_key=?', (context.config.id, bot_key())).fetchone()
    if not enabled() or not binding:
        return False
    text = (f'Callwise · {context.config.business.name}\nПодтверждённое обращение\n'
            f"Номер: {saved['callback_id']}\nИмя: {saved['customer_name']}\nТелефон: {saved['phone']}\n"
            f"Причина: {saved['request_details']}\n\nЭто обращение, не выполненная услуга.")
    text = text[:3500]  # Plain text, no parse_mode. Do not turn user text into markup.
    db.execute('INSERT OR IGNORE INTO tg_outbox (id,interaction_id,agent_id,bot_key,chat_id,text,status,next_try) VALUES (?,?,?,?,?,?,?,?)',
               (saved['callback_id'], context.interaction_id, context.config.id, bot_key(), binding['chat_id'], text, 'pending', time.time()))
    return True


def delivery(interaction_id):
    initialize()
    with session() as db:
        row = db.execute('SELECT status,attempts,error,message_id FROM tg_outbox WHERE interaction_id=?', (interaction_id,)).fetchone()
    return dict(row) if row else {'status': 'not_queued'}


def register_user(user_id, display_name, business_name):
    initialize()
    now = time.time()
    with session() as db:
        db.execute('INSERT INTO tg_users VALUES (?,?,?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET display_name=excluded.display_name,business_name=excluded.business_name,updated_at=excluded.updated_at,consent_version=excluded.consent_version',
                   (user_id, display_name, business_name, now, now, 'registration-v1'))
        db.execute('DELETE FROM tg_registration WHERE telegram_id=?', (user_id,))
    return user_profile(user_id)


def user_profile(user_id):
    initialize()
    with session() as db:
        row = db.execute('SELECT telegram_id,display_name,business_name,consent_version FROM tg_users WHERE telegram_id=?', (user_id,)).fetchone()
    return dict(row) if row else None
