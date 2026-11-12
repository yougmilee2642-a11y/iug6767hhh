"""Run against http_smoke_server.py: no browser route interception, actual HTTP API."""
import json
import os
from pathlib import Path
import shutil
import tempfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright, expect

base = os.environ.get('TRACK3_SMOKE_URL', 'http://127.0.0.1:8766')
artifacts = Path(os.environ.get('TRACK3_ARTIFACTS') or tempfile.mkdtemp(prefix='track3-ui-artifacts-'))
slot_day = datetime.now(ZoneInfo('Europe/Minsk')).date() + timedelta(days=7)
while slot_day.weekday() > 4:
    slot_day += timedelta(days=1)
artifacts.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=shutil.which('chromium') or p.chromium.executable_path, headless=True,args=['--no-sandbox'])
    context = browser.new_context(viewport={'width':1440,'height':1000})
    page = context.new_page()
    errors=[]; responses=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('response',lambda r:responses.append((r.request.method, r.url.removeprefix(base),r.status)))
    page.goto(base+'/meetings')
    page.get_by_label('Логин',exact=True).fill('irina');page.get_by_label('Пароль',exact=True).fill('irina-demo')
    page.get_by_role('button',name='Войти',exact=True).click()
    expect(page.get_by_role('heading',name='Обзор',exact=True)).to_be_visible()
    expect(page.locator('.gap-state')).to_contain_text('производственных данных')
    page.get_by_role('button',name='Встречи',exact=True).click();page.get_by_role('button',name='Открыть встречу',exact=True).click()
    page.get_by_label('Тема и цель встречи').fill('HTTP-проверка темы')
    page.get_by_role('button',name='Сохранить тему и участников').click()
    expect(page.locator('#toast')).to_contain_text('Параметры сохранены')
    page.get_by_role('button',name='Вопрос по материалам этой встречи').click()
    page.get_by_label('Ваш вопрос').fill('Когда запуск проекта?')
    page.get_by_role('button',name='Задать вопрос').click()
    expect(page.get_by_role('heading',name='Ответ с источниками')).to_be_visible()
    page.locator('.claim-item .citation-chip').click()
    expect(page.get_by_role('dialog')).to_contain_text('1 декабря 2026 года')
    page.keyboard.press('Escape')
    page.get_by_label('Комментарий').fill('Проверено через реальный HTTP')
    page.get_by_role('button',name='Отправить отзыв').click()
    expect(page.get_by_text('Отзыв отправлен',exact=True)).to_be_visible()
    page.get_by_label('Ваш вопрос').fill('Какой бюджет проекта на 2030 год?')
    page.get_by_role('button',name='Задать вопрос').click()
    expect(page.get_by_role('heading',name='Оснований не найдено')).to_be_visible()
    page.get_by_role('button',name='Встречи',exact=True).click();page.get_by_role('button',name='Открыть встречу',exact=True).click()
    page.get_by_role('button',name='3 · Протокол').click()
    page.locator('.protocol-item').get_by_label('Ответственный',exact=True).fill('Анна')
    page.locator('.protocol-item').get_by_label('Срок словами',exact=True).fill('после согласования')
    page.locator('.protocol-item-select').check()
    page.get_by_role('button',name='Подтвердить выбранные',exact=True).click()
    expect(page.get_by_role('dialog')).to_contain_text('Анна')
    page.get_by_role('button',name='Подтвердить',exact=True).click()
    expect(page.get_by_role('dialog')).to_have_count(0)
    page.get_by_role('button',name='4 · Задачи').click()
    expect(page.get_by_role('button',name='Изменить задачу')).to_be_visible()
    page.get_by_role('button',name='Изменить задачу').click()
    page.get_by_label('Статус задачи').select_option('in_progress')
    page.get_by_role('button',name='Предпросмотр',exact=True).click()
    expect(page.get_by_role('dialog')).to_contain_text('Открыта → В работе')
    page.get_by_role('button',name='Подтвердить',exact=True).click()
    expect(page.get_by_role('dialog')).to_have_count(0)
    expect(page.locator('.task-row.status-in_progress')).to_have_count(1)
    expect(page.locator('.task-row.status-in_progress')).to_contain_text('после согласования')
    stored=context.request.get(base+'/api/meet/tasks').json()['tasks'][0]
    assert stored['due_text']=='после согласования',stored
    page.get_by_role('button',name='1 · Подготовка').click()
    page.get_by_label('Начало поиска').fill(f'{slot_day}T09:00')
    page.get_by_label('Конец поиска').fill(f'{slot_day + timedelta(days=1)}T18:00')
    page.get_by_role('button',name='Загрузить участников').click()
    page.get_by_role('button',name='Найти свободное время').click()
    expect(page.locator('.meet-slots button').first).to_be_visible()
    page.locator('.meet-slots button').first.click()
    expect(page.get_by_role('dialog')).to_contain_text('Europe/Minsk')
    page.keyboard.press('Escape')
    assert not any(path=='/api/meet/calendar/confirm' for _,path,_ in responses)
    with page.expect_response(lambda r:r.url.endswith('/api/meet/calendar/preview')) as pending_preview:
        page.locator('.meet-slots button').first.click()
    preview=pending_preview.value.json()['preview']
    # Another confirmation takes the slot after this browser has reviewed it.
    rival=context.request.post(base+'/api/meet/calendar/preview',data={
        'meeting_id':1,'participant_ids':[person['id'] for person in preview['participants']],
        'start_at':preview['start_at'],'duration_minutes':preview['duration_minutes'],'timezone':preview['timezone']})
    assert rival.status==200,rival.text()
    token=rival.json()['confirmation_id']
    rival_confirm=context.request.post(base+'/api/meet/calendar/confirm',data={
        'confirmation_id':token,'idempotency_key':'http-smoke-rival-confirmation'})
    assert rival_confirm.status==200,rival_confirm.text()
    with page.expect_response(lambda r:r.url.endswith('/api/meet/calendar/confirm')) as conflict:
        page.get_by_role('button',name='Подтвердить',exact=True).click()
    assert conflict.value.status==409
    expect(page.get_by_role('dialog')).to_contain_text('Обновите слоты')
    page.get_by_role('button',name='Обновить слоты').click()
    expect(page.get_by_label('Начало поиска')).to_have_value(f'{slot_day}T09:00')
    page.locator('.meet-slots button').first.click()
    with page.expect_response(lambda r:r.url.endswith('/api/meet/calendar/confirm')) as accepted:
        page.get_by_role('button',name='Подтвердить',exact=True).click()
    assert accepted.value.status==200,accepted.value.text()
    event=accepted.value.json()['event']
    expect(page.get_by_role('dialog')).to_have_count(0)
    expect(page.locator('.meeting-detail-copy > .eyebrow')).to_contain_text(event['start_local'][11:16])
    for width in [360,768,1440]:
        page.set_viewport_size({'width':width,'height':1000})
        assert page.evaluate('document.documentElement.scrollWidth')<=width
        page.screenshot(path=str(artifacts/f'preparation-{width}.png'),full_page=True)
        page.get_by_role('button',name='3 · Протокол').click()
        assert page.evaluate('document.documentElement.scrollWidth')<=width
        page.screenshot(path=str(artifacts/f'protocol-{width}.png'),full_page=True)
        page.get_by_role('button',name='1 · Подготовка').click()
    page.get_by_role('button',name='Выйти',exact=True).click()
    expect(page.get_by_role('button',name='Войти',exact=True)).to_be_visible()
    page.get_by_label('Логин',exact=True).fill('petr');page.get_by_label('Пароль',exact=True).fill('petr-demo')
    page.get_by_role('button',name='Войти',exact=True).click()
    expect(page.get_by_role('heading',name='Обзор',exact=True)).to_be_visible()
    page.get_by_role('button',name='Встречи',exact=True).click()
    expect(page.get_by_role('button',name='Новая встреча')).to_have_count(0)
    assert 'HTTP: Запуск проекта' not in page.locator('#app').inner_text()
    forbidden=context.request.post(base+'/api/meet/meetings',data={'title':'Reader attempt'})
    assert forbidden.status==403,forbidden.text()
    assert not errors,errors
    (artifacts/'http-responses.json').write_text(json.dumps(responses,ensure_ascii=False,indent=2))
    print(json.dumps({'result':'passed','browser_errors':errors,'HTTP_responses':len(responses),'sizes':[360,768,1440],'model':'explicit test double; no Ollama quality claim','real_calendar_conflict':409,'due_words_preserved':True},ensure_ascii=False))
    context.close();browser.close()
