"""Loopback-only local LLM client for meetings. No cloud fallback, ever."""
import json
import os
from urllib.parse import urlsplit

import httpx

from providers.local_settings import LocalAIError


class MeetingLLM:
    def __init__(self, transport=None, model=None):
        self.transport = transport
        self.model = model or os.getenv('MEETINGS_MODEL') or 'qwen2.5:7b'

    def _base(self):
        base = os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434').rstrip('/')
        parsed = urlsplit(base)
        if (parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}
                or parsed.username or parsed.password or parsed.path):
            raise LocalAIError('unavailable')
        if self.model.endswith(':cloud') or '-cloud' in self.model:
            raise LocalAIError('cloud_disabled')
        return base

    def json(self, system: str, user: str, schema: dict, predict: int = 1500) -> dict:
        base = self._base()
        payload = {'model': self.model, 'stream': False, 'think': False, 'keep_alive': '30m', 'format': schema,
                   'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
                   'options': {'num_ctx': int(os.getenv('MEETINGS_CONTEXT', '8192')), 'num_predict': predict,
                               'temperature': 0.1}}
        try:
            with httpx.Client(timeout=float(os.getenv('MEETINGS_TIMEOUT', '300')), transport=self.transport,
                              trust_env=False, follow_redirects=False) as client:
                response = client.post(base + '/api/chat', json=payload)
            response.raise_for_status()
            data = response.json()
            if data.get('done_reason') == 'length':
                raise LocalAIError('invalid_reply')
            result = json.loads(data['message']['content'])
            if not isinstance(result, dict):
                raise LocalAIError('invalid_reply')
            return result
        except httpx.TimeoutException:
            raise LocalAIError('timeout') from None
        except httpx.HTTPError:
            raise LocalAIError('unavailable') from None
        except (ValueError, KeyError, TypeError):
            raise LocalAIError('invalid_reply') from None


_provider = None


def get_llm():
    global _provider
    if _provider is None:
        _provider = MeetingLLM()
    return _provider


def set_llm(provider):
    """Tests inject a fake provider."""
    global _provider
    _provider = provider
