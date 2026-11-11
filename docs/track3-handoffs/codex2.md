# Codex 2 — знания и управленческий обзор

База: `cb2614b86f3b83636e670c83a0afb8f4c9d6c3c3`.
Ветка: `codex/track3-knowledge-overview`.
Рабочая копия: `D:/projects/Callwise-track3-knowledge-overview`.
SHA последней реализации: `8d95b6429600486d378cd9e680ba442dbd7643d9` (включает первоначальную реализацию `3f3307c6d5d6a38e5f338ebb15f3c77591807a0e` и усиление `8f637aa`). Следующий коммит обновляет только этот handoff. [PR №1](https://github.com/yougmilee2642-a11y/iug6767hhh/pull/1).

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

`qa_answers.source_ids` — JSON-массив строк F-id **всех переданных модели фрагментов**, включая не попавшие в claims. `claims` — JSON claims с полными Sources; **только в хранилище** первая claim дополнена `_context_sha256: {F_id: sha256}` для всего контекста (текст, document_id, заголовок, дата, locator). Этот ключ никогда не возвращается API. Перед выдачей весь контекст сверяется: сохранение самой цитаты при изменении окружающего отрицания не позволяет повторно выдать старый ответ. Старые grounded-записи без доказательства целостности требуют нового вопроса (409), без миграции или изменения старой записи. Повреждённые JSON/claims/IDs также дают безопасный 409. `question_masked=''`; хранится только SHA-256 вопроса. `answer_id` — integer из SQLite. Отдельная таблица ссылок не нужна. Заявки на индексы `production_metric_access(user_id,metric_id)` и `production_metrics(scope,as_of)` **закрыты миграцией m008 в ядре Claude**. Витрина должна иметь неотрицательные конечные значения: модуль исключает нарушающие это условие строки с безопасным warning. Проценты не обрезаются до 100; при нулевом знаменателе всегда null.

Нужны `meetings.knowledge.api.router()` и `meetings.management.api.router()` в `meetings.api.install`. Подключение уже реализовано в [PR Claude №2](https://github.com/yougmilee2642-a11y/iug6767hhh/pull/2). Дополнительный `GET /api/meet/qa/{answer_id}`: только автор, повторная проверка встречи, приложений, документов и целостности всего контекста. Заявка feedback **закрыта в коммите Claude `c0d4a396fe817743e6828e20f04606b1027a6f14`**: resolver вызывает `knowledge.service.load_answer`. Отзыв document ACL проверяется и в global, и в meeting режиме; feedback после отзыва → 404. Оценить собственный устаревший ответ (409) ядро позволяет, сам ответ при этом не выдаётся повторно.

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

Явно указанные в кавычках названия — обязательные ограничения до ранжирования и модели. Вопрос о «Вега» не получает бюджет «Орбита» или «Вега Плюс». Название может находиться в заголовке доступного документа; если выдержка сама явно называет другой проект, она также отбрасывается. Это консервативная лексическая защита: переименования, склонения названий и сравнения нескольких проектов могут потребовать уточнённого вопроса, а не произвольного вывода.

Claims намеренно экстрактивные: `text` и `quote` совпадают с точной выдержкой из одного или нескольких соседних полных предложений переданного фрагмента (либо целым фрагментом), 12–1000 символов, с повторной релевантностью вопросу. Модель может нормализовать только пробелы/PDF NBSP/переносы; сервер восстанавливает **оригинальную подстроку хранилища**, включая пробелы. Ни одно слово, знак препинания или отрицание не изменяется. Границы полных предложений не позволяют отрезать «не» внутри предложения. Неизвестный F-id, перефразирование, неподлинная/частичная цитата и дополнительный `answer` модели отбрасываются. Известные инструкции в цитате также отбрасываются; это вспомогательный фильтр, основная защита — отсутствие инструментов и запись только проверенных цитат. Пустые claims → insufficient_data. Сломанная оболочка JSON / timeout / unavailable → 503 model_*. Двойники доказывают работу ограждений, не качество модели.

`source_at` документа — существующий `documents.created_at`, **дата загрузки записи**, поскольку отдельной даты публикации в базе нет. Дата автора не выдумывается. В источнике возвращаются title, F-id, точная цитата и location. Недатированные/naive источники не используются. Поиск лексический: синонимы, сложная морфология, междокументные выводы, OCR/сканы и сложные таблицы не гарантируются; в сомнении отказ/дословный фрагмент. Большие фрагменты, не вмещающиеся целиком в бюджет, пропускаются.

Обзор: `status != done`; просрочка — только валидный YYYY-MM-DD и due строго меньше даты cutoff в Europe/Minsk. Завершённые исключены. KPI — отношение сумм доступных числителей и знаменателей, а не среднее процентов. Последний доступный снимок каждого scope с as_of ≤ cutoff; разные scope не перекрываются. Включается один последний общий период `[period_start,period_end)`, старые периоды не суммируются. Нулевой знаменатель → null + warning. Проценты округляются до 2 знаков, capacity числитель/знаменатель в одной единице мощности.

`overview.as_of` и `source.source_at` KPI — **самый старый из использованных timestamps витрины** (консервативная актуальность), `generated_at` — время расчёта. Старше 48 ч относительно генерации → warning. Нет доступной витрины → только реальные счётчики задач, `as_of:null` и warning. Статусы задач текущие; as_of меняет дату просрочки и срез витрины, не восстанавливает историю задач. Для счётчика source_at — последний updated_at доступного реестра; у пустого реестра время чтения пустого состояния. Данные задач не выдаются за производственный снимок.

Источник агрегата имеет вид `A~<key>~<cutoff_microseconds_UTC>~<observed_microseconds_UTC>~<HMAC-SHA256>`. Подпись связывает **key, UTC cutoff, время наблюдения и полный разрешённый набор строк**: подмена даты не превращает старый источник в другой показатель. Ключ подписи — существующий секрет сессии; идентификатор не содержит названий подразделений/счётчиков. Resolver заново строит доступный набор и проверяет его подпись. Отзыв ACL, изменение задач, изменение/удаление снимка → старый источник 404, без устаревшего кэша. Это ID, не разрешение доступа. Данные старого изменённого набора не хранятся отдельно. У пустого реестра source_at сохраняет **исходное время наблюдения**, а не исторический cutoff или время повторного открытия. Старые ID до усиления подписи перестают открываться — нужно получить новый обзор.

Суммы KPI считаются через стандартный Decimal: несколько конечных очень больших значений не превращаются в Infinity до деления. Если сам процент не представим конечным числом, value=null с warning; экстремальные totals в resolver представлены десятичными строками, обычные — числами. Неверный updated_at старой задачи не ломает реальные счётчики: явное предупреждение о дате. Прямое открытие недатированного task/metric возвращает 409 invalid_source_date, дата не выдумывается.

Каждый ответ расширения, включая ошибки, имеет X-Request-ID. Ошибки типов/длин не отражают входные строки: 422 `{code:"invalid_request",detail:"Проверьте формат и допустимую длину полей запроса."}` и безопасный audit `request.invalid`. Ошибка общего журнала после успешного расчёта явно возвращает 503 audit_unavailable; если одновременно сломалась модель, сохраняется исходный model_timeout/model_* и пишется безопасная диагностическая запись без текста ошибки БД/контекста.

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
Длины, типы, неизвестные поля и нецелый meeting_id (422):
```json
{"code":"invalid_request","detail":"Проверьте формат и допустимую длину полей запроса."}
```
Ошибка записи журнала (503):
```json
{"code":"audit_unavailable","detail":"Не удалось записать результат в журнал. Повторите запрос позже."}
```

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
Агрегат: `{source, data:{metric,numerator,denominator,period_start,period_end,snapshots:[...]}}`. Счётчик задач: `{source,data:{metric,tasks:[Task],evaluated_at,deadline_date}}`. Открытие задачи: `{source:{kind:"task",id:"1",title,source_at,quote,locator:"meeting:1"},data:Task}`; сериализатор `store.task_out`, включая реальную встречу и source_quote. Чужой/отозванный/изменённый ID и unsupported kind → тот же 404 `not_found`; вход и capability — те же 401/403. Источник с неверной датой (409):
```json
{"code":"invalid_source_date","detail":"В источнике нет корректной даты. Требуется обновление данных."}
```

## Проверки и передача

Команды из собственной рабочей копии, отдельный `.venv`; тесты всегда задают временный MEETINGS_DB_PATH, не используют живую SQLite:
```powershell
$track3TestFiles = @('tests/test_track3_knowledge.py', 'tests/test_track3_knowledge_hardening.py', 'tests/test_track3_knowledge_integration.py', 'tests/test_track3_knowledge_ollama.py', 'tests/test_track3_management.py', 'tests/test_track3_management_hardening.py')
.\.venv\Scripts\python.exe -m pytest -q $track3TestFiles tests/test_meetings.py tests/test_meeting_voice.py tests/test_meeting_voice_mode.py tests/test_llm_gateway.py
```
Прогон на базе cb2614b: **113 passed, 11 skipped in 61.34s**; 8 opt-in проверок Ollama и 3 теста feedback/registration без ядра намеренно пропущены. После последней правки даты наблюдения добавлена ещё одна регрессия; весь management-набор: **28 passed in 15.76s**. Никаких новых зависимостей проекта не добавлено.

Проверка интеграции **на неизменяемом коммите**, без записи в рабочую копию Claude. Для воспроизведения уже создан отдельный detached worktree внутри игнорируемого `.venv/core-integration`:
```powershell
git worktree add --detach D:/projects/Callwise-track3-knowledge-overview/.venv/core-integration c0d4a396fe817743e6828e20f04606b1027a6f14
.\.venv\Scripts\python.exe -c "import meetings, pytest; root='D:/projects/Callwise-track3-knowledge-overview/.venv/core-integration'; meetings.__path__.insert(0,root+'/meetings'); raise SystemExit(pytest.main(['-q','tests/test_track3_knowledge.py','tests/test_track3_knowledge_hardening.py','tests/test_track3_knowledge_integration.py','tests/test_track3_management.py','tests/test_track3_management_hardening.py',root+'/tests/test_track3_core.py',root+'/tests/test_track3_calendar.py',root+'/tests/test_meetings.py',root+'/tests/test_meeting_voice.py',root+'/tests/test_meeting_voice_mode.py']))"
```
`git worktree add` выполнять только если этот путь ещё не существует. `install` ядра регистрирует роутеры сам; fixture не подключает их повторно. Проверяются реальные миграции m001–m007, структурированный audit, общий X-Request-ID, отзыв доступа для feedback в global/meeting режимах, календарь и существующие сценарии ядра. **Окончательный результат: 132 passed in 78.67s** на коде `8f637aa` + неизменяемом ядре `c0d4a39`; все последние изменения включены. Перед объединением PR нужно повторить этот набор на выбранном интеграционном SHA; main этой веткой не изменяется.

## Реальная модель: 11.11.2026, qwen2.5:7b

```powershell
$env:TRACK3_REAL_OLLAMA='1'
.\.venv\Scripts\python.exe -c "import meetings, pytest; meetings.__path__.insert(0, 'D:/projects/Callwise-track3-knowledge-overview/.venv/core-integration/meetings'); raise SystemExit(pytest.main(['-q','-s','tests/test_track3_knowledge_ollama.py']))"
```

Результат на зафиксированном ядре Claude: **8 passed in 39.16s**. Семь реальных вызовов MeetingLLM/Ollama; двойника в этих вызовах нет. Один тест дополнительно проверяет два отказа **без** вызова модели. Нормальный pytest без TRACK3_REAL_OLLAMA не требует работающей Ollama и ничего не загружает.

| Контроль | Результат |
|---|---|
| Точный срок запуска, сумма предоплаты, риск шлюза на одиночных источниках | 3 grounded, точные цитаты и даты, сохранённые ответы открываются |
| Документ с инструкцией отменить запуск/удалить файлы | grounded только на исходном факте, команда в ответ не попала |
| Бюджет 2030 при источнике 2026; закрытый бюджет для petr | insufficient_data; 0 вызовов модели |
| Полный исходный demo: запуск, предоплата, риск шлюза | 3 grounded; реальные F1/F11/F5, каждый источник открыт и цитата буквально найдена в хранилище |

В первом реальном прогоне обнаружены и исправлены лишний отказ на условно сформулированную сумму предоплаты и несовместимость с PDF NBSP/выдержкой из соседних предложений. Это проверяемый малый контрольный набор, **не** оценка качества всего релиза или ≥80% извлечения задач; расширенный набор Codex 3 остаётся необходимым.

## Окончательная проверка с обновлённым ядром

Проверена настоящая совместная рабочая копия, без namespace overlay: ядро **`891a9866985264f83ee8cd954e59f372ae8443d1`** + реализация Codex 2 **`8d95b6429600486d378cd9e680ba442dbd7643d9`**. Локальное пробное слияние прошло без конфликтов; merge-коммит не создавался и main не менялся. Включена версия БД **8**, включая заказанные индексы. Все дальнейшие коммиты этого PR до изменения кода — документация.

```powershell
# Создавать копию только если путь ещё не существует.
git worktree add --detach D:/projects/Callwise-track3-knowledge-overview/.venv/combined-check 891a9866985264f83ee8cd954e59f372ae8443d1
git -C D:/projects/Callwise-track3-knowledge-overview/.venv/combined-check merge --no-commit --no-ff 8d95b6429600486d378cd9e680ba442dbd7643d9
Set-Location D:/projects/Callwise-track3-knowledge-overview/.venv/combined-check
$env:TRACK3_REAL_OLLAMA='0'
$env:TRACK3_HTTP_SMOKE='0'
& D:/projects/Callwise-track3-knowledge-overview/.venv/Scripts/python.exe -m pytest -q tests
```

**Полный набор проекта: 838 passed, 23 skipped in 188.90s.** Никакие проваленные тесты не исключались. Пропуски — штатные условия запуска, включая явное включение реальной Ollama/HTTP. Одно предупреждение Starlette об устаревающем alias AnyIO не влияет на результат.

Отдельно на этой же совместной копии:

```powershell
$env:TRACK3_REAL_OLLAMA='1'
& D:/projects/Callwise-track3-knowledge-overview/.venv/Scripts/python.exe -m pytest -q -s tests/test_track3_knowledge_ollama.py
$env:TRACK3_REAL_OLLAMA='0'
$env:TRACK3_HTTP_SMOKE='1'
& D:/projects/Callwise-track3-knowledge-overview/.venv/Scripts/python.exe -m pytest -q -s tests/test_track3_knowledge_http.py
$env:TRACK3_HTTP_SMOKE='0'
```

- **9 passed in 27.09s** на `qwen2.5:7b`: восемь реальных вызовов модели, включая вопрос о явно названном проекте. Отдельный тест проверяет три отказа без вызова модели: чужой документ, отсутствующий год и другое название проекта.
- **HTTP: 1 passed in 11.11s**. Два запуска настоящего uvicorn/FastAPI в отдельных процессах на loopback; временные meetings/business DB и случайный секрет. Проверены вход двух ролей, реальная Ollama, no-store и request ID, сохранение ответа и cookies после перезапуска, версия БД 8, реальные записи audit, разные KPI (10% директору / 100% читателю), запрет открытия скрытого metric, отзыв document ACL → 404 сохранённого ответа/фрагмента/feedback и новый insufficient_data без вызова модели. Дочерние процессы завершаются в finally; живые БД и исходный .env не используются.

### Воспроизводимость окружения

Проверенная собственная `.venv`: FastAPI 0.141.1, Starlette 1.6.0, Pydantic 2.13.5, pytest 9.1.1, httpx 0.28.1, httpx2/httpcore2 2.12.0; SciPy 1.17.1, SoundFile 0.14.0, av 16.1.0. `pip check` → **No broken requirements found**. Файлы зависимостей не изменялись: их владелец Codex 3.

Первый полный прогон на более новых пакетах дал 831 passed / 3 failed. Два падения вызваны отсутствием аудиозависимостей собственного окружения. Третье — изменившийся порядок дублированных cookies в httpx2 2.16.0: тестовый клиент отправлял одновременно поддельную и исходную валидную cookie. Отдельный запрос только с подделкой давал 401; обхода авторизации не обнаружено. После установки требуемых аудиопакетов и совпадения httpx2 с окружением проекта все три теста прошли, затем прошёл полный набор выше. **Заявка Codex 3:** зафиксировать проверенные версии зависимостей в релизном окружении, чтобы обновление тестового клиента не ломало воспроизводимость.

Передача идёт через этот файл и PR согласно README. Изменения только в разрешённых путях. Основная копия/main и чужие незакоммиченные изменения не тронуты. Официальное объединение остаётся за интегратором; UI/микрофон и расширенная релизная оценка — вне пакета Codex 2.
