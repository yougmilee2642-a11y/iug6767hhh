"""Measure voice-path latency on a temporary local stand (P1-03).

What is measured here, each stage separately (stages are never summed into a
"full conversation time"):
  stt  - POST /api/transcribe (multipart field ``file`` with real WAV bytes)
  llm  - POST /api/chat with a synthetic customer phrase
  tts  - POST /api/speech: time to first audio bytes and time to the whole WAV

Not measurable over HTTP and therefore reported as "not measured": endpointing
(end-of-speech detection) and the start of actual playback. Both happen in the
browser and need a manual run with a real microphone.

Safety: only loopback addresses; by default the script starts its OWN server
with a temporary database, no Telegram and no e-mail; synthetic data only.
HTTP 4xx/5xx, timeouts and cancellations are failed attempts, never latencies.
Standard library only.
"""
import argparse
import io
import ipaddress
import json
import math
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
import wave
from pathlib import Path
from urllib import error, request
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_PHRASES = {
    'short': 'Где посмотреть баланс?',
    'phone': 'Меня зовут Анна, мой номер плюс триста семьдесят пять двадцать девять один один один два два три три',
    'negation': 'Я не хочу доставку, перезвоните мне завтра',
}


def assert_loopback(url):
    parsed=urlparse(url)
    host=parsed.hostname
    if parsed.scheme not in {'http','https'} or parsed.username or parsed.password or host not in {'127.0.0.1','localhost','::1'}:
        raise ValueError('Замер разрешён только на локальном HTTP/HTTPS без учётных данных.')
    return host



def wav_bytes(seconds=2.0, rate=16000, tone_hz=0.0):
    """Valid mono 16-bit PCM WAV. tone_hz=0 gives silence; otherwise a synthetic tone (not speech)."""
    frames = int(seconds * rate)
    samples = bytearray()
    for n in range(frames):
        value = int(8000 * math.sin(2 * math.pi * tone_hz * n / rate)) if tone_hz else 0
        samples += value.to_bytes(2, 'little', signed=True)
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(bytes(samples))
    return buffer.getvalue()


def multipart(fields, file_field, filename, content, content_type='audio/wav'):
    boundary = '----focus' + uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    head = (f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
            f'Content-Type: {content_type}\r\n\r\n').encode()
    parts.append(head + content + b'\r\n')
    parts.append(f'--{boundary}--\r\n'.encode())
    return b''.join(parts), f'multipart/form-data; boundary={boundary}'


def percentile(values, q):
    """Nearest-rank percentile; None for an empty sample."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q / 100 * len(ordered)) - 1)]


def summarize(attempts):
    """attempts: dicts with stage, label, temperature, ok, ms. Latency statistics use successful attempts only."""
    groups = {}
    for item in attempts:
        groups.setdefault((item['stage'], item['label'], item['temperature']), []).append(item)
    rows = []
    for (stage, label, temperature), items in sorted(groups.items()):
        good = [i['ms'] for i in items if i['ok']]
        rows.append({'stage': stage, 'label': label, 'temperature': temperature, 'attempts': len(items),
                     'successes': len(good), 'failures': len(items) - len(good),
                     'p50_ms': percentile(good, 50), 'p95_ms': percentile(good, 95),
                     'minimum_sample_size_met': len(good) >= 20})
    return rows


def timed(url, data=None, headers=None, timeout=120, first_byte=False):
    """Returns (ok, status, total_ms, first_byte_ms, body). Any HTTP error or exception is not ok."""
    assert_loopback(url)
    req = request.Request(url, data=data, headers=headers or {}, method='POST' if data is not None else 'GET')
    start = time.perf_counter()
    try:
        class NoRedirect(request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs): raise error.URLError('Redirects disabled')
        opener=request.build_opener(request.ProxyHandler({}),NoRedirect())
        with opener.open(req, timeout=timeout) as response:
            first = response.read(1)
            first_ms = (time.perf_counter() - start) * 1000
            body = first + response.read()
            return 200 <= response.status < 300, response.status, (time.perf_counter() - start) * 1000, first_ms, body
    except error.HTTPError as exc:
        return False, exc.code, (time.perf_counter() - start) * 1000, None, b''
    except Exception:
        return False, None, (time.perf_counter() - start) * 1000, None, b''


def json_post(base, path, payload, timeout=120):
    return timed(base + path, json.dumps(payload).encode(), {'Content-Type': 'application/json'}, timeout)


def run_measurements(base, repeats, wav, phrases, temperature_of=lambda i: 'first_attempt' if i == 0 else 'repeat_attempt', timeout=120):
    attempts, notes = [], []
    for label, text in phrases.items():
        for i in range(repeats):
            ok, status, _, _, body = json_post(base, '/api/conversations', {}, timeout)
            if not ok:
                raise RuntimeError(f'Не удалось создать разговор на стенде (HTTP {status})')
            interaction = json.loads(body)['interaction_id']
            temp = temperature_of(i)
            data, ctype = multipart({'interaction_id': interaction, 'context': ''}, 'file', 'voice.wav', wav)
            ok, status, ms, _, body = timed(base + '/api/transcribe', data, {'Content-Type': ctype}, timeout)
            attempts.append({'stage': 'stt', 'label': 'audio', 'temperature': temp, 'ok': ok, 'status': status, 'ms': ms})
            ok, status, ms, _, body = json_post(base, '/api/chat', {'interaction_id': interaction, 'text': text,
                                                                    'request_id': str(uuid.uuid4())}, timeout)
            try: reply_ok = ok and bool(json.loads(body).get('text')) if ok else False
            except (ValueError,TypeError,AttributeError): reply_ok=False
            attempts.append({'stage': 'llm', 'label': label, 'temperature': temp, 'ok': reply_ok, 'status': status, 'ms': ms})
            ok, status, ms, first_ms, body = timed(base + '/api/speech', json.dumps({'text': text}).encode(),
                                                   {'Content-Type': 'application/json'}, timeout)
            wav_ok = ok and body[:4] == b'RIFF'
            attempts.append({'stage': 'tts_first_audio', 'label': label, 'temperature': temp, 'ok': wav_ok, 'status': status,
                             'ms': first_ms if wav_ok else ms})
            attempts.append({'stage': 'tts_total', 'label': label, 'temperature': temp, 'ok': wav_ok, 'status': status, 'ms': ms})
    notes.append('endpointing и начало воспроизведения: не измерялись этим скриптом. Их пишет браузер при ручной проверке с микрофоном: кнопка «Скачать замеры задержек (JSON)» на экране разговора (static/voice-metrics.js).')
    return attempts, notes


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


LAUNCH = """
import os, sys, pathlib
root, port, folder = sys.argv[1], int(sys.argv[2]), sys.argv[3]
sys.path.insert(0, root); os.chdir(root)
import storage
storage.DATA_DIR = pathlib.Path(folder); storage.DB_PATH = pathlib.Path(folder) / 'latency.sqlite'
import uvicorn, app
for route in app.app.routes:
    if getattr(route,'path',None)=='/api/health':
        original=route.dependant.call
        def health(): return {**original(), 'benchmark_temp_db':True}
        route.endpoint=health; route.dependant.call=health
