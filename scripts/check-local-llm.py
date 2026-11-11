"""Real local model smoke: Russian reply, native tools and structured output.

Only synthetic data and a read-only fictional tool result; no business writes.
Run before changing .env: python scripts/check-local-llm.py --model qwen3:4b-instruct
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / '.env')
from providers.base import ConversationMessage, ToolSpec
from providers.ollama import OllamaProvider


class VoiceSmokeProvider(OllamaProvider):
    def request(self, *args, **kwargs):
        message = super().request(*args, **kwargs)
        assert not message.get('thinking', '').strip(), 'Model generated reasoning despite voice non-thinking mode'
        content = message.get('content', '')
        if '</think>' in content:
            prefix = content.rsplit('</think>', 1)[0]
            assert not re.sub(r'</?think>', '', prefix).strip(), 'Model generated reasoning in content'
        assert '<think>' not in content or '</think>' in content, 'Unfinished reasoning block'
        return message


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True)
    args = parser.parse_args()
    provider = VoiceSmokeProvider(model=args.model)
    assert provider.available(), 'Requested model is not installed'
    checks = []

    def record(case, started):
        checks.append({'case': case, 'passed': True,
                       'seconds': round(time.perf_counter() - started, 3),
                       'metrics': dict(provider.last_metrics)})

    started = time.perf_counter()
    reply = provider.complete([
        ConversationMessage('system', 'Отвечай по-русски, кратко. Не выдумывай услуги и доступность.'),
        ConversationMessage('user', 'Тестовый факт: консультация стоит 50 BYN. Сколько стоит консультация?'),
    ], [])
    assert '50' in reply.text and not reply.tool_calls and '<think>' not in reply.text, reply.text
    record('russian_price', started)

    tool = ToolSpec('check_slots', 'Read-only availability in a fictional calendar.', {
        'type': 'object', 'properties': {'service': {'type': 'string'}, 'date': {'type': 'string'}},
        'required': ['service', 'date'], 'additionalProperties': False,
    })
    messages = [
        ConversationMessage('system', 'Use check_slots to check availability. Never invent availability. '
                            'For the first reply call the tool with the requested service and ISO date. '
                            'After the tool result, reply in Russian with the returned available time.'),
        ConversationMessage('user', 'Проверь доступность: стрижка, 2026-10-20.'),
    ]
    started = time.perf_counter()
    reply = provider.complete(messages, [tool])
    assert len(reply.tool_calls) == 1, 'Expected one native read-only tool call'
    call = reply.tool_calls[0]
    assert call.name == 'check_slots' and call.arguments == {'service': 'стрижка', 'date': '2026-10-20'}, call
    messages.extend([
        ConversationMessage('assistant', reply.text, calls=reply.tool_calls),
        ConversationMessage('tool', call_id=call.id, result={'slots': [{'datetime': '2026-10-20T17:30:00'}]}),
    ])
    answer = provider.complete(messages, [tool])
    assert not answer.tool_calls and '17:30' in answer.text, answer
    record('native_tool_round_trip', started)

    started = time.perf_counter()
    result = provider.structured([
        ConversationMessage('system', 'Extract only the facts in the user message as JSON.'),
        ConversationMessage('user', 'Услуга: стрижка. Дата: 2026-10-20. Время: 17:30.'),
    ], {'type': 'object', 'properties': {key: {'type': 'string'} for key in ('service', 'date', 'time')},
        'required': ['service', 'date', 'time'], 'additionalProperties': False}, predict=128)
    assert result == {'service': 'стрижка', 'date': '2026-10-20', 'time': '17:30'}, result
    record('structured_output', started)

    output = {'model': args.model, 'passed': True, 'synthetic': True, 'business_writes': 0,
              'thinking': False, 'request_count': provider.request_count, 'checks': checks}
    destination = ROOT / 'proof/local-llm-smoke.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(output, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
