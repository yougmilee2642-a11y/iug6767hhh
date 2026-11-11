"""Checks for scripts/measure_voice_latency.py against a fake loopback server (no models, no real data)."""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import measure_voice_latency as m  # noqa: E402


class Fake(BaseHTTPRequestHandler):
    seen = {'multipart_ok': False, 'wav_ok': False}

    def log_message(self, *a):
        pass

    def reply(self, code, body=b'', ctype='application/json'):
        self.send_response(code); self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        if self.path == '/api/conversations':
            return self.reply(200, json.dumps({'interaction_id': 'i1'}).encode())
        if self.path == '/api/transcribe':
            Fake.seen['multipart_ok'] = b'name="file"; filename="voice.wav"' in body and b'name="audio"' not in body
            Fake.seen['wav_ok'] = b'RIFF' in body and b'WAVE' in body
            return self.reply(200, json.dumps({'text': 'тест'}).encode())
        if self.path == '/api/chat':
            if 'не хочу' in json.loads(body)['text']:
                return self.reply(502, json.dumps({'detail': 'Ошибка ответа AI'}).encode())
            return self.reply(200, json.dumps({'text': 'ответ'}).encode())
        if self.path == '/api/speech':
            return self.reply(200, m.wav_bytes(0.1), 'audio/wav')
        self.reply(404)

    def do_GET(self):
        self.reply(200, b'{}')


def serve():
    server = HTTPServer(('127.0.0.1', 0), Fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f'http://127.0.0.1:{server.server_port}'


def test_wav_is_real_pcm_and_multipart_uses_file_field():
    wav = m.wav_bytes(0.5, tone_hz=220)
    assert wav[:4] == b'RIFF' and wav[8:12] == b'WAVE' and len(wav) > 16000
    body, ctype = m.multipart({'interaction_id': 'x'}, 'file', 'voice.wav', wav)
    assert b'name="file"; filename="voice.wav"' in body and ctype.startswith('multipart/form-data; boundary=')


def test_only_loopback_is_allowed():
    assert m.assert_loopback('http://127.0.0.1:8000') == '127.0.0.1'
    for bad in ('http://10.1.2.3:8000', 'http://192.168.0.5', 'http://8.8.8.8'):
        try:
            m.assert_loopback(bad)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_percentiles_use_successes_only_and_flag_small_samples():
    rows = m.summarize([{'stage': 'llm', 'label': 'a', 'temperature': 'repeat_attempt', 'ok': True, 'ms': v} for v in range(1, 101)]
                       + [{'stage': 'llm', 'label': 'a', 'temperature': 'repeat_attempt', 'ok': False, 'ms': 99999}])
    row = rows[0]
    assert (row['p50_ms'], row['p95_ms'], row['failures'], row['minimum_sample_size_met']) == (50, 95, 1, True)
    assert m.summarize([{'stage': 's', 'label': 'a', 'temperature': 'first_attempt', 'ok': True, 'ms': 5}])[0]['minimum_sample_size_met'] is False


def test_http_errors_are_failures_and_stages_are_not_summed():
    server, base = serve()
    try:
        attempts, notes = m.run_measurements(base, 2, m.wav_bytes(0.2, tone_hz=220),
                                             {'short': 'Привет', 'negation': 'Я не хочу доставку'})
    finally:
        server.shutdown()
    assert Fake.seen == {'multipart_ok': True, 'wav_ok': True}
    llm = {(a['label'], a['temperature']): a for a in attempts if a['stage'] == 'llm'}
    assert llm[('short', 'first_attempt')]['ok'] and not llm[('negation', 'repeat_attempt')]['ok'] and llm[('negation', 'repeat_attempt')]['status'] == 502
    assert {a['stage'] for a in attempts} == {'stt', 'llm', 'tts_first_audio', 'tts_total'}
    assert not any(a['stage'] == 'total' for a in attempts)
    assert any('endpointing' in n for n in notes)


def test_loopback_check_rejects_credentials_and_non_http_urls():
    import pytest
    for url in ('http://user:pass@127.0.0.1:8000','file:///tmp/a','https://example.com'):
        with pytest.raises(ValueError): m.assert_loopback(url)


def test_invalid_json_reply_is_a_failed_attempt():
    original=Fake.do_POST
    def handler(self):
        if self.path=='/api/chat':
            self.rfile.read(int(self.headers.get('Content-Length',0)))
            return self.reply(200,b'not json')
        return original(self)
    Fake.do_POST=handler
    server,base=serve()
    try: attempts,_=m.run_measurements(base,1,m.wav_bytes(.1),{'short':'Привет'})
    finally: server.shutdown();Fake.do_POST=original
    assert not next(a['ok'] for a in attempts if a['stage']=='llm')
