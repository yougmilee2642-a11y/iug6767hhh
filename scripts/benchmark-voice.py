"""Synthetic loopback voice pipeline; not a real-microphone latency benchmark."""
import argparse
import json
import time
from pathlib import Path
import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--runs', type=int, default=3, choices=range(1, 6))
    args = parser.parse_args()
    records = []
    with httpx.Client(base_url='http://127.0.0.1:8000', timeout=120, trust_env=False) as client:
        def post(path, **kwargs):
            response = client.post(path, **kwargs)
            response.raise_for_status()
            return response
        health = client.get('/api/health').json()
        for index in range(args.runs):
            started = post('/api/shell/conversations', json={
                'id': 'voice-benchmark', 'name': 'Синтетический голосовой тест', 'company': 'Тестовая команда',
                'role': 'Поддержка клиентов', 'greeting': 'Здравствуйте! Чем могу помочь?',
                'knowledge': 'Кодовое слово команды — Парус. Не собирай личные данные.',
                'qa': [{'question': 'Какое кодовое слово команды?', 'answer': 'Кодовое слово команды — Парус.'}]
            }).json()
            cid = started['interaction_id']
            try:
                if started.get('privacy', {}).get('status') == 'pending':
                    post('/api/conversations/'+cid+'/consent', json={'accepted': True, 'version': started['privacy']['version']})
                wav = post('/api/speech', json={'text': 'Какое кодовое слово команды?'}).content
                began = time.perf_counter()
                recognized = post('/api/transcribe', files={'file': ('synthetic.wav', wav, 'audio/wav')},
                                  data={'interaction_id': cid}).json()['text']
                stt = time.perf_counter()-began
                began = time.perf_counter()
                reply = post('/api/chat', json={'interaction_id': cid, 'text': recognized,
                             'request_id': 'benchmark-'+str(index)}).json()
                llm = time.perf_counter()-began
                began = time.perf_counter()
                audio = post('/api/speech', json={'text': reply['text']}).content
                tts = time.perf_counter()-began
                assert recognized.strip() and 'парус' in reply['text'].casefold() and audio.startswith(b'RIFF')
                records.append({'run': index+1, 'stt_seconds': round(stt, 3), 'llm_seconds': round(llm, 3),
                    'tts_seconds': round(tts, 3), 'serial_pipeline_seconds': round(stt+llm+tts, 3),
                    'answer_chars': len(reply['text']), 'passed': True})
                print(json.dumps(records[-1]), flush=True)
            finally:
                post('/api/application', json={'interaction_id': cid})
    result = {'purpose': 'synthetic_local_pipeline_not_real_call', 'includes_endpointing_or_playback': False,
              'model': health['model'], 'speech': health['local_speech'], 'runs': records}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__': main()
