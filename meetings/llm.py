"""Meetings LLM: loopback by default, or the shared authenticated gateway policy.

Remote inference runs on the gateway host, not on the browser user's computer.
"""
import json
import os

import httpx

from providers.local_settings import LocalAIError
from providers import ollama


class MeetingLLM:
    def __init__(self, transport=None, model=None):
        self.transport = transport
        self.model = model or os.getenv('MEETINGS_MODEL') or 'qwen2.5:7b'

    def _target(self):
        if ':cloud' in self.model.casefold() or '-cloud' in self.model.casefold():
            raise LocalAIError('cloud_disabled')
        try:
            target = ollama.endpoint()
        except ValueError:
            target = None
        if not target:
            raise LocalAIError('unavailable')
        return target

    def _base(self):
        # Keep the previous helper compatible; validation has one shared owner.
        return self._target()[0]

    def json(self, system: str, user: str, schema: dict, predict: int = 1500) -> dict:
        base, headers = self._target()
        payload = {'model': self.model, 'stream': False, 'think': False, 'keep_alive': '30m', 'format': schema,
                   'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
                   'options': {'num_ctx': int(os.getenv('MEETINGS_CONTEXT', '8192')), 'num_predict': predict,
                               'temperature': 0.1}}
        try:
            with httpx.Client(timeout=float(os.getenv('MEETINGS_TIMEOUT', '300')), transport=self.transport,
                              trust_env=False, follow_redirects=False) as client:
                response = client.post(base + '/api/chat', json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or data.get('done') is not True or data.get('done_reason') == 'length':
                raise LocalAIError('invalid_reply')
            result = json.loads(data['message']['content'])
            if not isinstance(result, dict):
                raise LocalAIError('invalid_reply')
            return result
        except httpx.TimeoutException:
            raise LocalAIError('timeout') from None
        except (httpx.HTTPError, httpx.InvalidURL):
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
