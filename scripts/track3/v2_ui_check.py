"""Photoprint role forms against actual product HTTP; synthetic QA double only."""
import argparse
import json
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def run(artifacts):
    import httpx
    from playwright.sync_api import sync_playwright
    from scripts.track3.seed_fotoprint import seed
    observations = []
    with tempfile.TemporaryDirectory(prefix='fotoprint-v2-browser-') as temp:
        path = Path(temp) / 'ui.db'; ids = seed(str(path))
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
                # A human-authored decision fixture over real APIs; no model extraction.
                with httpx.Client(base_url=base,trust_env=False,timeout=15) as fixture:
                    fixture.post('/api/meet/login',json={'login':'prod_head','password':'prod_head-demo'}).raise_for_status()
                    result = fixture.post('/api/meet/meetings',json={'title':'Браузерная проверка контроля решения','access_user_ids':[ids['users']['operator']]}); result.raise_for_status()
                    decision_meeting = result.json()['meeting']['id']
                    result = fixture.put(f'/api/meet/meetings/{decision_meeting}/transcript',json={'text':'Марина: Решили проверить резерв картона перед запуском Premium.'}); result.raise_for_status()
                    utterance_id = result.json()['utterances'][0]['id']
                    result = fixture.put(f'/api/meet/meetings/{decision_meeting}/protocol',json={'items':[{'kind':'decision','text':'Проверить резерв картона перед запуском Premium','quotes':[{'utterance_id':utterance_id}]}]}); result.raise_for_status()
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
                                assert not errors, {'login':login,'page_errors':errors}
                                if login == 'prod_head':
                                    page.get_by_role('button',name='Встречи',exact=True).click()
                                    page.locator('.meeting-card').filter(has_text='Браузерная проверка контроля решения').get_by_role('button',name='Открыть встречу',exact=True).click()
                                    page.get_by_role('button',name='3 · Протокол',exact=True).click()
                                    page.get_by_role('button',name='Контроль решения',exact=True).click()
                                    editor = page.get_by_role('dialog'); editor.wait_for()
                                    editor.get_by_label('Ответственный за решение',exact=True).select_option(str(ids['users']['operator']))
                                    editor.get_by_label('Срок контроля',exact=True).fill((datetime.now(timezone.utc)-timedelta(days=1)).date().isoformat())
                                    editor.get_by_role('button',name='Предпросмотр',exact=True).click()
                                    preview = page.get_by_role('dialog').filter(has=page.get_by_role('heading',name='Подтвердить контроль решения',exact=True))
                                    preview.wait_for(); preview.get_by_role('button',name='Подтвердить',exact=True).click(); preview.wait_for(state='hidden')
                                    page.get_by_role('button',name='Обзор',exact=True).click()
                                    page.get_by_role('heading',name='Решения на контроле',exact=True).wait_for()
                                if login == 'operator':
                                    page.get_by_role('button', name='Задачи', exact=True).click()
                                    card = page.locator('.task-card').first; card.wait_for()
                                    card.get_by_role('button',name='Изменить задачу',exact=True).click()
                                    dialog = page.get_by_role('dialog'); dialog.wait_for()
                                    assert dialog.get_by_label('Приоритет',exact=True).is_disabled(), 'Employee priority must be read-only'
                                    dialog.get_by_label('Статус задачи',exact=True).select_option('blocked')
                                    dialog.get_by_role('button',name='Предпросмотр',exact=True).click()
                                    preview = page.get_by_role('dialog').filter(has=page.get_by_role('heading',name='Подтвердить изменение задачи',exact=True))
                                    preview.wait_for()
                                    preview.get_by_role('button',name='Отмена',exact=True).click()
                                    preview.wait_for(state='hidden')
                                if login == 'auditor':
                                    page.locator('table').wait_for()
                                    page.get_by_label('Действие',exact=True).fill('login')
                                    with page.expect_response(lambda response:'/api/meet/audit?' in response.url and 'action=login' in response.url):
                                        page.get_by_role('button',name='Применить фильтры',exact=True).click()
                                    assert 'action=login' in page.get_by_role('link',name='Скачать CSV · текущие фильтры',exact=True).get_attribute('href')
                                if login == 'admin':
                                    page.get_by_label('Уровень sales_head', exact=True).wait_for()
                                    assert page.get_by_label('Активен sales_head', exact=True).is_checked(), 'Seeded sales_head should be active'
                                    row = page.get_by_label('Уровень sales_head', exact=True).locator('xpath=ancestor::tr')
                                    row.get_by_role('button', name='Предпросмотр', exact=True).click()
                                    page.get_by_role('dialog').get_by_role('button', name='Отменить', exact=True).click()
                                    page.get_by_role('dialog').wait_for(state='detached')
                                    assert page.get_by_role('dialog').count() == 0, 'Cancelled preview remained open'
                                for width in (360,768,1440):
                                    page.set_viewport_size({'width':width,'height':1000})
                                    geometry = page.evaluate('() => ({width:innerWidth,document_width:document.documentElement.scrollWidth})')
                                    assert geometry['document_width'] <= width + 1, (login, geometry)
                                    page.screenshot(path=str(artifacts / f'{login}-{width}.png'), full_page=True)
                                    observations.append({'login':login, **geometry})
                                assert not errors, {'login':login,'page_errors':errors}
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
    except Exception as error: result = {'status':'failed','error':type(error).__name__,'detail':str(error),'traceback':traceback.format_exc()}; code = 1
    result['elapsed_seconds'] = time.perf_counter() - started
    result['commit'] = subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip()
    result['working_tree_dirty'] = bool(subprocess.check_output(['git','status','--porcelain'], cwd=ROOT, text=True).strip())
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='viewports'}, ensure_ascii=False))
    return code

if __name__ == '__main__': raise SystemExit(main())
