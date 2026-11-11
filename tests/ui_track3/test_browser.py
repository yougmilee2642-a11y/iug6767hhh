"""Behavioral browser tests, stdlib unittest + the environment's Playwright.
Run: python -m unittest discover -s tests/ui_track3 -p 'test_browser.py' -v
The HTTP fixtures intercept only /api/meet; the actual UI modules run in Chromium.
"""
import functools
import http.server
import os
import shutil
from pathlib import Path
import threading
import unittest

try:
    from playwright.sync_api import sync_playwright, expect
except ImportError:  # optional test tool: without it these scenarios are skipped, never the whole pytest run
    raise unittest.SkipTest('Playwright не установлен: браузерные сценарии track 3 пропущены (pip install playwright)')
from fixtures import FixtureAPI

ROOT = Path(__file__).resolve().parents[2]

class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler = functools.partial(QuietHandler, directory=str(ROOT))
        cls.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(headless=True, executable_path=os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE") or shutil.which("chromium") or cls.pw.chromium.executable_path, args=['--no-sandbox','--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream'])

    @classmethod
    def tearDownClass(cls):
        cls.browser.close(); cls.pw.stop(); cls.server.shutdown(); cls.server.server_close()

    def setUp(self):
        self.api = FixtureAPI()
        self.context = self.browser.new_context(viewport={'width':1440, 'height':1000})
        self.page = self.context.new_page()
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.route('**/api/meet/**', self.api.handle)
        self.page.goto(f'http://127.0.0.1:{self.server.server_port}/static/meetings.html')
        expect(self.page.get_by_role('heading', name='Обзор', exact=True)).to_be_visible()

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])

    def meetings(self):
        self.page.get_by_role('button',name='Встречи',exact=True).click()
        self.page.get_by_role('button',name='Открыть встречу',exact=True).click()
        expect(self.page.get_by_role('heading',name='Параметры и свободное время')).to_be_visible()

    def slots(self):
        self.meetings()
        self.page.get_by_label('Начало поиска').fill('2026-11-18T09:00')
        self.page.get_by_label('Конец поиска').fill('2026-11-19T18:00')
        self.page.get_by_role('button',name='Загрузить участников').click()
        self.page.get_by_role('button',name='Найти свободное время').click()
        self.page.locator('.meet-slots button').first.click()
        expect(self.page.get_by_role('dialog')).to_be_visible()

    def test_calendar_cancel_escape_and_confirm(self):
        self.slots()
        expect(self.page.get_by_role('dialog')).to_contain_text('Europe/Minsk')
        expect(self.page.get_by_role('dialog')).to_contain_text('Тестовые приглашения')
        self.assertEqual(self.api.count('/calendar/confirm'),0)
        self.page.keyboard.press('Escape')
        expect(self.page.get_by_role('dialog')).to_have_count(0)
        self.assertEqual(self.api.count('/calendar/confirm'),0)
        self.page.locator('.meet-slots button').first.click()
        self.page.get_by_role('button',name='Подтвердить',exact=True).click()
        expect(self.page.get_by_role('dialog')).to_have_count(0)
        self.assertEqual(self.api.count('/calendar/confirm'),1)
        payload=next(b for _,p,b in self.api.calls if p=='/calendar/slots')
        self.assertEqual(payload['range_start'], '2026-11-18T06:00:00.000Z')

    def test_calendar_conflict_keeps_form(self):
        self.api.conflict=True; self.slots()
        self.page.get_by_role('button',name='Подтвердить',exact=True).click()
        expect(self.page.get_by_role('dialog')).to_contain_text('Слот уже занят')
        self.page.get_by_role('button',name='Обновить слоты').click()
        expect(self.page.get_by_label('Начало поиска')).to_have_value('2026-11-18T09:00')
        expect(self.page.locator('.meet-slots button')).to_have_count(1)
        self.assertEqual(self.api.count('/calendar/confirm'),1)

    def test_protocol_selected_preview_edits_and_deduplication(self):
        self.meetings(); self.page.get_by_role('button',name='3 · Протокол').click()
        first=self.page.locator('[data-item-id="10"]')
        first.get_by_label('Формулировка').fill('Исправленная задача')
        first.get_by_label('Выбрать').check()
        self.page.get_by_role('button',name='Подтвердить выбранные',exact=True).click()
        expect(self.page.get_by_role('dialog')).to_contain_text('Исправленная задача')
        expect(self.page.get_by_role('dialog')).not_to_contain_text('Проверить релиз')
        self.assertEqual(self.api.count('/meetings/1/protocol/confirm'),0)
        self.page.get_by_role('button',name='Подтвердить',exact=True).click()
        expect(self.page.get_by_role('dialog')).to_have_count(0)
        self.assertEqual(self.api.count('/meetings/1/protocol/confirm'),1)
        self.page.get_by_role('button',name='4 · Задачи').click()
        expect(self.page.locator('#task-1')).to_have_count(1)

    def test_task_cancel_and_explicit_confirmation(self):
        self.page.get_by_role('button',name='Задачи',exact=True).click()
        self.page.get_by_role('button',name='Изменить задачу').click()
        self.page.get_by_label('Статус задачи').select_option('done')
        self.page.get_by_role('button',name='Предпросмотр',exact=True).click()
        expect(self.page.get_by_role('dialog')).to_contain_text('Открыта → Готова')
        self.page.get_by_role('button',name='Отмена',exact=True).click()
        self.assertEqual(self.api.task['status'],'open')
        self.assertEqual(self.api.count('/tasks/1/confirm'),0)
        self.page.get_by_role('button',name='Изменить задачу').click()
        self.page.get_by_label('Ответственный',exact=True).fill('Анна')
        self.page.get_by_role('button',name='Предпросмотр',exact=True).click()
        expect(self.page.get_by_role('dialog')).to_contain_text('Анна')
        self.page.get_by_role('button',name='Подтвердить',exact=True).click()
        expect(self.page.get_by_role('dialog')).to_have_count(0)
        self.assertEqual(self.api.task['assignee'],'Анна')
        self.assertFalse(any(m=='PATCH' and p=='/tasks/1' for m,p,_ in self.api.calls))

    def ask(self):
        self.page.get_by_role('button',name='Знания',exact=True).click()
        self.page.get_by_label('Ваш вопрос').fill('Когда запуск?')
        self.page.get_by_role('button',name='Задать вопрос').click()

    def test_qa_real_source_feedback_and_no_inner_html(self):
        self.api.qa_html=True; self.ask()
        expect(self.page.get_by_role('heading',name='Ответ с источниками')).to_be_visible()
        self.assertEqual(self.page.locator('.claim-item img').count(),0)
        self.assertIsNone(self.page.evaluate('window.injected'))
        expect(self.page.locator('.claim-item')).to_contain_text('<img')
        self.assertNotIn('UNVERIFIED',self.page.locator('#app').inner_text())
        self.page.locator('.claim-item .citation-chip').click()
        expect(self.page.get_by_role('dialog')).to_contain_text('1 декабря 2026')
        self.page.keyboard.press('Escape')
        self.page.get_by_label('Оценка').select_option('incorrect')
        self.page.get_by_label('Комментарий').fill('Проверьте источник')
        self.assertEqual(self.api.count('/feedback'),0)
        self.page.get_by_role('button',name='Отправить отзыв').click()
        expect(self.page.get_by_text('Отзыв отправлен',exact=True)).to_be_visible()
        self.assertEqual(self.api.count('/feedback'),1)

    def test_no_answer_and_server_error_retry(self):
        self.api.qa_empty=True; self.ask()
        expect(self.page.get_by_role('heading',name='Оснований не найдено')).to_be_visible()
        self.api.errors['/qa']=503
        self.page.get_by_role('button',name='Задать вопрос').click()
        expect(self.page.locator('#notice')).to_contain_text('503')
        expect(self.page.get_by_label('Ваш вопрос')).to_have_value('Когда запуск?')
        del self.api.errors['/qa']
        self.page.get_by_role('button',name='Повторить',exact=True).click()
        expect(self.page.get_by_role('heading',name='Оснований не найдено')).to_be_visible()

    def test_overview_null_stale_and_task_link(self):
        expect(self.page.get_by_text('Нет данных',exact=True)).to_be_visible()
        expect(self.page.get_by_text('Производственная витрина устарела.')).to_be_visible()
        expect(self.page.get_by_text('Формула:',exact=False)).to_be_visible()
        self.page.get_by_role('button',name='Открыть задачу во встрече',exact=False).click()
        expect(self.page.get_by_role('heading',name='Поручения и следующие шаги')).to_be_visible()

    def test_reader_role_and_account_switch_clears_private_answer(self):
        self.ask(); expect(self.page.get_by_role('heading',name='Ответ с источниками')).to_be_visible()
        self.page.get_by_role('button',name='Выйти',exact=True).click()
        expect(self.page.get_by_role('button',name='Войти',exact=True)).to_be_visible()
        self.page.get_by_label('Логин',exact=True).fill('petr'); self.page.get_by_label('Пароль',exact=True).fill('petr-demo')
        self.page.get_by_role('button',name='Войти',exact=True).click()
        expect(self.page.get_by_role('heading',name='Обзор',exact=True)).to_be_visible()
        self.page.get_by_role('button',name='Знания',exact=True).click()
        expect(self.page.get_by_label('Ваш вопрос')).to_have_value('')
        expect(self.page.get_by_role('heading',name='Ответ с источниками')).to_have_count(0)
        self.page.get_by_role('button',name='Встречи',exact=True).click()
        expect(self.page.get_by_role('button',name='Новая встреча')).to_have_count(0)
        self.page.get_by_role('button',name='Открыть встречу',exact=True).click()
        expect(self.page.get_by_label('Тема и цель встречи')).to_be_disabled()
        self.page.get_by_role('button',name='2 · Материалы').click()
        expect(self.page.get_by_role('button',name='Начать запись')).to_have_count(0)

    def test_auth_loss_restores_draft_only_same_identity(self):
        self.meetings(); self.page.get_by_label('Тема и цель встречи').fill('Несохранённая тема')
        self.api.errors['/meetings/1']=401
        self.page.get_by_role('button',name='Сохранить тему и участников').click()
        expect(self.page.get_by_role('button',name='Войти',exact=True)).to_be_visible()
        del self.api.errors['/meetings/1']
        self.page.get_by_label('Логин',exact=True).fill('irina'); self.page.get_by_label('Пароль',exact=True).fill('irina-demo')
        self.page.get_by_role('button',name='Войти',exact=True).click()
        expect(self.page.get_by_role('heading',name='Обзор',exact=True)).to_be_visible()
        self.meetings()
        expect(self.page.get_by_label('Тема и цель встречи')).to_have_value('Несохранённая тема')

    def test_responsive_and_native_keyboard_focus(self):
        for width in (360,768,1440):
            self.page.set_viewport_size({'width':width,'height':900})
            self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),width)
        self.slots()
        modal=self.page.get_by_role('dialog')
        self.assertTrue(self.page.evaluate('document.activeElement.closest("dialog") !== null'))
        for _ in range(10): self.page.keyboard.press('Tab')
        self.assertTrue(self.page.evaluate('document.activeElement.closest("dialog") !== null'))
        self.page.keyboard.press('Escape')
        expect(modal).to_have_count(0)
        self.assertTrue(self.page.locator('.meet-slots button').evaluate('(b)=>b===document.activeElement'))

    def test_source_404_clears_previous_text_and_can_retry(self):
        self.ask()
        expect(self.page.get_by_role('heading',name='Ответ с источниками')).to_be_visible()
        self.page.locator('.claim-item .citation-chip').click()
        expect(self.page.get_by_role('dialog')).to_contain_text('1 декабря')
        self.page.keyboard.press('Escape')
        self.api.errors['/fragments/F1']=404
        self.page.locator('.claim-item .citation-chip').click()
        expect(self.page.get_by_role('dialog')).to_contain_text('404')
        expect(self.page.locator('#source-content')).not_to_contain_text('1 декабря')
        del self.api.errors['/fragments/F1']
        self.page.get_by_role('button',name='Повторить',exact=True).click()
        expect(self.page.get_by_role('dialog')).to_contain_text('1 декабря')

    def test_role_revocation_403_keeps_input_and_removes_controls(self):
        self.meetings()
        self.page.get_by_label('Тема и цель встречи').fill('Несохранённый план')
        self.api.errors['/meetings/1']=403
        original=self.api.me
        def reader_me():
            value=original(); value['capabilities']=['meetings.read','calendar.view','qa.ask','overview.read']; return value
        self.api.me=reader_me
        self.page.get_by_role('button',name='Сохранить тему и участников').click()
        expect(self.page.get_by_label('Тема и цель встречи')).to_be_disabled()
        expect(self.page.get_by_label('Тема и цель встречи')).to_have_value('Несохранённый план')
        expect(self.page.locator('#notice')).to_contain_text('прав',ignore_case=True)

    def test_late_qa_cannot_restore_previous_users_answer(self):
        pending=[]
        self.page.route('**/api/meet/qa',lambda route:pending.append(route))
        self.ask()
        expect(self.page.get_by_role('button',name='Формируется ответ…')).to_be_disabled()
        self.page.get_by_role('button',name='Встречи',exact=True).click()
        expect(self.page.get_by_role('button',name='Открыть встречу',exact=True)).to_be_visible()
        self.page.get_by_role('button',name='Выйти',exact=True).click()
        expect(self.page.get_by_role('button',name='Войти',exact=True)).to_be_visible()
        self.page.get_by_label('Логин',exact=True).fill('petr');self.page.get_by_label('Пароль',exact=True).fill('petr-demo')
        self.page.get_by_role('button',name='Войти',exact=True).click()
        expect(self.page.get_by_role('heading',name='Обзор',exact=True)).to_be_visible()
        status,response=self.api.respond('POST','/qa',{'question':'Когда запуск?'})
        self.assertEqual(len(pending),1)
        pending[0].fulfill(status=status,json=response)
        self.page.get_by_role('button',name='Знания',exact=True).click()
        expect(self.page.get_by_role('heading',name='Ответ с источниками')).to_have_count(0)
        expect(self.page.get_by_label('Ваш вопрос')).to_have_value('')

    def test_double_confirm_sends_once(self):
        self.slots()
        self.page.get_by_role('button',name='Подтвердить',exact=True).evaluate('(b)=>{b.click();b.click();b.dispatchEvent(new MouseEvent("click"));}')
        expect(self.page.get_by_role('dialog')).to_have_count(0)
        self.assertEqual(self.api.count('/calendar/confirm'),1)

    def test_create_meeting_explicit_timezone_and_dst_validation(self):
        result=self.page.evaluate('''async () => {
          const {track3UI}=await import('/static/meetings/track3.js');
          const ui=track3UI({state:{capabilities:[]}});
          const check=(v,z)=>{try{return ui.zonedISO(v,z);}catch(e){return 'rejected';}};
          return [check('2026-11-18T09:00','Europe/Minsk'),check('2026-03-29T02:30','Europe/Berlin'),check('2026-10-25T02:30','Europe/Berlin')];
        }''')
        self.assertEqual(result,['2026-11-18T06:00:00.000Z','rejected','rejected'])
        self.page.get_by_role('button',name='Встречи',exact=True).click()
        self.page.get_by_role('button',name='Новая встреча',exact=True).click()
        self.page.get_by_label('Название',exact=True).fill('Новая встреча с зоной')
        self.page.get_by_label('Дата и время',exact=True).fill('2026-11-18T09:00')
        self.page.get_by_role('button',name='Создать встречу',exact=True).click()
        expect(self.page.get_by_role('heading',name='Параметры и свободное время')).to_be_visible()
        body=next(b for m,p,b in self.api.calls if m=='POST' and p=='/meetings')
        self.assertEqual(body['timezone'],'Europe/Minsk')
        self.assertEqual(body['scheduled_at'],'2026-11-18T06:00:00.000Z')

    def test_preview_conflict_refresh_without_losing_input(self):
        self.api.errors['/calendar/preview']=409
        self.meetings()
        self.page.get_by_role('button',name='Загрузить участников').click()
        self.page.get_by_label('Начало поиска').fill('2026-11-18T09:00')
        self.page.get_by_label('Конец поиска').fill('2026-11-19T18:00')
        self.page.get_by_role('button',name='Найти свободное время').click()
        self.page.locator('.meet-slots button').first.click()
        expect(self.page.get_by_role('button',name='Обновить слоты')).to_be_visible()
        self.page.get_by_role('button',name='Обновить слоты').click()
        expect(self.page.get_by_label('Начало поиска')).to_have_value('2026-11-18T09:00')
        self.assertEqual(self.api.count('/calendar/confirm'),0)

    def test_voice_consent_all_speakers_and_editable_draft(self):
        transcriptions=[]
        def transcribe(route):
            transcriptions.append(route.request.post_data_buffer)
            route.fulfill(status=200,json={'text':'План подготовлю завтра.'})
        self.page.route('**/api/transcribe',transcribe)
        self.meetings()
        self.page.get_by_role('button',name='2 · Материалы').click()
        start=self.page.get_by_role('button',name='Начать запись',exact=True)
        expect(start).to_be_disabled()
        self.assertEqual(transcriptions,[])
        self.page.get_by_label('Я подтвердил(а), что все участники согласны').check()
        start.click()
        expect(self.page.get_by_role('button',name='Остановить запись',exact=True)).to_be_visible()
        self.page.wait_for_timeout(400)  # Collect real fake-device PCM frames for the WAV flush.
        self.page.get_by_role('button',name='Остановить запись',exact=True).click()
        expect(self.page.get_by_label('Распознанный текст')).to_have_value('План подготовлю завтра.')
        expect(self.page.locator('.voice-draft-card').get_by_label('Метка говорящего')).to_have_value('Говорящий ?')
        self.page.get_by_label('Распознанный текст').fill('Исправленный текст')
        self.assertEqual(len(transcriptions),1)
        payload=transcriptions[0]
        self.assertIn(b'name="speaker_mode"\r\n\r\nall',payload)
        self.assertIn(b'name="meeting_consent"\r\n\r\ntrue',payload)
        self.assertEqual(self.api.count('/meetings/1/utterances'),0)

    def test_long_protocol_generation_keeps_navigation_and_prevents_duplicate(self):
        pending=[]
        self.page.route('**/api/meet/meetings/1/protocol/draft',lambda route:pending.append(route))
        self.meetings(); self.page.get_by_role('button',name='3 · Протокол').click()
        self.page.get_by_role('button',name='Обновить черновик',exact=True).click()
        expect(self.page.get_by_role('button',name='Выполняется…',exact=True)).to_be_disabled()
        expect(self.page.locator('[data-item-id="10"]').get_by_label('Формулировка')).to_be_disabled()
        self.page.get_by_role('button',name='Встречи',exact=True).click()
        self.page.get_by_role('button',name='Открыть встречу',exact=True).click()
        self.page.get_by_role('button',name='3 · Протокол').click()
        expect(self.page.get_by_role('button',name='Выполняется…',exact=True)).to_be_disabled()
        self.assertEqual(len(pending),1)
        protocol={'items':self.api.items,'summary':[],'warnings':['Генерация завершена']}
        pending[0].fulfill(status=200,json={'protocol':protocol})
        expect(self.page.get_by_role('button',name='Обновить черновик',exact=True)).to_be_enabled()
        expect(self.page.locator('[data-item-id="10"]').get_by_label('Формулировка')).to_be_enabled()
        expect(self.page.get_by_text('Генерация завершена',exact=True)).to_be_visible()

    def test_status_only_change_preserves_due_in_words(self):
        self.api.task.update(due=None,due_text='после согласования',due_status='stated')
        self.page.get_by_role('button',name='Задачи',exact=True).click()
        self.page.get_by_role('button',name='Изменить задачу').click()
        self.page.get_by_label('Статус задачи').select_option('done')
        self.page.get_by_role('button',name='Предпросмотр',exact=True).click()
        expect(self.page.get_by_role('dialog')).to_contain_text('после согласования')
        self.page.get_by_role('button',name='Подтвердить',exact=True).click()
        expect(self.page.get_by_role('dialog')).to_have_count(0)
        body=next(b for _,path,b in self.api.calls if path=='/tasks/1/preview')
        self.assertEqual(body['changes'],{'status':'done'})
        self.assertEqual(self.api.task['due_text'],'после согласования')

    def test_save_meeting_preserves_edits_typed_during_request(self):
        pending=[]
        def hold(route):
            if route.request.method=='PATCH': pending.append(route)
            else: self.api.handle(route)
        self.page.route('**/api/meet/meetings/1',hold)
        self.meetings()
        topic=self.page.get_by_label('Тема и цель встречи')
        topic.fill('Отправленная версия')
        self.page.get_by_role('button',name='Сохранить тему и участников').click()
        expect(self.page.get_by_role('button',name='Выполняется…',exact=True)).to_be_visible()
        topic.fill('Новый несохранённый ввод')
        self.assertEqual(len(pending),1)
        body=pending[0].request.post_data_json
        status,result=self.api.respond('PATCH','/meetings/1',body)
        pending[0].fulfill(status=status,json=result)
        expect(self.page.get_by_role('button',name='Сохранить тему и участников')).to_be_visible()
        expect(self.page.get_by_label('Тема и цель встречи')).to_have_value('Новый несохранённый ввод')
        self.page.get_by_role('button',name='3 · Протокол').click()
        self.page.get_by_role('button',name='1 · Подготовка').click()
        expect(self.page.get_by_label('Тема и цель встречи')).to_have_value('Новый несохранённый ввод')

    def test_calendar_stale_slots_and_participant_selection(self):
        self.slots(); self.page.keyboard.press('Escape')
        self.page.get_by_label('Пётр',exact=True).check()
        expect(self.page.locator('.meet-slots button')).to_have_count(0)
        self.page.get_by_role('button',name='Найти свободное время').click()
        expect(self.page.locator('.meet-slots button')).to_have_count(1)
        self.page.get_by_label('Продолжительность, минут').fill('90')
        expect(self.page.locator('.meet-slots button')).to_have_count(0)
        self.page.get_by_role('button',name='3 · Протокол').click()
        self.page.get_by_role('button',name='1 · Подготовка').click()
        expect(self.page.get_by_label('Пётр',exact=True)).to_be_checked()
        self.page.get_by_role('button',name='Найти свободное время').click()
        expect(self.page.locator('.meet-slots button')).to_have_count(1)
        body=[b for _,path,b in self.api.calls if path=='/calendar/slots'][-1]
        self.assertIn(2,body['participant_ids'])
        self.assertEqual(body['duration_minutes'],90)

    def test_delayed_calendar_slots_do_not_reintroduce_stale_choices(self):
        pending=[]
        self.page.route('**/api/meet/calendar/slots',lambda route:pending.append(route))
        self.meetings()
        self.page.get_by_role('button',name='Загрузить участников').click()
        self.page.get_by_label('Начало поиска').fill('2026-11-18T09:00')
        self.page.get_by_label('Конец поиска').fill('2026-11-19T18:00')
        self.page.get_by_role('button',name='Найти свободное время').click()
        expect(self.page.get_by_role('button',name='Выполняется…',exact=True)).to_be_visible()
        self.page.get_by_label('Продолжительность, минут').fill('90')
        status,result=self.api.respond('POST','/calendar/slots',pending[0].request.post_data_json)
        pending[0].fulfill(status=status,json=result)
        expect(self.page.get_by_role('button',name='Найти свободное время')).to_be_enabled()
        expect(self.page.locator('.meet-slots button')).to_have_count(0)

    def test_logout_waits_before_allowing_new_login(self):
        pending=[]
        self.page.route('**/api/meet/logout',lambda route:pending.append(route))
        self.page.get_by_role('button',name='Выйти',exact=True).click()
        expect(self.page.get_by_role('button',name='Войти',exact=True)).to_be_disabled()
        self.assertEqual(len(pending),1)
        self.assertEqual(self.api.count('/login'),0)
        self.api.user=None
        pending[0].fulfill(status=200,json={})
        expect(self.page.get_by_role('button',name='Войти',exact=True)).to_be_enabled()

    def test_calendar_confirm_success_is_not_retried_when_refresh_fails(self):
        self.slots()
        self.api.errors['/meetings/1']=503
        self.page.get_by_role('button',name='Подтвердить',exact=True).click()
        expect(self.page.get_by_role('dialog')).to_have_count(0)
        expect(self.page.locator('#notice')).to_contain_text('Встреча назначена')
        del self.api.errors['/meetings/1']
        self.page.get_by_role('button',name='Повторить',exact=True).click()
        expect(self.page.locator('#notice')).to_be_hidden()
        self.assertEqual(self.api.count('/calendar/confirm'),1)

    def test_search_only_latest_query_can_update_results(self):
        pending=[]
        self.page.route('**/api/meet/search?**',lambda route:pending.append(route))
        search=self.page.get_by_role('searchbox',name='Поиск по документам')
        search.fill('первый'); self.page.get_by_role('button',name='Найти',exact=True).click()
        search.fill('второй'); self.page.get_by_role('button',name='Найти',exact=True).click()
        self.assertEqual(len(pending),2)
        pending[1].fulfill(status=200,json={'results':[{'id':'F2','document_title':'Второй источник','text':'Второй ответ'}]})
        expect(self.page.get_by_role('heading',name='Второй источник',exact=True)).to_be_visible()
        pending[0].fulfill(status=200,json={'results':[{'id':'F1','document_title':'Первый источник','text':'Первый ответ'}]})
        # A task on the page yields to the fetch continuation before checking the settled DOM.
        self.page.get_by_role('button',name='Встречи',exact=True).focus()
        expect(self.page.get_by_role('heading',name='Второй источник',exact=True)).to_be_visible()
        expect(self.page.get_by_role('heading',name='Первый источник',exact=True)).to_have_count(0)

    def test_source_title_is_removed_on_logout(self):
        self.ask()
        expect(self.page.get_by_role('heading',name='Ответ с источниками')).to_be_visible()
        self.page.locator('.claim-item .citation-chip').click()
        expect(self.page.locator('#source-title')).to_have_text('План запуска')
        self.page.keyboard.press('Escape')
        self.page.get_by_role('button',name='Выйти',exact=True).click()
        expect(self.page.get_by_role('button',name='Войти',exact=True)).to_be_enabled()
        expect(self.page.locator('#source-title')).to_have_text('Цитата')

    def test_protocol_live_warnings_selection_and_exact_preview(self):
        self.api.items[0].update(due_text='до согласования',due_status='stated')
        self.meetings(); self.page.get_by_role('button',name='3 · Протокол').click()
        first=self.page.locator('[data-item-id="10"]')
        first.get_by_label('Ответственный',exact=True).fill('Анна')
        expect(first.locator('.warning-badge.red')).to_have_count(0)
        first.get_by_label('Срок',exact=True).fill('2026-11-25')
        expect(first.get_by_label('Срок словами')).to_have_value('')
        expect(first.get_by_text('Срок: до согласования',exact=False)).to_be_hidden()
        first.get_by_label('Выбрать').check()
        self.page.get_by_role('button',name='2 · Материалы').click()
        self.page.get_by_role('button',name='3 · Протокол').click()
        expect(self.page.locator('[data-item-id="10"]').get_by_label('Выбрать')).to_be_checked()
        self.page.get_by_role('button',name='Подтвердить выбранные',exact=True).click()
        expect(self.page.get_by_role('dialog')).to_contain_text('Анна')
        expect(self.page.get_by_role('dialog')).not_to_contain_text('до согласования')
        self.page.get_by_role('button',name='Подтвердить',exact=True).click()
        expect(self.page.get_by_role('dialog')).to_have_count(0)
        body=next(b for m,p,b in self.api.calls if m=='PUT' and p=='/meetings/1/protocol')
        sent=next(item for item in body['items'] if item['id']==10)
        self.assertEqual(sent['due'],'2026-11-25')
        self.assertIsNone(sent['due_text'])

    def test_empty_protocol_item_does_not_open_confirmation_or_write(self):
        self.meetings(); self.page.get_by_role('button',name='3 · Протокол').click()
        first=self.page.locator('[data-item-id="10"]')
        first.get_by_label('Формулировка').fill('   ')
        first.get_by_label('Выбрать').check()
        self.page.get_by_role('button',name='Подтвердить выбранные',exact=True).click()
        expect(self.page.get_by_role('dialog')).to_have_count(0)
        expect(self.page.locator('#notice')).to_contain_text('Заполните формулировку')
        self.assertEqual(self.api.count('/meetings/1/protocol'),0)
        expect(first.get_by_label('Формулировка')).to_be_focused()

    def test_proposal_outcome_badge_tracks_edit_immediately(self):
        self.api.items[0].update(kind='proposal',outcome='rejected')
        self.meetings(); self.page.get_by_role('button',name='3 · Протокол').click()
        first=self.page.locator('[data-item-id="10"]')
        expect(first.locator('.outcome-badge')).to_have_text('Отклонено')
        first.get_by_label('Исход предложения').select_option('accepted')
        expect(first.locator('.outcome-badge')).to_have_text('Принято')
        first.get_by_label('Исход предложения').select_option('')
        expect(first.locator('.outcome-badge')).to_have_text('Исход не указан')

    def test_custom_speaker_name_draft_survives_tab_change(self):
        self.meetings(); self.page.get_by_role('button',name='2 · Материалы').click()
        self.page.get_by_label('Имя для Говорящий 1',exact=True).select_option('__custom__')
        self.page.get_by_label('Другое имя для Говорящий 1',exact=True).fill('Новый участник')
        self.page.get_by_role('button',name='3 · Протокол').click()
        self.page.get_by_role('button',name='2 · Материалы').click()
        expect(self.page.get_by_label('Имя для Говорящий 1',exact=True)).to_have_value('__custom__')
        expect(self.page.get_by_label('Другое имя для Говорящий 1',exact=True)).to_be_visible()
        expect(self.page.get_by_label('Другое имя для Говорящий 1',exact=True)).to_have_value('Новый участник')

    def test_calendar_preview_cannot_open_after_leaving_meeting(self):
        pending=[]
        self.page.route('**/api/meet/calendar/preview',lambda route:pending.append(route))
        self.meetings()
        self.page.get_by_role('button',name='Загрузить участников').click()
        self.page.get_by_label('Начало поиска').fill('2026-11-18T09:00')
        self.page.get_by_label('Конец поиска').fill('2026-11-19T18:00')
        self.page.get_by_role('button',name='Найти свободное время').click()
        self.page.locator('.meet-slots button').first.click()
        self.page.get_by_role('button',name='Задачи',exact=True).click()
        expect(self.page.get_by_role('button',name='Изменить задачу')).to_be_visible()
        status,result=self.api.respond('POST','/calendar/preview',pending[0].request.post_data_json)
        with self.page.expect_response(lambda r:r.url.endswith('/confirmations/cf_calendar/cancel')):
            pending[0].fulfill(status=status,json=result)
        expect(self.page.get_by_role('dialog')).to_have_count(0)
        self.assertEqual(self.api.count('/calendar/confirm'),0)

    def test_delayed_meeting_does_not_override_task_navigation(self):
        pending=[]
        self.page.route('**/api/meet/meetings/1',lambda route:pending.append(route))
        self.page.get_by_role('button',name='Встречи',exact=True).click()
        self.page.get_by_role('button',name='Открыть встречу',exact=True).click()
        self.page.get_by_role('button',name='Задачи',exact=True).click()
        expect(self.page.get_by_role('button',name='Изменить задачу')).to_be_visible()
        status,result=self.api.respond('GET','/meetings/1',None)
        pending[0].fulfill(status=status,json=result)
        self.page.get_by_role('button',name='Встречи',exact=True).focus()
        expect(self.page.get_by_role('button',name='Изменить задачу')).to_be_visible()
        expect(self.page.get_by_role('heading',name='Параметры и свободное время')).to_have_count(0)

    def test_meeting_times_use_explicit_zone_and_deadline_is_calendar_date(self):
        self.api.meeting['timezone']='Asia/Tokyo'
        self.page.reload()
        expect(self.page.get_by_role('heading',name='Обзор',exact=True)).to_be_visible()
        self.page.get_by_role('button',name='Встречи',exact=True).click()
        expect(self.page.locator('.meeting-date-chip')).to_contain_text('15:00')
        expect(self.page.locator('.meeting-date-chip')).to_contain_text('Asia/Tokyo')
        self.page.get_by_role('button',name='Открыть встречу',exact=True).click()
        expect(self.page.locator('.meeting-detail-copy > .eyebrow')).to_contain_text('15:00')
        expect(self.page.locator('.meeting-detail-copy > .eyebrow')).to_contain_text('Asia/Tokyo')
        other=self.browser.new_context(timezone_id='Pacific/Kiritimati')
        try:
            page=other.new_page();page.route('**/api/meet/**',self.api.handle)
            page.goto(f'http://127.0.0.1:{self.server.server_port}/static/meetings.html')
            expect(page.get_by_role('heading',name='Обзор',exact=True)).to_be_visible()
            page.get_by_role('button',name='Задачи',exact=True).click()
            expect(page.locator('.task-card .task-meta').filter(has_text='Срок:')).to_contain_text('1 нояб.')
        finally:
            other.close()

    def test_slot_retry_uses_edited_range_parameters(self):
        self.meetings();self.page.get_by_role('button',name='Загрузить участников').click()
        self.page.get_by_label('Начало поиска').fill('2026-11-18T09:00')
        self.page.get_by_label('Конец поиска').fill('2026-11-19T18:00')
        self.api.errors['/calendar/slots']=503
        self.page.get_by_role('button',name='Найти свободное время').click()
        expect(self.page.locator('#notice')).to_contain_text('503')
        self.page.get_by_label('Продолжительность, минут').fill('90')
        del self.api.errors['/calendar/slots']
        self.page.get_by_role('button',name='Повторить',exact=True).click()
        expect(self.page.locator('.meet-slots button')).to_have_count(1)
        body=[b for _,path,b in self.api.calls if path=='/calendar/slots'][-1]
        self.assertEqual(body['duration_minutes'],90)

    def test_followup_success_does_not_repeat_creation_on_list_refresh_error(self):
        self.meetings();self.page.get_by_role('button',name='4 · Задачи').click()
        self.page.get_by_role('button',name='Повестка следующей встречи',exact=True).click()
        self.page.get_by_role('button',name='Создать следующую встречу',exact=True).click()
        self.api.errors['/meetings']=503
        self.page.get_by_role('button',name='Подтвердить',exact=True).click()
        expect(self.page.get_by_role('dialog')).to_have_count(0)
        expect(self.page.locator('#notice')).to_contain_text('Встреча создана')
        del self.api.errors['/meetings']
        self.page.get_by_role('button',name='Повторить',exact=True).click()
        expect(self.page.locator('#notice')).to_be_hidden()
        creations=[b for _,path,b in self.api.calls if path=='/meetings/1/next-agenda' and b.get('create_meeting')]
        self.assertEqual(len(creations),1)