uvicorn.run(app.app, host='127.0.0.1', port=port, log_level='warning')
"""


def start_temp_server():
    port = free_port()
    env = dict(os.environ, TELEGRAM_ENABLED='false', BUSINESS_EMAIL='', CALLWISE_OWNER_PASSWORD='', CALLWISE_LOCAL_ONLY='true', AI_PROVIDER='ollama', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    temporary=tempfile.TemporaryDirectory(prefix='focus-latency-')
    try: process = subprocess.Popen([sys.executable, '-c', LAUNCH, str(ROOT), str(port),temporary.name], env=env, cwd=ROOT)
    except Exception:
        temporary.cleanup();raise
    process._focus_temporary=temporary
    base = f'http://127.0.0.1:{port}'
    for _ in range(120):
        if timed(base + '/api/health', timeout=2)[0]:
            return process, base
        if process.poll() is not None:
            break
        time.sleep(1)
    stop_temp_server(process)
    raise RuntimeError('Временный сервер не запустился')


def stop_temp_server(process):
    if process.poll() is None:
        process.terminate()
        try: process.wait(timeout=10)
        except subprocess.TimeoutExpired: process.kill();process.wait(timeout=10)
    temporary=getattr(process,'_focus_temporary',None)
    if temporary:
        target=Path(temporary.name).resolve()
        if target.parent!=Path(tempfile.gettempdir()).resolve() or not target.name.startswith('focus-latency-'):
            raise ValueError('Unexpected temporary storage path')
        temporary.cleanup()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--url', help='Уже запущенный ВРЕМЕННЫЙ стенд на loopback; по умолчанию запускается свой сервер')
    parser.add_argument('--confirm-temp-db', action='store_true', help='Подтверждаю, что --url работает на временной базе')
    parser.add_argument('--repeats', type=int, default=20, help='Повторов на фразу (20+ успешных от 20 успешных)')
    parser.add_argument('--wav', help='WAV с синтетической речью; без него используется синтетический тон (не речь)')
    parser.add_argument('--json-out')
    args = parser.parse_args(argv)
    if not 1<=args.repeats<=100: parser.error('Повторы: 1–100')
    wav = Path(args.wav).read_bytes() if args.wav else wav_bytes(2.0, tone_hz=220.0)
    process = None
    try:
        if args.url:
            assert_loopback(args.url)
            if not args.confirm_temp_db:
                parser.error('--url требует --confirm-temp-db: замер не должен писать в рабочую базу')
            base = args.url.rstrip('/')
            ok,_,_,_,body=timed(base+'/api/health')
            health=json.loads(body) if ok else {}
            if not (health.get('benchmark_temp_db') or health.get('qa_stub')):
                parser.error('Указанный сервер не отмечен как временный стенд; рабочая база не используется.')
        else:
            process, base = start_temp_server()
        attempts, notes = run_measurements(base, args.repeats, wav, SYNTHETIC_PHRASES)
    finally:
        if process:
            stop_temp_server(process)
    notes.append('first_attempt/repeat_attempt — порядок попыток, не доказательство холодной/прогретой модели. 20 успешных — минимальная выборка, не гарантия точности p95.')
    rows = summarize(attempts)
    if not args.wav:
        notes.append('Аудио: синтетический тон, а не речь; STT-результат не оценивается, измеряется только время обработки.')
    print('| этап | фраза | cold/warm | попыток | успех | сбой | p50 мс | p95 мс | 20+ успешных |')
    print('|---|---|---|---|---|---|---|---|---|')
    for r in rows:
        print(f"| {r['stage']} | {r['label']} | {r['temperature']} | {r['attempts']} | {r['successes']} | {r['failures']} | "
              f"{r['p50_ms'] and round(r['p50_ms'])} | {r['p95_ms'] and round(r['p95_ms'])} | {'да' if r['minimum_sample_size_met'] else 'нет (мало повторов)'} |")
    for note in notes:
        print('Примечание:', note)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps({'rows': rows, 'attempts': attempts, 'notes': notes}, ensure_ascii=False, indent=1), encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
