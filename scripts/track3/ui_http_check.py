"""Run the UI owner's browser acceptance against real HTTP handlers and temp DB.

Only inference is an explicit test double from tests/ui_track3/http_smoke_server.py.
This is integration evidence, never a live-model quality measurement.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.track3.reporting import ReportFile


def run(artifacts):
    import httpx
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1', 0))
        port = reserve.getsockname()[1]
    env = {**os.environ, 'TRACK3_SERVER_ROOT': str(ROOT), 'TRACK3_SMOKE_PORT': str(port),
           'TRACK3_SMOKE_URL': f'http://127.0.0.1:{port}', 'TRACK3_ARTIFACTS': str(artifacts)}
    server = None
    before = time.perf_counter()
    with (artifacts / 'server.log').open('w') as log:
        try:
            server = subprocess.Popen([sys.executable, str(ROOT / 'tests/ui_track3/http_smoke_server.py')],
                                      cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + 30
            with httpx.Client(trust_env=False, timeout=1) as client:
                while time.monotonic() < deadline:
                    if server.poll() is not None:
                        raise RuntimeError('isolated_server_exited')
                    try:
                        if client.get(env['TRACK3_SMOKE_URL'] + '/meetings').status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                else:
                    raise RuntimeError('isolated_server_startup_timeout')
            result = subprocess.run([sys.executable, str(ROOT / 'tests/ui_track3/http_browser_smoke.py')],
                                    cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
            (artifacts / 'browser.log').write_text(result.stdout + result.stderr)
            if result.returncode:
                raise RuntimeError('browser_acceptance_failed_see_artifacts')
            summary = json.loads(result.stdout.strip().splitlines()[-1])
            if summary.get('result') != 'passed' or summary.get('browser_errors'):
                raise RuntimeError('invalid_browser_summary')
            return dict(status='passed', model_kind='explicit_test_double', live_model_quality='not_run',
                        elapsed_seconds=time.perf_counter() - before, browser=summary)
        finally:
            if server is not None:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--artifacts', required=True, help='New absolute directory; never an existing user folder')
    args = parser.parse_args()
    artifacts = Path(args.artifacts)
    if not artifacts.is_absolute() or '..' in artifacts.parts or any(p.is_symlink() for p in (artifacts, *artifacts.parents)):
        parser.error('Choose an absolute artifact directory without traversal or symlinks')
    try:
        output = ReportFile(args.output)
        artifacts.mkdir(parents=True, exist_ok=False)
    except (ValueError, FileExistsError) as error:
        parser.error(str(error))
    with output:
        try:
            report = run(artifacts)
        except Exception as error:
            report = dict(status='failed', error_type=type(error).__name__, blocker=str(error),
                          live_model_quality='not_run')
        report.update(artifacts=str(artifacts), observed_at=datetime.now(timezone.utc).isoformat(),
                      commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip())
        output.write(report)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
