"""Check an isolated checkout/venv, seed and real HTTP; never download model weights.

Run from a committed checkout. Reports are created exclusively outside the repository.
The download cache is not controlled, so timing is not a cold-install benchmark.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
PROFILES = {'base': 'requirements.txt', 'runtime': 'requirements-track3-runtime.txt'}


def sanitized(value):
    return re.sub(r'https?://[^\s<>\"\']+', '[package-source-url]', value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=PROFILES, default='runtime')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output).expanduser().absolute()
    if output.is_relative_to(ROOT) or output.is_symlink():
        parser.error('Report must be a new file outside the checkout')
    # Reserve the file before starting; failed and interrupted runs cannot overwrite evidence.
    with output.open('x', encoding='utf-8'):
        pass
    report = {'status': 'running', 'profile': PROFILES[args.profile], 'steps': [],
              'started_at': datetime.now(timezone.utc).isoformat(), 'platform': sys.platform,
              'python': sys.version, 'actor': 'agent/CI, not an independent human installer',
              'cache': 'uncontrolled; pip may reuse cached wheels', 'models_downloaded': False,
              'live_model_quality': 'not_run'}
    started = time.perf_counter()

    def save():
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def step(name, command, cwd, env, timeout=240):
        begin = time.perf_counter()
        result = subprocess.run(command, cwd=cwd, env=env, capture_output=True,
                                encoding='utf-8', errors='replace', timeout=timeout)
        report['steps'].append({'name': name, 'exit_code': result.returncode,
                               'elapsed_seconds': round(time.perf_counter() - begin, 3),
                               'tail': sanitized(result.stdout + result.stderr).splitlines()[-8:]})
        save()
        print(name, result.returncode, flush=True)
        if result.returncode:
            raise RuntimeError(name + ' failed')
        return result

    try:
        # A fresh checkout is intentional: untracked local helpers and source .env are excluded.
        dirty = subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True)
        if dirty.strip():
            raise RuntimeError('Commit the candidate before checking a clean installation')
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(('MEETINGS_', 'OLLAMA_', 'CALLWISE_', 'TRACK3_'))}
        env.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8', MEETINGS_DEMO='1',
                   CALLWISE_LOCAL_ONLY='true', TELEGRAM_ENABLED='false',
                   CALLWISE_CLOUD_INTEGRATIONS_ENABLED='false',
                   OLLAMA_BASE_URL='http://127.0.0.1:1', OLLAMA_API_KEY='',
                   MEETINGS_TIMEOUT='1', PIP_DISABLE_PIP_VERSION_CHECK='1')
        with tempfile.TemporaryDirectory(prefix='fotoprint-install-') as temporary:
            root = Path(temporary).resolve()
            checkout, venv = root / 'repo', root / 'venv'
            step('clone', ['git', 'clone', '--no-hardlinks', '--', str(ROOT), str(checkout)], root, env)
            report['commit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout, text=True).strip()
            step('venv', [sys.executable, '-m', 'venv', str(venv)], checkout, env)
            python = str(venv / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python'))
            step('install', [python, '-m', 'pip', 'install', '-r', PROFILES[args.profile]], checkout, env)
            step('pip-check', [python, '-m', 'pip', 'check'], checkout, env)
            env['MEETINGS_DB_PATH'] = str(root / 'demo.db')
            first = step('seed', [python, 'scripts/seed_meetings_demo.py'], checkout, env)
            second = step('seed-repeat', [python, 'scripts/seed_meetings_demo.py'], checkout, env)
            if json.loads(first.stdout) != json.loads(second.stdout):
                raise RuntimeError('Repeated seed changed object identifiers')
            try:
                step('http-restart-and-model-503', [python, 'scripts/track3/v2_http_smoke.py',
                     '--unavailable', '--output', str(root / 'http.json')], checkout, env, timeout=120)
            finally:
                if (root / 'http.json').is_file():
                    report['http'] = json.loads((root / 'http.json').read_text(encoding='utf-8'))
                    save()
            inventory = step('inventory', [python, '-c',
                "from importlib import metadata,util; import json; print(json.dumps({"
                "'packages':{d.metadata['Name']:d.version for d in metadata.distributions()},"
                "'optional':{n:util.find_spec(n) is not None for n in "
                "['torch','scipy','av','soundfile','playwright','pytest']}}))"], checkout, env)
            report['inventory'] = json.loads(inventory.stdout)
            forbidden = ['torch', 'scipy', 'av', 'soundfile', 'playwright']
            if args.profile == 'runtime':
                forbidden.append('pytest')
            if any(report['inventory']['optional'][name] for name in forbidden):
                raise RuntimeError('Unexpected model, voice or test package in product profile')
            report['status'] = 'passed'
    except Exception as error:
        report.update(status='failed', error=type(error).__name__, detail=sanitized(str(error)))
    finally:
        report['elapsed_seconds'] = round(time.perf_counter() - started, 3)
        report['within_15_minutes_without_models'] = report['status'] == 'passed' and report['elapsed_seconds'] <= 900
        save()
    print(json.dumps({key: report[key] for key in ['status', 'profile', 'elapsed_seconds']}, ensure_ascii=False))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
