"""Photoprint role forms against actual product HTTP; synthetic QA double only."""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def run(artifacts):
    import httpx
    from playwright.sync_api import sync_playwright
    from scripts.track3.seed_fotoprint import seed
    observations = []
    with tempfile.TemporaryDirectory(prefix='fotoprint-v2-browser-') as temp:
        path = Path(temp) / 'ui.db'; seed(str(path))
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        with (artifacts / 'server.log').open('w', encoding='utf-8') as log:
            proc = subprocess.Popen([sys.executable, str(ROOT / 'scripts/track3/v2_http_smoke.py'), '--serve', str(path), '--port', str(port)],
                                    cwd=ROOT, env={**os.environ, 'MEETINGS_DEMO':'1', 'OLLAMA_BASE_URL':'http://127.0.0.1:1'},
                                    stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 25
                while time.monotonic() < deadline:
                    if proc.poll() is not None: raise RuntimeError('Product server exited')
                    try:
                        if httpx.get(base + '/meetings', trust_env=False, timeout=.2).status_code == 200: break
                    except httpx.HTTPError: pass
                    time.sleep(.1)
                else: raise RuntimeError('Server startup timeout')
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(executable_path=shutil.which('chromium') or pw.chromium.executable_path,
                                                 headless=True, args=['--no-sandbox'])
                    try:
                        for login, heading in [('director','Обзор'), ('prod_head','Обзор'), ('operator','Обзор'),
                                               ('designer','Обзор'), ('admin','Администрирование · Пользователи'), ('auditor','Журнал действий')]:
                            context = browser.new_context(viewport={'width':1440, 'height':1000})
                            try:
                                page = context.new_page(); page.set_default_timeout(12000)
                                errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
                                page.goto(base + '/meetings')
                                page.get_by_label('Демо-роль', exact=True).select_option(login)
                                page.get_by_role('button', name='Войти', exact=True).click()
                                page.get_by_role('heading', name=heading, exact=True).wait_for()
                                assert not errors, errors
                                if login == 'admin':
                                    page.get_by_label('Уровень sales_head', exact=True).wait_for()
                                    assert page.get_by_label('Активен sales_head', exact=True).is_checked()
                                    row = page.get_by_label('Уровень sales_head', exact=True).locator('xpath=ancestor::tr')
                                    row.get_by_role('button', name='Предпросмотр', exact=True).click()
                                    page.get_by_role('dialog').get_by_role('button', name='Отменить', exact=True).click()
                                    assert page.get_by_role('dialog').count() == 0
                                for width in (360,768,1440):
                                    page.set_viewport_size({'width':width,'height':1000})
                                    geometry = page.evaluate('() => ({width:innerWidth,document_width:document.documentElement.scrollWidth})')
                                    assert geometry['document_width'] <= width + 1, (login, geometry)
                                    page.screenshot(path=str(artifacts / f'{login}-{width}.png'), full_page=True)
                                    observations.append({'login':login, **geometry})
                                assert not errors, errors
                            finally: context.close()
                    finally: browser.close()
            finally:
                proc.terminate()
                try: proc.wait(timeout=10)
                except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=5)
    return {'status':'passed','viewports':observations,'model_quality':'not_run; scripted QA double', 'admin_preview_cancel':'passed'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True); parser.add_argument('--artifacts', required=True)
    args = parser.parse_args(); artifacts = Path(args.artifacts); artifacts.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    try: result = run(artifacts); code = 0
    except Exception as error: result = {'status':'failed','error':type(error).__name__,'detail':str(error)}; code = 1
    result['elapsed_seconds'] = time.perf_counter() - started
    result['commit'] = subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip()
    result['working_tree_dirty'] = bool(subprocess.check_output(['git','status','--porcelain'], cwd=ROOT, text=True).strip())
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='viewports'}, ensure_ascii=False))
    return code

if __name__ == '__main__': raise SystemExit(main())
