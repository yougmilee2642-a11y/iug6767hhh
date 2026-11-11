# Codex 2 — знания и управленческий обзор

База: `cb2614b86f3b83636e670c83a0afb8f4c9d6c3c3`.
Ветка: `codex/track3-knowledge-overview`.
Рабочая копия: `D:/projects/Callwise-track3-knowledge-overview`.
SHA реализации: `3f3307c6d5d6a38e5f338ebb15f3c77591807a0e`; следующий коммит содержит только этот handoff.

## Схема и подключение Claude

Только Claude создаёт миграции общей БД. Модули не создают таблиц сами. Начальная заявка заменена фактическим интерфейсом `m007_knowledge_and_management` из рабочей копии Claude, прочитанным 11.11.2026. Реализация адаптирована к нему; нужна именно эта миграция:

```sql
CREATE TABLE qa_answers (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), meeting_id INTEGER,
 question_masked TEXT NOT NULL, question_sha256 TEXT NOT NULL, status TEXT NOT NULL,
 answer TEXT NOT NULL DEFAULT '', claims TEXT NOT NULL DEFAULT '[]',
 source_ids TEXT NOT NULL DEFAULT '[]', model TEXT, request_id TEXT, generated_at TEXT NOT NULL
);
CREATE INDEX qa_answers_user ON qa_answers(user_id, generated_at);
CREATE TABLE production_metrics (
 id INTEGER PRIMARY KEY, source_id TEXT UNIQUE NOT NULL, owner_id INTEGER REFERENCES users(id),
 scope TEXT NOT NULL, period_start TEXT NOT NULL, period_end TEXT NOT NULL, as_of TEXT NOT NULL,
 completed_orders INTEGER, on_time_orders INTEGER, produced_units INTEGER, defective_units INTEGER,
 available_capacity REAL, occupied_capacity REAL, created_at TEXT NOT NULL
);
CREATE INDEX production_metrics_asof ON production_metrics(as_of);
CREATE TABLE production_metric_access (
 metric_id INTEGER NOT NULL REFERENCES production_metrics(id) ON DELETE CASCADE,
 user_id INTEGER NOT NULL REFERENCES users(id), PRIMARY KEY(metric_id, user_id)
);
```

`as_of` и границы периода — aware ISO 8601, UTC рекомендуется. Scope — стабильный ID производственного подразделения. Одна строка — накопленные показатели одного scope за один период; разные scope в одном периоде не пересекаются. При повторных снимках выбирается последний доступный снимок scope на дату запроса; разные периоды не суммируются. Все сроки задач сохраняют текущую семантику.

`qa_answers.source_ids` — JSON-массив строк F-id **всех переданных модели фрагментов**, включая не попавшие в claims. `claims` — JSON claims контракта с полными Sources. `question_masked=''`; хранится только SHA-256 вопроса. `answer_id` — integer из SQLite. Отдельная таблица ссылок не нужна. Дополнительные индексы-заявки: `production_metric_access(user_id,metric_id)`, `production_metrics(scope,as_of)`; не блокируют функциональность. Витрина должна иметь неотрицательные конечные значения: модуль исключает нарушающие это условие строки с безопасным warning. Проценты не обрезаются до 100; при нулевом знаменателе всегда null.

Подключить `meetings.knowledge.api.router()` и `meetings.management.api.router()` в `meetings.api.install`. Дополнительный `GET /api/meet/qa/{answer_id}`: только автор, повторная проверка встречи, приложений, документов и неизменности цитат. **Заявка Claude для feedback:** использовать `meetings.knowledge.service.load_answer(connection, user['id'], answer_id)` в resolver qa_answer. Проверка только автора/встречи в текущем feedback недостаточна после отзыва document ACL. Это не позволяет читать ответ через наши маршруты, но оставляет интеграционную доработку в чужом модуле.

Аудит через существующий `store.audit(connection, actor, action, **details)`; details: request_id, result, source_ids, model/error_code, object_type/id. Вопросы и контекст не журналируются. Просьба сохранить этот совместимый вызов при расширении audit.

## Codex 3: точный формат fixture

```json
{"source_id":"prod-print-20261111","owner_id":1,"scope":"print","as_of":"2026-11-11T09:00:00+00:00","period_start":"2026-11-01T00:00:00+03:00","period_end":"2026-12-01T00:00:00+03:00","on_time_orders":90,"completed_orders":100,"defective_units":20,"produced_units":1000,"occupied_capacity":60,"available_capacity":80,"created_at":"2026-11-11T09:00:00+00:00","access_user_ids":[2]}
```

