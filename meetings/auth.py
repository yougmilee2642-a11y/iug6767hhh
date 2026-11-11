"""Demo users with signed session cookie. Every /api/meet endpoint resolves the user server-side."""
import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path

from fastapi import Request

from meetings import store


class MeetError(Exception):
    """API error `{code, detail}`. `audit` (optional dict with user_id/action/... ) is written by the error
    handler in its own transaction AFTER the request's transaction rolled back, so denials are never lost."""

    def __init__(self, status: int, code: str, detail: str, audit: dict | None = None):
        super().__init__(detail)
        self.status, self.code, self.detail, self.audit = status, code, detail, audit


# ---------- roles and capabilities (ОТ-02) ----------
# `users.role` stays the human job title; `users.access_role` is the server-side role. Capabilities are checked on
# the server in addition to (never instead of) the per-object ACL: a capability never opens a foreign object.
CAPABILITIES = {
    'reader': ('meetings.read', 'prep.generate', 'calendar.view', 'qa.ask', 'overview.read', 'feedback.create'),
    'manager': ('meetings.read', 'prep.generate', 'calendar.view', 'qa.ask', 'overview.read', 'feedback.create',
                'meetings.create', 'meetings.edit', 'meetings.share', 'documents.upload', 'documents.share',
                'transcript.edit', 'protocol.edit', 'protocol.confirm', 'tasks.change', 'calendar.invite',
                'audit.read'),
}
ROLE_LABELS = {'reader': 'Чтение и обратная связь', 'manager': 'Управление встречами и задачами'}


def capabilities(user: dict) -> list[str]:
    return list(CAPABILITIES.get((user or {}).get('access_role') or 'reader', CAPABILITIES['reader']))


def has_capability(user: dict, capability: str) -> bool:
    return capability in capabilities(user)


def forbidden(user: dict, capability: str, object_type: str | None = None, object_id=None, action: str | None = None):
    """403 for an action the role does not allow on an object the user CAN see. Audited, no titles."""
    return MeetError(403, 'forbidden_role', 'Ваша роль не позволяет выполнить это действие.',
                     audit={'user_id': user['id'], 'action': 'access_denied', 'object_type': object_type,
                            'object_id': object_id, 'result': 'denied', 'error_code': 'forbidden_role',
                            'attempted': action or capability, 'capability': capability})


def require(user: dict, capability: str, object_type: str | None = None, object_id=None, action: str | None = None):
    if not has_capability(user, capability):
        raise forbidden(user, capability, object_type, object_id, action)

COOKIE = 'cw_meet_user'
TTL = 12 * 3600

DEMO_USERS = [
    ('irina', 'Ирина Власова', 'Руководитель проекта', 'irina-demo', 'manager'),
    ('petr', 'Пётр Смирнов', 'Подрядчик (дизайн)', 'petr-demo', 'reader'),
]


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(8)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 120_000).hex()
    return f'{salt}${digest}'


def check_password(password: str, stored: str) -> bool:
    salt, _, _digest = stored.partition('$')
    return hmac.compare_digest(hash_password(password, salt), stored)


def ensure_demo_users():
    with store.db() as connection:
        for login, name, role, password, access_role in DEMO_USERS:
            if not connection.execute('SELECT 1 FROM users WHERE login=?', (login,)).fetchone():
                connection.execute('INSERT INTO users(login,name,role,password_hash,access_role) VALUES (?,?,?,?,?)',
                                   (login, name, role, hash_password(password), access_role))


def _secret() -> bytes:
    configured = os.getenv('MEETINGS_SECRET', '')
    if configured:
        return configured.encode()
    path = Path(store.db_path()).with_name('meetings_secret.key')
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(32))
    return path.read_text().strip().encode()


def make_cookie(user_id: int) -> str:
    value = f'{user_id}.{int(time.time()) + TTL}.{secrets.token_hex(8)}'
    return value + '.' + hmac.new(_secret(), value.encode(), hashlib.sha256).hexdigest()


def user_from_request(request: Request) -> dict | None:
    raw = request.cookies.get(COOKIE, '')
    try:
        user_id, expiry, nonce, digest = raw.split('.')
        value = f'{user_id}.{expiry}.{nonce}'
        if not hmac.compare_digest(digest, hmac.new(_secret(), value.encode(), hashlib.sha256).hexdigest()):
            return None
        if int(expiry) < time.time():
            return None
        with store.db() as connection:
            row = connection.execute('SELECT id,login,name,role,access_role FROM users WHERE id=?',
                                     (int(user_id),)).fetchone()
        return dict(row) if row else None
    except (ValueError, TypeError):
        return None


def current_user(request: Request) -> dict:
    user = user_from_request(request)
    if not user:
        raise MeetError(401, 'not_authenticated', 'Войдите как демо-пользователь.')
    return user
