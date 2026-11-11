"""Verify raw Mini App initData; never trust initDataUnsafe or browser user IDs."""
import hashlib
import hmac
import json
import os
import re
import time
from urllib.parse import parse_qsl


def verify_init_data(raw, now=None):
    token = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
    if not token or not isinstance(raw,str) or not 1 <= len(raw) <= 12000:
        raise ValueError('Откройте регистрацию внутри Telegram.')
    pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True, max_num_fields=30)
    data = dict(pairs)
    if len(data) != len(pairs):
        raise ValueError('Некорректные данные Telegram.')
    received = data.pop('hash', '')
    check = '\n'.join(f'{key}={value}' for key,value in sorted(data.items()))
    secret = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not re.fullmatch('[a-f0-9]{64}',received) or not hmac.compare_digest(received, expected):
        raise ValueError('Подпись Telegram не прошла проверку.')
    try:
        age = (time.time() if now is None else now) - int(data['auth_date'])
        user = json.loads(data['user'])
        if not 0 <= age <= 600 or not isinstance(user,dict) or type(user.get('id')) is not int or user['id'] <= 0 or user.get('is_bot'):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise ValueError('Сессия Telegram устарела или недействительна. Откройте приложение заново.') from None
    return user