`access_user_ids` загружается в `production_metric_access` через возвращённый числовой `production_metrics.id`, остальные поля в `production_metrics`. `source_id` уникален и не начинается с зарезервированного `A~`. Не включать имена скрытых scope в публичные warnings. Владелец также имеет доступ. Источники возвращают ID `source_id`, для агрегата — непрозрачный ID набора строк, resolver повторяет ACL всех участников. `on_time_orders` — физическое имя числителя on_time из ТЗ. Ожидаемые KPI этой строки: 90%, 2%, 75%.

Контрольные вопросы Ollama: «Когда запланирован запуск?» (launch_plan), «Какой размер предоплаты?» (budget), «Какие риски связаны с платёжным шлюзом?» (risk_register), «Какой бюджет на 2030 год?» (отказ). Для petr вопросы к закрытому budget должны давать отказ без передачи материала модели. Формат оценщика: `{question, user_login, meeting_id?, expected_status, expected_document_filenames:[], expected_quote_substrings:[], forbidden_substrings:[]}`. Проверять реальные F-id, точность цитат и отсутствие дополнительных утверждений; двойники не доказывают качество Ollama.

## Маршруты и правила

- `POST /api/meet/qa` — `{question, meeting_id?}`.
- `GET /api/meet/qa/{answer_id}` — повторное открытие собственного ответа с актуальной проверкой прав.
- `GET /api/meet/overview?as_of=<aware ISO>`.
- `GET /api/meet/sources/{kind}/{source_id}` — только `metric` и `task`; для задачи ID — десятичный `tasks.id`. Для document/utterance остаются текущие `/fragments/F…` и `/utterances/U…`.

Общая cookie `cw_meet_user`, общий `MeetError`, общий `store.audit`. С установленным ядром дополнительно вызываются `auth.require(...,'qa.ask'|'overview.read')`. Генерация QA не держит транзакцию во время модели. Перед сохранением `BEGIN IMMEDIATE` и повторная проверка **всего** контекста/встречи/связей документов; изменение данных → 409, отзыв доступа → 404. Сохранённый ответ проверяется при каждом открытии; глобального кэша ответов нет.

QA: существующие fragments и `textutil.norm/words/stem`; ACL в SQL до ранжирования. Стоп-слова вопроса убираются, минимум 50% его значимых основ должно совпасть. Числа/годы вопроса обязательны целиком: вопрос про 2030 не получает ответ про 2026. Сканируются доступные фрагменты, сохраняются лучшие 24 кандидата, модели передаются максимум 8 целых фрагментов, максимум 6000 символов JSON массива документов. Вопрос отдельно до 2000 символов, `num_predict=1800`, максимум 5 claims. Нет кандидатов — модель не вызывается. `MeetingLLM.json` без fallback.

Claims намеренно экстрактивные: `text == quote`, точное полное предложение из переданного фрагмента, 12–1000 символов, повторная релевантность вопросу. Проверка полного предложения не позволяет отрезать «не» внутри него. Неизвестный F-id, перефразирование, неподлинная/частичная цитата и дополнительный `answer` модели отбрасываются. Известные инструкции в цитате также отбрасываются; это вспомогательный фильтр, основная защита — отсутствие инструментов и запись только проверенных цитат. Пустые claims → insufficient_data. Сломанная оболочка JSON / timeout / unavailable → 503 model_*. Двойники доказывают работу ограждений, не качество модели.

`source_at` документа — существующий `documents.created_at`, **дата загрузки записи**, поскольку отдельной даты публикации в базе нет. Дата автора не выдумывается. В источнике возвращаются title, F-id, точная цитата и location. Недатированные/naive источники не используются. Поиск лексический: синонимы, сложная морфология, междокументные выводы, OCR/сканы и сложные таблицы не гарантируются; в сомнении отказ/дословный фрагмент. Большие фрагменты, не вмещающиеся целиком в бюджет, пропускаются.

Обзор: `status != done`; просрочка — только валидный YYYY-MM-DD и due строго меньше даты cutoff в Europe/Minsk. Завершённые исключены. KPI — отношение сумм доступных числителей и знаменателей, а не среднее процентов. Последний доступный снимок каждого scope с as_of ≤ cutoff; разные scope не перекрываются. Включается один последний общий период `[period_start,period_end)`, старые периоды не суммируются. Нулевой знаменатель → null + warning. Проценты округляются до 2 знаков, capacity числитель/знаменатель в одной единице мощности.

