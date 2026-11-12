"""REST adapters: no implicit retries or silent demo fallback."""
import logging
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
import httpx
from integrations.contracts import IntegrationError
from integrations.settings import network_allowed

_credentials_cache = {}
_credentials_lock = threading.Lock()


WEBHOOK = re.compile(r'(/rest/\d+/)[^/\s\"]+')


class WebhookRedaction(logging.Filter):
    def filter(self, record):
        def redact(value):
            if isinstance(value, (int, float)) or value is None:
                return value
            text = str(value)  # httpx passes URL objects
            return WEBHOOK.sub(r'\1[REDACTED]', text) if WEBHOOK.search(text) else value
        # Keep record.args intact in shape so formatters that unpack it still work.
        if isinstance(record.args, tuple):
            record.args = tuple(redact(arg) for arg in record.args)
        elif isinstance(record.args, dict):
            record.args = {key: redact(arg) for key, arg in record.args.items()}
        record.msg = redact(record.msg)
        return True


for _name in ('httpx', 'httpcore'):
    logging.getLogger(_name).addFilter(WebhookRedaction())


def instant(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Timezone required')
    return result


class GoogleCalendar:
    def __init__(self, credentials_env, client=None, token=None):
        self.credentials_env = credentials_env
        self.client = client
        self.token = token  # Dependency injection for transport-only tests.

    def bearer(self):
        if self.token:
            return self.token()
        try:
            from google.oauth2 import service_account
            from google.auth.transport.requests import Request
            import requests
            path = Path(os.environ[self.credentials_env]).resolve()
            stat = path.stat()
            if stat.st_size > 100000: raise ValueError()
            key = (str(path), stat.st_mtime_ns, stat.st_size)

            class BoundedRequest(Request):
                def __call__(self, *args, **kwargs):
                    kwargs['timeout'] = 10
                    return super().__call__(*args, **kwargs)

            with _credentials_lock:
                credentials = _credentials_cache.get(key)
                if credentials is None:
                    credentials = service_account.Credentials.from_service_account_file(
                        str(path), scopes=['https://www.googleapis.com/auth/calendar'])
                    # Credentials are owner-managed; don't accept arbitrary token destinations.
                    if credentials._token_uri != 'https://oauth2.googleapis.com/token': raise ValueError()
                    if len(_credentials_cache) >= 100: _credentials_cache.clear()
                    _credentials_cache[key] = credentials
                if not credentials.valid:
                    with requests.Session() as session:
                        session.trust_env = False
                        credentials.refresh(BoundedRequest(session=session))
                return credentials.token
        except Exception:
            raise IntegrationError('config') from None

    def request(self, method, path, payload=None, missing=False, write=False):
        network_allowed()
        headers = {'Authorization': 'Bearer ' + self.bearer()}
        try:
            with httpx.Client(timeout=12, trust_env=False, follow_redirects=False) if self.client is None else _Borrowed(self.client) as client:
                response = client.request(method, 'https://www.googleapis.com/calendar/v3/' + path, json=payload, headers=headers)
            if missing and response.status_code == 404:
                return None
            if response.status_code == 409:
                raise IntegrationError('conflict', uncertain=write)
            if not response.is_success:
                raise IntegrationError('unavailable', uncertain=write and (response.status_code >= 500 or 300 <= response.status_code < 400))
            if method == 'DELETE' and response.status_code == 204:
                return {}
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except (httpx.HTTPError, ValueError) as exc:
            if isinstance(exc, IntegrationError):
                raise
            raise IntegrationError('unavailable', uncertain=write) from None

    def busy(self, calendar_ids, start, end):
        data = self.request('POST', 'freeBusy', {'timeMin': start, 'timeMax': end, 'items': [{'id': key} for key in calendar_ids]})
        try:
            result = {}
            for key in calendar_ids:
                calendar = data['calendars'][key]
                if calendar.get('errors') or not isinstance(calendar['busy'], list):
                    raise ValueError()
                for interval in calendar['busy']:
                    if instant(interval['end']) <= instant(interval['start']):
                        raise ValueError()
                result[key] = calendar['busy']
            return result
        except (ValueError, KeyError, TypeError, AttributeError):
            raise IntegrationError('unavailable') from None

    def get(self, calendar_id, event_id):
        return self.request('GET', 'calendars/' + quote(calendar_id, safe='') + '/events/' + event_id, missing=True)

    def insert(self, calendar_id, event):
        return self.request('POST', 'calendars/' + quote(calendar_id, safe='') + '/events?sendUpdates=none', event, write=True)


class _Borrowed:
    def __init__(self, client): self.client = client
    def __enter__(self): return self.client
    def __exit__(self, *args): pass


class BitrixCRM:
    def __init__(self, webhook_env, client=None):
        self.webhook_env = webhook_env
        self.client = client

    def request(self, method, payload):
        network_allowed()
        base = os.getenv(self.webhook_env, '')
        # Cloud Bitrix only. Reject arbitrary hosts, query strings, redirects, local URLs.
        if not re.fullmatch(r'https://[a-zA-Z0-9-]+\.bitrix24\.(?:ru|by|com|eu|de|kz|ua)/rest/[1-9][0-9]*/[a-zA-Z0-9_-]+/', base):
            raise IntegrationError('config')
        try:
            with httpx.Client(timeout=12, trust_env=False, follow_redirects=False) if self.client is None else _Borrowed(self.client) as client:
                response = client.post(base + method + '.json', json=payload)
            if not response.is_success:
                raise IntegrationError('unavailable', uncertain=method.endswith('.add') and response.status_code >= 300)
            data = response.json()
            if data.get('error'):
                raise IntegrationError('unavailable', uncertain=method.endswith('.add'))
            return data['result']
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
            if isinstance(exc, IntegrationError): raise
            raise IntegrationError('unavailable', uncertain=method.endswith('.add')) from None

    def find(self, booking_id):
        rows = self.request('crm.deal.list', {'filter': {'=ORIGINATOR_ID': 'callwise', '=ORIGIN_ID': booking_id},
                                              'select': ['ID', 'ORIGINATOR_ID', 'ORIGIN_ID']})
        if not isinstance(rows, list) or len(rows) > 1:
            raise IntegrationError('conflict')
        if not rows: return None
        if rows[0].get('ORIGIN_ID') != booking_id or rows[0].get('ORIGINATOR_ID') != 'callwise' or not str(rows[0].get('ID', '')).isdigit():
            raise IntegrationError('conflict')
        return str(rows[0]['ID'])

    def create(self, booking):
        values = booking['structured_data']['values']
        result = self.request('crm.deal.add', {'fields': {
            'TITLE': 'Callwise: ' + values['service'], 'ORIGINATOR_ID': 'callwise', 'ORIGIN_ID': booking['id'],
            'COMMENTS': '\n'.join([f"Клиент: {values['customer_name']}", f"Телефон: {values['phone']}",
                                  f"Время: {values['datetime']}", f"Сотрудник: {values['employee']}",
                                  'Событие календаря: ' + booking['id']]),
        }})
        if not str(result).isdigit():
            raise IntegrationError('uncertain', uncertain=True)
        return str(result)
