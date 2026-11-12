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



def document_editions(page):
    """Real HTTP/UI, no model inference; upload, cancel, confirm and source diff."""
    page.get_by_role('button', name='Знания', exact=True).click()
    panel = page.locator('details').filter(has=page.get_by_text('Документы · версии и источники', exact=True))
    def expand():
        if not panel.evaluate('element => element.open'):
            panel.locator('summary').click()
    expand()
    page.get_by_label('Добавить документы', exact=True).set_input_files([{
        'name':'browser-edition.txt', 'mimeType':'text/plain',
        'buffer':'Поставка тестового картона состоится 20 ноября. Участок готов.'.encode()}, {
        'name':'browser-guide.md','mimeType':'text/markdown','buffer':'# Памятка\nУчебные файлы не содержат данных клиентов.'.encode()}])
    page.get_by_role('button', name='Загрузить документы', exact=True).click()
    page.get_by_text('Загружено документов: 2', exact=True).wait_for()
    expand()
    page.get_by_label('Фильтр документов по названию', exact=True).fill('browser-edition')
    card = panel.locator('article').filter(has=page.get_by_role('heading', name='browser-edition · версия 1', exact=True))
    card.get_by_role('button', name='Кратко', exact=True).click()
    panel.get_by_text('Выдержки первых пяти подходящих фрагментов; это не полная смысловая сводка.', exact=True).wait_for()
    card.get_by_role('button', name='Новая версия', exact=True).click()
    editor = page.get_by_role('dialog').filter(has=page.get_by_role('heading', name='Загрузить новую версию', exact=True))
    def prepare():
        editor.get_by_label('Файл новой версии', exact=True).set_input_files({
            'name':'browser-edition-v2.txt','mimeType':'text/plain',
            'buffer':'Поставка тестового картона состоится 25 ноября. Участок готов.'.encode()})
        editor.get_by_role('button', name='Предпросмотр', exact=True).click()
    prepare()
    preview = page.get_by_role('dialog').filter(has=page.get_by_role('heading', name='Подтвердить новую версию', exact=True))
    with page.expect_response(lambda r:'/api/meet/confirmations/' in r.url and r.url.endswith('/cancel') and r.status==200):
        preview.get_by_role('button', name='Отмена', exact=True).click()
    card.get_by_role('button', name='Новая версия', exact=True).click()
    editor.get_by_text('Ранее выбран файл: browser-edition-v2.txt. Можно выбрать другой.',exact=True).wait_for()
    editor.get_by_role('button', name='Предпросмотр', exact=True).click()
    preview.get_by_role('button', name='Подтвердить', exact=True).click()
    page.get_by_text('Новая версия сохранена', exact=True).wait_for()
    expand()
    current = panel.locator('article').filter(has=page.get_by_role('heading', name='browser-edition · версия 2', exact=True))
    current.get_by_role('button', name='Версии / сравнить', exact=True).click()
    page.get_by_role('button', name='Сравнить версии', exact=True).click()
    panel.get_by_role('heading', name='Изменения по фрагментам', exact=True).wait_for()
    assert panel.get_by_text('Поставка тестового картона состоится 20 ноября. Участок готов.', exact=True).count()
    assert panel.get_by_text('Поставка тестового картона состоится 25 ноября. Участок готов.', exact=True).count()
    page.get_by_label('Показать заменённые версии', exact=True).check()
    card.wait_for()
    for width in (360,768,1440):
        page.set_viewport_size({'width':width,'height':1000})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1'), ('documents overflow',width)
    page.get_by_role('button', name='Обзор', exact=True).click()
    page.get_by_role('heading', name='Обзор', exact=True).wait_for()


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
                                if login == 'director':
                                    document_editions(page)
                                    page.get_by_role('button',name='Ассистент',exact=True).click()
                                    page.get_by_role('heading',name='Спросить Фокус',exact=True).wait_for()
                                    page.get_by_label('Сообщение ассистенту',exact=True).fill('Что просрочено?')
                                    page.get_by_role('button',name='Спросить Фокус',exact=True).click()
                                    page.locator('[aria-label="Ответы ассистента"] .citation-chip').first.wait_for()
                                    page.get_by_role('button',name='Уведомления',exact=True).click()
                                    page.get_by_role('heading',name='Уведомления',exact=True).wait_for()
                                    page.get_by_role('button',name='Предпросмотр настроек',exact=True).wait_for()
                                    page.get_by_role('button',name='Обзор',exact=True).click()
                                    page.get_by_role('button',name='Брифинг',exact=True).click()
                                    page.get_by_role('heading',name='Брифинг дня',exact=True).wait_for()
                                    page.get_by_role('heading',name='Главные отклонения KPI',exact=True).wait_for()
                                    page.get_by_label('Дата брифинга',exact=True).fill('2026-11-11')
                                    page.get_by_role('button',name='Обновить брифинг',exact=True).click()
                                    page.get_by_role('heading',name='Новые документы за 7 дней',exact=True).wait_for()
                                    page.get_by_role('button',name='Обзор',exact=True).click()
                                    page.get_by_label('Поиск по документам',exact=True).fill('картон')
                                    page.get_by_role('button',name='Найти',exact=True).click()
                                    page.get_by_role('heading',name='Результаты: картон',exact=True).wait_for()
                                    page.locator('.search-result').first.wait_for()
                                    assert page.locator('.search-result').count()>0
                                    page.get_by_role('button',name='Обзор',exact=True).click()
                                    page.get_by_role('heading',name='Обзор',exact=True).wait_for()
                                if login == 'admin':
                                    page.get_by_role('button',name='Хранение данных',exact=True).click()
                                    page.get_by_role('heading',name='Хранение данных',exact=True).wait_for()
                                    page.get_by_role('button',name='Предпросмотр политики',exact=True).wait_for()
                                    page.get_by_role('button',name='Пользователи',exact=True).click()
                                if login == 'prod_head':
                                    page.get_by_role('button',name='Встречи',exact=True).click()
                                    calendar=page.locator('details').filter(has=page.get_by_text('Мой календарь · ICS и приглашения',exact=True))
                                    calendar.locator('summary').click()
                                    payload=(b'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:browser-import\r\n'
                                             b'DTSTART:20261201T060000Z\r\nDTEND:20261201T070000Z\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n')
                                    calendar.get_by_label('Импорт занятости (.ics)',exact=True).set_input_files({'name':'busy.ics','mimeType':'text/calendar','buffer':payload})
                                    calendar.get_by_role('button',name='Предпросмотр импорта',exact=True).click()
                                    import_dialog=page.get_by_role('dialog').filter(has=page.get_by_role('heading',name='Проверить импорт занятости',exact=True))
                                    import_dialog.wait_for()
                                    with page.expect_response(lambda response:'/api/meet/confirmations/' in response.url and response.url.endswith('/cancel') and response.status==200):
                                        import_dialog.get_by_role('button',name='Отмена',exact=True).click()
                                    assert calendar.get_by_label('Импорт занятости (.ics)',exact=True).input_value().endswith('busy.ics')
                                    calendar.get_by_role('button',name='Предпросмотр импорта',exact=True).click();import_dialog.wait_for()
                                    with page.expect_response(lambda response:response.url.endswith('/api/meet/calendar/import/confirm') and response.status==200):
                                        import_dialog.get_by_role('button',name='Подтвердить',exact=True).click()
                                    import_dialog.wait_for(state='hidden')
                                    assert 'Импортировано интервалов: 1' in calendar.inner_text()
                                    calendar.get_by_role('button',name='Создать ссылку подписки',exact=True).click()
                                    subscription_dialog=page.get_by_role('dialog').filter(has=page.get_by_role('heading',name='Создать подписку календаря',exact=True))
                                    subscription_dialog.wait_for();subscription_dialog.get_by_role('button',name='Создать ссылку',exact=True).click();subscription_dialog.wait_for(state='hidden')
                                    assert '/api/meet/calendar/feed/' in calendar.get_by_label('Ссылка подписки (храните как пароль)',exact=True).input_value()
                                    for width in (360,768,1440):
                                        page.set_viewport_size({'width':width,'height':1000})
                                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1'), ('calendar overflow',width)
                                    calendar.get_by_role('button',name='Отозвать ссылки подписки',exact=True).click()
                                    page.get_by_text('Ссылки подписки отозваны.',exact=True).wait_for()
                                    page.get_by_role('button',name='Задачи',exact=True).click()
                                    card=page.locator('.task-card').first;card.wait_for()
                                    card.get_by_role('button',name='Отправить в Битрикс24 · mock',exact=True).click()
                                    crm_dialog=page.get_by_role('dialog').filter(has=page.get_by_role('heading',name='Что уйдёт в Битрикс24 · mock',exact=True))
                                    crm_dialog.wait_for()
                                    with page.expect_response(lambda response:response.url.endswith('/api/meet/crm/confirm') and response.status==200):
                                        crm_dialog.get_by_role('button',name='Подтвердить',exact=True).click()
                                    crm_dialog.wait_for(state='hidden')
                                    page.locator('.task-card').first.get_by_role('button',name='Статус CRM · mock',exact=True).click()
                                    status_dialog=page.get_by_role('dialog').filter(has=page.get_by_role('heading',name='Отправка в Битрикс24 · mock',exact=True))
                                    status_dialog.wait_for()
                                    assert 'Отправлено в локальную имитацию' in status_dialog.inner_text()
                                    status_dialog.get_by_role('button',name='Закрыть',exact=True).click();status_dialog.wait_for(state='hidden')
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
                                    page.get_by_role('button',name='Интеграции',exact=True).click()
                                    with page.expect_response(lambda response:response.url.endswith('/api/meet/integrations/check') and response.status==200):
                                        page.get_by_role('button',name='Проверить соединение',exact=True).click()
                                    page.get_by_role('status').filter(has_text='SQLite-имитация доступна').wait_for()
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