`overview.as_of` и `source.source_at` KPI — **самый старый из использованных timestamps витрины** (консервативная актуальность), `generated_at` — время расчёта. Старше 48 ч относительно генерации → warning. Нет доступной витрины → только реальные счётчики задач, `as_of:null` и warning. Статусы задач текущие; as_of меняет дату просрочки и срез витрины, не восстанавливает историю задач. Для счётчика source_at — последний updated_at доступного реестра; у пустого реестра время чтения пустого состояния. Данные задач не выдаются за производственный снимок.

Источник агрегата имеет вид `A~<key>~<cutoff_microseconds_UTC>~<HMAC-SHA256>`. Ключ подписи — существующий секрет сессии; идентификатор не содержит названий подразделений/счётчиков. Resolver заново строит доступный набор и проверяет его подпись. Отзыв ACL, изменение задач, изменение/удаление снимка → старый источник 404, без устаревшего кэша. Это ID, не разрешение доступа. Данные старого изменённого набора не хранятся отдельно.

## JSON: QA

Успех (200; пример ID/даты иллюстративный):
```json
{"answer_id":1,"status":"grounded","answer":"Запуск проекта назначен на 1 декабря 2026 года.","claims":[{"text":"Запуск проекта назначен на 1 декабря 2026 года.","sources":[{"kind":"document","id":"F12","title":"План запуска","source_at":"2026-11-10T09:00:00+00:00","quote":"Запуск проекта назначен на 1 декабря 2026 года.","locator":"абз. 1 (фрагмент 1)"}]}],"sources":[{"kind":"document","id":"F12","title":"План запуска","source_at":"2026-11-10T09:00:00+00:00","quote":"Запуск проекта назначен на 1 декабря 2026 года.","locator":"абз. 1 (фрагмент 1)"}],"generated_at":"2026-11-11T09:00:00+00:00","model":"qwen2.5:7b"}
```
Нет оснований (200; model=null, если поиск пуст):
```json
{"answer_id":2,"status":"insufficient_data","answer":"Недостаточно доступных данных для ответа с проверяемым источником.","claims":[],"sources":[],"generated_at":"2026-11-11T09:00:00+00:00","model":null}
```
Сохранённый ответ — тот же JSON, только собственный и ещё доступный. Чужой/отозванный ответ или встреча (404):
```json
{"code":"not_found","detail":"Не найдено или нет доступа."}
```
Изменившийся источник (409):
```json
{"code":"stale_sources","detail":"Источники изменились. Повторите вопрос."}
```
Ошибка модели (503; аналогично model_unavailable/model_invalid_reply):
```json
{"code":"model_timeout","detail":"Локальная модель не ответила вовремя."}
```
Не установлены миграции хранения QA (503):
```json
{"code":"storage_unavailable","detail":"Хранилище временно недоступно. Проверьте миграции."}
```
Без входа (401):
```json
{"code":"not_authenticated","detail":"Войдите как демо-пользователь."}
```
Недостаточная capability ядра (403):
```json
{"code":"forbidden_role","detail":"Ваша роль не позволяет выполнить это действие."}
```
Пробельный вопрос (422):
```json
{"code":"invalid_question","detail":"Введите вопрос."}
```
Длины и типы проверяет Pydantic/общий handler приложения (422); новых ошибок валидации чужого API модуль не вводит.

## JSON: обзор и источники

