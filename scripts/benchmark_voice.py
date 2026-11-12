#!/usr/bin/env python3
"""Offline benchmark for local Russian STT. Never uploads audio or prints transcripts by default.

Manifest JSON format: [{"id":"sample-01","audio":"fixtures/01.wav","reference":"Добрый день"}]
Run: python scripts/benchmark_voice.py --manifest tests/voice-fixtures/manifest.json --output voice-benchmark.json
The model and audio fixtures must already exist locally.
"""
from __future__ import annotations
import argparse
import json
import re
import statistics
import sys
import time
import unicodedata
import hashlib
import os
import platform
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))


def normalize(text: str) -> str:
    text = unicodedata.normalize('NFKC', str(text)).lower().replace('ё', 'е')
    return ' '.join(re.findall(r"[а-яa-z0-9]+", text))


def edit_distance(left: list[str], right: list[str]) -> int:
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


def error_rate(reference: str, hypothesis: str, unit: str) -> float:
    if unit not in {'char','word'}: raise ValueError('Unknown metric unit')
    ref = list(normalize(reference)) if unit == 'char' else normalize(reference).split()
    hyp = list(normalize(hypothesis)) if unit == 'char' else normalize(hypothesis).split()
    if not ref:
        return 0.0 if not hyp else 1.0
    return edit_distance(ref, hyp) / len(ref)


def run(manifest: Path, output: Path, include_text: bool = False, transcriber=None, warmup=True) -> dict:
    data = json.loads(manifest.read_text(encoding='utf-8'))
    if not isinstance(data, list) or not data:
        raise ValueError('Manifest must be a non-empty JSON array.')
    seen = set()
    for item in data:
        if not isinstance(item, dict) or not all(k in item for k in ('id', 'audio', 'reference')):
            raise ValueError('Every sample needs id, audio, reference.')
        if not isinstance(item['id'],str) or not item['id'].strip() or len(item['id'])>100 or item['id'] in seen:
            raise ValueError('Sample IDs must be non-empty and unique.')
        if not isinstance(item['audio'],str) or not isinstance(item['reference'],str): raise ValueError('Audio and reference must be strings.')
        seen.add(item['id'])
        audio = (manifest.parent / item['audio']).resolve()
        if not audio.is_file():
            raise FileNotFoundError(f"Audio fixture not found for sample {item['id']}: {audio}")
        item['_audio_path'] = audio
    if output.resolve()==manifest.resolve() or any(output.resolve()==item['_audio_path'] for item in data):
        raise ValueError('Output cannot overwrite manifest or audio.')
    # Lazy import keeps metric tests independent of model dependencies.
    if transcriber is None:
        from services.local_speech import transcribe_local
        transcriber=transcribe_local
    warmup_seconds=None
    if warmup:
        started=time.perf_counter()
        transcriber(data[0]['_audio_path'].read_bytes())
        warmup_seconds=round(time.perf_counter()-started,3)
    rows = []
    word_errors=char_errors=reference_words=reference_chars=0
    for item in data:
        audio_bytes=item['_audio_path'].read_bytes()
        started = time.perf_counter()
        hypothesis = transcriber(audio_bytes)
        elapsed = time.perf_counter() - started
        if not isinstance(hypothesis,str): raise ValueError('Transcriber must return text.')
        ref=normalize(item['reference']); hyp=normalize(hypothesis)
        wc=edit_distance(ref.split(),hyp.split()); cc=edit_distance(list(ref),list(hyp))
        word_errors+=wc;char_errors+=cc;reference_words+=len(ref.split());reference_chars+=len(ref)
        row = {
            'id': item['id'], 'duration_seconds': round(elapsed, 3),
            'wer': round(error_rate(item['reference'], hypothesis, 'word'), 5),
            'cer': round(error_rate(item['reference'], hypothesis, 'char'), 5),
            'reference_words': len(ref.split()),'reference_chars':len(ref),
            'word_errors':wc,'char_errors':cc,'audio_sha256':hashlib.sha256(audio_bytes).hexdigest(),
            'reference_sha256':hashlib.sha256(item['reference'].encode()).hexdigest(),
        }
        if include_text:
            row['reference'] = item['reference']
            row['hypothesis'] = hypothesis
        rows.append(row)
    packages={}
    for package in ('faster-whisper','silero-vad','torch'):
        try: packages[package]=version(package)
        except PackageNotFoundError: packages[package]=None
    result = {
        'benchmark': 'focus_local_stt', 'language': 'ru', 'sample_count': len(rows),
        'wer_mean': round(statistics.mean(r['wer'] for r in rows), 5),
        'cer_mean': round(statistics.mean(r['cer'] for r in rows), 5),
        'latency_seconds_mean': round(statistics.mean(r['duration_seconds'] for r in rows), 3),
        'latency_seconds_p95': round(sorted(r['duration_seconds'] for r in rows)[max(0, int(.95 * len(rows) + .999) - 1)], 3),
        'warmup_seconds':warmup_seconds,'warmup_excluded':warmup,
        'wer_corpus':round(word_errors/reference_words,5) if reference_words else None,
        'cer_corpus':round(char_errors/reference_chars,5) if reference_chars else None,
        'dataset_sha256':hashlib.sha256(json.dumps([{k:r[k] for k in ('id','audio_sha256','reference_sha256')} for r in rows],sort_keys=True).encode()).hexdigest(),
        'environment':{'platform':platform.platform(),'machine':platform.machine(),'processor':platform.processor(),
            'python':platform.python_version(),'packages':packages,'cpu_threads':os.getenv('LOCAL_CPU_THREADS','6'),
            'stt_path':os.getenv('LOCAL_STT_PATH','models/gigaam'),'stt_engine':'tone_gigaam','context':''},
        'measurement':'STT only; excludes end-of-speech, LLM, TTS playback and model warmup by default.',
        'samples': rows,
        'privacy_note': 'Audio processed locally; raw text omitted unless --include-text is set.',
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--output', type=Path, default=Path('voice-benchmark.json'))
    parser.add_argument('--cold-start',action='store_true',help='Include first model load in STT timing; marked in report.')
    parser.add_argument('--include-text', action='store_true', help='Store reference and recognized text in output; use only with synthetic/consented audio.')
    args = parser.parse_args(argv)
    try:
        result = run(args.manifest.resolve(), args.output.resolve(), args.include_text, warmup=not args.cold_start)
    except Exception as exc:
        print(f'Benchmark failed: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 2
    print(json.dumps({k: result[k] for k in ('benchmark','sample_count','wer_mean','cer_mean','latency_seconds_mean','latency_seconds_p95')}, ensure_ascii=False, indent=2))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
