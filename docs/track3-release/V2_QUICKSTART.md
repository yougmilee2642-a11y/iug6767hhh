# Фокус v2 · текущий прототип

Ветка `track3/v2-fotoprint`, draft PR #12. Это промежуточная версия: E0/E1 и
основа E2 реализованы; полный выпуск и все P0 ещё не приняты. Состояние и
проверки: [журнал](../track3-handoffs/agent-v2.md).

## Изолированный текстовый запуск

Python 3.12. Команды ниже — PowerShell из корня репозитория. Отдельный абсолютный
путь вне рабочей `data/` обязателен. Существующая БД без тестового маркера не
перезаписывается. Запуск не скачивает и не прогревает голосовые веса.

```powershell
py -3.12 -m venv .venv-track3
.venv-track3\Scripts\python -m pip install -r requirements-track3-v2-test.txt
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
подтверждение задач, тестовый календарь и обзор из витрин. Генерация протокола и
QA с содержательным ответом требуют заранее подготовленной модели на хосте.
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
.venv-track3\Scripts\python scripts\track3\gen_fotoprint_data.py
.venv-track3\Scripts\python scripts\track3\check.py -q tests --ignore=tests/ui_track3
node --test tests/*.cjs static/mts-shell/tests/*.mjs
.venv-track3\Scripts\python scripts\track3\v2_http_smoke.py --output "$env:TEMP\fotoprint-http.json"
```

HTTP-smoke сам создаёт временную БД, запускает существующее приложение,
проверяет шесть ролей, KPI, cancel/confirm и перезапуск; внешние аккаунты,
модели и GPU не используются. Браузерная проверка:

```powershell
.venv-track3\Scripts\python -m playwright install chromium
.venv-track3\Scripts\python scripts\track3\v2_ui_check.py --output "$env:TEMP\fotoprint-ui.json" --artifacts "$env:TEMP\fotoprint-ui"
```

Локальная среда агента блокирует Unix socket Chromium; CI выполняет эту проверку
на Linux. Результат браузера для нового коммита нельзя считать passed до CI.