Пустой обзор (200):
```json
{"as_of":null,"generated_at":"2026-11-11T09:00:00+00:00","metrics":[{"key":"open_tasks","label":"Открытые задачи","value":0,"unit":"задач","formula":"count(status != 'done'); текущий реестр","source":{"kind":"metric","id":"aggregate-open-id-from-response","title":"Открытые задачи: реестр задач","source_at":"2026-11-11T09:00:00+00:00"}},{"key":"overdue_tasks","label":"Просроченные задачи","value":0,"unit":"задач","formula":"count(status != 'done' AND valid_date(due) < 2026-11-11); Europe/Minsk","source":{"kind":"metric","id":"aggregate-overdue-id-from-response","title":"Просроченные задачи: реестр задач","source_at":"2026-11-11T09:00:00+00:00"}}],"overdue_tasks":[],"summary":[{"text":"Открытые задачи: 0 задач.","sources":[{"kind":"metric","id":"aggregate-open-id-from-response","title":"Открытые задачи: реестр задач","source_at":"2026-11-11T09:00:00+00:00"}]},{"text":"Просроченные задачи: 0 задач.","sources":[{"kind":"metric","id":"aggregate-overdue-id-from-response","title":"Просроченные задачи: реестр задач","source_at":"2026-11-11T09:00:00+00:00"}]}],"warnings":["Производственная витрина не загружена."]}
```
В примерах агрегатные ID — placeholders. Для открытия всегда брать неизменённый `source.id` из реального ответа. При заполненной витрине дополнительно три metrics; пример одной записи (остальные: defect_rate=2, capacity_utilization=75):
```json
{"key":"on_time_orders","label":"Заказы в срок","value":90,"unit":"%","formula":"sum(on_time_orders) / sum(completed_orders) × 100; период [2026-11-01T00:00:00+03:00, 2026-12-01T00:00:00+03:00)","source":{"kind":"metric","id":"aggregate-on-time-id-from-response","title":"Заказы в срок: производственная витрина","source_at":"2026-11-11T09:00:00+00:00"}}
```
Нулевой знаменатель: форма записи сохраняется, `value:null`; в warnings:
```json
["Заказы в срок: значение не рассчитано, знаменатель равен нулю."]
```
Старая витрина: as_of остаётся исходным, generated_at новым, в warnings:
```json
["Производственная витрина устарела: самому старому используемому снимку больше 48 часов."]
```
Недоступные строки полностью исключены до расчёта, без отдельного списка скрытых scope. Наивный/неверный as_of (422):
```json
{"code":"invalid_date","detail":"as_of должен быть ISO 8601 с часовым поясом."}
```
Открытие строки витрины (200):
```json
{"source":{"kind":"metric","id":"prod-print-20261111","title":"Производственный снимок: print","source_at":"2026-11-11T09:00:00+00:00","locator":"[2026-11-01T00:00:00+03:00, 2026-12-01T00:00:00+03:00)"},"data":{"id":1,"source_id":"prod-print-20261111","owner_id":1,"scope":"print","as_of":"2026-11-11T09:00:00+00:00","period_start":"2026-11-01T00:00:00+03:00","period_end":"2026-12-01T00:00:00+03:00","on_time_orders":90,"completed_orders":100,"defective_units":20,"produced_units":1000,"occupied_capacity":60,"available_capacity":80,"created_at":"2026-11-11T09:00:00+00:00"}}
```
Агрегат: `{source, data:{metric,numerator,denominator,period_start,period_end,snapshots:[...]}}`. Счётчик задач: `{source,data:{metric,tasks:[Task],evaluated_at,deadline_date}}`. Открытие задачи: `{source:{kind:"task",id:"1",title,source_at,quote,locator:"meeting:1"},data:Task}`; сериализатор `store.task_out`, включая реальную встречу и source_quote. Чужой/отозванный/изменённый ID и unsupported kind → тот же 404 `not_found`; вход и capability — те же 401/403.

## Проверки и передача

Команды из собственной рабочей копии, отдельный `.venv`; тесты всегда задают временный MEETINGS_DB_PATH, не используют живую SQLite:
```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_track3_knowledge.py tests/test_track3_management.py
.\.venv\Scripts\python.exe -m pytest -q tests/test_meetings.py tests/test_meeting_voice.py tests/test_meeting_voice_mode.py tests/test_llm_gateway.py
```
На 11.11.2026: новые **45 тестов**, базовые **42 passed**, совместный прогон **87 passed in 37.49s**. Затем проверены дополнительные границы SQLite ID и UTC-нормализация даты: **6 passed in 6.12s** на затронутых сценариях. Никаких новых зависимостей проекта не добавлено.

Проверка интеграции **без записи в чужую копию** — импорт ядра Claude через namespace path, свои модули вторым путём; `install` сам регистрирует оба роутера, fixture не подключает их повторно:
```powershell
.\.venv\Scripts\python.exe -c "import meetings, pytest; meetings.__path__.insert(0, 'D:/projects/Callwise-track3-claude/meetings'); raise SystemExit(pytest.main(['-q','tests/test_track3_knowledge.py','tests/test_track3_management.py']))"
```
Окончательный результат: **45 passed in 31.71s** на текущем незакоммиченном срезе Claude, миграции m001–m007 и middleware audit включены; все последние изменения реализации учтены. Это подтверждает фактическую регистрацию и совместимость, но не заменяет повторный запуск на финальном интеграционном SHA. Реальная Ollama в этой проверке не вызывалась; вопросы и формат оценщика переданы выше.

В доступных чатах нет отдельных исполнителей Claude/Codex 3; передача идёт через этот файл и PR согласно README. Изменения только в разрешённых путях. Основная копия/main и чужие незакоммиченные изменения не тронуты.
