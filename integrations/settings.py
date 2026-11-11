import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field
import storage
from integrations.contracts import IntegrationError
from providers.local_settings import local_only


class Binding(BaseModel):
    model_config = ConfigDict(extra='forbid')
    calendars: dict[str, str] = Field(min_length=1, max_length=40)
    google_credentials_env: str = Field(default='CALLWISE_GOOGLE_CREDENTIALS', pattern=r'^[A-Z][A-Z0-9_]{0,79}$')
    bitrix_webhook_env: str | None = Field(default=None, pattern=r'^[A-Z][A-Z0-9_]{0,79}$')

    def fingerprint(self):
        # Token rotation is permitted; silently changing the CRM destination is not.
        destination = urlsplit(os.getenv(self.bitrix_webhook_env, '')) if self.bitrix_webhook_env else None
        portal = destination.netloc + '/'.join(destination.path.split('/')[:3]) if destination else ''
        return hashlib.sha256((self.model_dump_json() + '\0' + portal).encode()).hexdigest()


def bindings():
    filename = os.getenv('CALLWISE_INTEGRATIONS_FILE', '').strip()
    if not filename:
        return {}
    try:
        if Path(filename).stat().st_size > 1000000: raise ValueError()
        raw = json.loads(Path(filename).read_text(encoding='utf-8-sig'))
        if not isinstance(raw, dict) or len(raw) > 100:
            raise ValueError()
        return {key: Binding.model_validate(value) for key, value in raw.items()}
    except (ValueError, OSError, TypeError):
        raise IntegrationError('config') from None


def network_allowed():
    # Simulation must never mutate real businesses, even with live owner credentials.
    if local_only() or storage.is_isolated_database() or os.getenv('CALLWISE_CLOUD_INTEGRATIONS_ENABLED', 'false').lower() != 'true':
        raise IntegrationError('disabled')


def public_status():
    try:
        configured = bindings()
    except IntegrationError:
        return {'status': 'invalid_config', 'agents': []}
    enabled = not local_only() and os.getenv('CALLWISE_CLOUD_INTEGRATIONS_ENABLED', 'false').lower() == 'true'
    agents = []
    for agent_id, binding in configured.items():
        credentials = os.getenv(binding.google_credentials_env, '')
        try:
            ready = bool(credentials and Path(credentials).is_file())
        except (OSError, ValueError):
            ready = False
        crm_ready = bool(binding.bitrix_webhook_env and os.getenv(binding.bitrix_webhook_env, ''))
        agents.append({'agent_id': agent_id, 'calendar': 'google', 'resources': list(binding.calendars),
                       'status': 'configured_unverified' if enabled and ready else 'disabled' if not enabled else 'credentials_missing',
                       'crm': 'bitrix24' if binding.bitrix_webhook_env else None, 'crm_credentials_present': crm_ready})
    return {'status': 'enabled_unverified' if enabled else 'disabled', 'local_only': local_only(),
            'agents': agents, 'supported': {'calendar': ['google'], 'crm': ['bitrix24']}}
