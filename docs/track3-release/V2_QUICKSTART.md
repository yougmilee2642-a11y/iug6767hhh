# Фокус v2 · текущий прототип

Ветка `track3/v2-fotoprint`, draft PR #12. Реализованы данные, роли, защита,
подготовка, поручения, обзор, mock CRM и оценщик v2 на дублёре. Полное ТЗ ещё
не выполнено: [самоаудит](SELF_AUDIT.md), [журнал](../track3-handoffs/agent-v2.md).

## Изолированный текстовый запуск

Python 3.12. Команды ниже — PowerShell из корня репозитория. Отдельный абсолютный
путь вне рабочей `data/` обязателен. Существующая БД без тестового маркера не
перезаписывается. Запуск не скачивает и не прогревает голосовые веса.

```powershell
py -3.12 -m venv .venv-track3
.venv-track3\Scripts\python -m pip install -r requirements-track3-runtime.txt
.venv-track3\Scripts\python -m pip check
$env:MEETINGS_DB_PATH = Join-Path $env:TEMP 'fotoprint-v2-demo\meetings.db'
$env:MEETINGS_DEMO = '1'
$env:CALLWISE_LOCAL_ONLY = 'true'
$env:TELEGRAM_ENABLED = 'false'
$env:CALLWISE_CLOUD_INTEGRATIONS_ENABLED = 'false'
.venv-track3\Scripts\python scripts\seed_meetings_demo.py
.venv-track3\Scripts\python scripts\track3\start.py --db $env:MEETINGS_DB_PATH --port 8000
```

Откройте `http://127.0.0.1:8000/meetings`. Минимальная пара для проверки:
`prod_head / prod_head-demo` и `designer / designer-demo`. Директор:
`director / director-demo`; администратор: `admin / admin-demo`; аудитор:
`auditor / auditor-demo`. Все имена и операции вымышлены. Переключатель демо-ролей
доступен только при `MEETINGS_DEMO=1` и загруженном наборе v2. Legacy-пользователи
`irina`, `petr` и функция старого seed сохранены; CLI-флаг `--legacy` загружает
«Орбиту».

Без LLM работают вход, документы, роли, ручное редактирование протокола,
подтверждение задач, тестовый календарь, mock CRM и обзор из витрин.
Подготовка встречи, генерация протокола и содержательный QA требуют модели.
При недоступной модели API возвращает 503 `model_unavailable` с русским
объяснением; уже сохранённая расшифровка остаётся доступной.
Эта версия не обещает завершить установку и скачивание модели за 15 минут.
Живую Ollama/ASR/TTS агент не запускал; HTTP-проверка использует явный дублёр.

Остановка — `Ctrl+C`. Повторный запуск использует ту же БД и session key.
Повторный seed без reset не создаёт дублей. Если синтетический набор изменился,
seed требует новую БД либо явный сброс:

```powershell
.venv-track3\Scripts\python scripts\seed_meetings_demo.py --reset
```

Эта команда сбрасывает только явно настроенную маркированную демо-БД. Для
просмотра удаления всех объявленных тестовых артефактов сначала dry-run:

```powershell
.venv-track3\Scripts\python scripts\track3\cleanup.py --db $env:MEETINGS_DB_PATH
.venv-track3\Scripts\python scripts\track3\cleanup.py --db $env:MEETINGS_DB_PATH --confirm-delete
```

Рабочая `data/`, симлинки и неопознанные файлы защищены. Нельзя направлять smoke
на пользовательскую БД. Состав хранимых данных и ограничения удаления —
[DATA_POLICY.md](DATA_POLICY.md); расширенный UI хранения v2 ещё запланирован.

## Данные и проверка без моделей

54 документа (замороженные 24 v1 + 30 новых), пять контрольных расшифровок,
отдельная история пяти поручений, 600 заказов, 250 клиентов, 400 обращений.
`demo/track3/v2/manifest.json` и `snapshots.json` — независимые v2-файлы; эталон
v1 не менялся. Цены и финансовые суммы демонстрационные, не публичная оферта.

```powershell
.venv-track3\Scripts\python -m pip install -r requirements-track3-v2-test.txt
.venv-track3\Scripts\python scripts\track3\gen_fotoprint_data.py
.venv-track3\Scripts\python scripts\track3\check.py -q tests --ignore=tests/ui_track3
node --test tests/*.cjs static/mts-shell/tests/*.mjs
.venv-track3\Scripts\python scripts\track3\v2_http_smoke.py --output "$env:TEMP\fotoprint-http.json"
```

HTTP-smoke сам создаёт временную БД, запускает существующее приложение,
проверяет семь уровней ролей, KPI, cancel/confirm и перезапуск; внешние аккаунты,
модели и GPU не используются. Браузерная проверка:

```powershell
.venv-track3\Scripts\python -m playwright install chromium
.venv-track3\Scripts\python scripts\track3\v2_ui_check.py --output "$env:TEMP\fotoprint-ui.json" --artifacts "$env:TEMP\fotoprint-ui"
```

Локальная среда агента блокирует Unix socket Chromium; CI выполняет эту проверку
на Linux. Результат браузера для нового коммита нельзя считать passed до CI.

## Воспроизводимая проверка установки

Из чистого закоммиченного checkout, с новым путём отчёта вне репозитория:

```powershell
python scripts/track3/clean_install.py --profile runtime --output "$env:TEMP\fotoprint-runtime-install.json"
python scripts/track3/clean_install.py --profile base --output "$env:TEMP\fotoprint-base-install.json"
```

Скрипт клонирует текущий commit в новую временную папку, создаёт venv,
устанавливает зависимости, повторяет seed и проверяет семь ролей, сохранность
данных при `503 model_unavailable`, CRM и перезапуск. GPU/модели не вызываются:
адрес провайдера принудительно направлен на закрытый loopback-порт 1.
`base` проверяет требуемый ТЗ `requirements.txt`; `runtime` — фиксированный
текстовый профиль без pytest/Playwright/ASR. Кэш pip не отключён: время нельзя
выдавать за холодную установку. Windows CI проверяет установку на runner,
но не заменяет проверку микрофона и моделей на компьютере хоста.

## Ассистент, контроль и экспорт (срез E3/E4/E8/E10–12)

В верхней панели доступны «Ассистент», уведомления, хранение и запрос удаления
своих данных; доступ зависит от capability. Ассистент по умолчанию детерминирован:
разрешённые документы/протоколы/задачи/KPI/заказы/обращения/календарь/брифинг.
Каждый ответ имеет проверяемый источник. `MEETINGS_ASSISTANT_MODEL_ROUTER=1`
включает только JSON-выбор разрешённого tool и серверного кандидата; содержимое
ответа всё равно проверяется. История личная, источники перепроверяются.

«Поставь задачу» в чате или голосе открывает проект действия. В форме уточните
встречу-основание, владельца и срок, проверьте preview, затем подтвердите. Ручное
поручение явно помечено и не выдаётся за слова участника стенограммы. Изменение
статуса и встреча без приглашений также требуют preview/confirm.

Во встрече доступны комментарии/история задач, подтверждение перетаскивания
статуса, экспорт подтверждённого протокола MD/HTML для печати, локальная
рассылка через preview. Письма EML создаются в DB-parent/outbox либо
`MEETINGS_OUTBOX_DIR`; никаких реальных отправок.

`MEETINGS_PUBLIC_ORIGIN` задаёт единственный Origin браузерного API, если он
отличается от адреса сервера. UI передаёт `X-Focus-Request:1`; cross-site мутации
блокируются. `MEETINGS_RATE_LIMIT_LOGIN` (30/min) и `MEETINGS_RATE_LIMIT_QA`
(60/min) — лимиты на адрес, значения1..10000. CSP использует только self, Jost
включён локально с OFL. Параметры хранения: «Хранение» → preview → confirm.

### Изолированная проверка адаптеров

Default: CRM `bitrix24-mock`, календарь `mock`. Никаких аккаунтов не требуется.
Транспортные тесты: `pytest -q tests/test_track3_bitrix.py tests/test_track3_calendar_providers.py`.
Они используют только httpx.MockTransport и синтетические `portal.invalid` ответы.

Контракт Bitrix включается `MEETINGS_BITRIX_ENABLED=1`, HTTPS-webhook задаётся
в окружении `MEETINGS_BITRIX_WEBHOOK` (не в git). Календарь отдельно:
`MEETINGS_CALENDAR_PROVIDER=bitrix24`; без маппинга всех участников подтверждение
запрещено. Администратор: Интеграции → сотрудники → preview/confirm маппинга;
роли/отделы/ACL автоматически не изменяются. `MEETINGS_BITRIX_ENTITY_MAP` —
owner-managed JSON `{"contacts":{"client-0001":"41"},"deals":{"deal-0001":"42"}}`.
Локальная витрина проверяет scope до запроса; имена/телефоны/адреса контакта
не выдаются. ERP и Mary остаются scoped локальными витринами.

После таймаута календаря ответ503/uncertain, повтор не отправляет запрос.
Слот остаётся заблокированным, ICS отмечен TENTATIVE, приглашений нет. Проверьте
результат у администратора портала; не удаляйте outbox для обхода защиты.
CalDAV/Exchange — явные disabled заготовки; Google-calendar ещё не подключён
к track3 (существующий booking адаптер не означает готовность этого экрана).
На новых task cards Bitrix `task.commentitem.getlist` может не поддерживаться;
в таком случае экспорт протокола завершается ошибкой без записи, слепого
fallback нет. Для нового chat API требуется отдельный adapter.
