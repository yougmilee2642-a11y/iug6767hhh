# Handoff Claude — ядро встреч, роли, календарь

Ветка `claude/track3-core-calendar`, база `cb2614b86f3b83636e670c83a0afb8f4c9d6c3c3`. SHA коммитов — в PR (последний коммит ветки).

## Изменённые пути (только своя зона)

- `meetings/migrations/__init__.py` — версионированные миграции (`PRAGMA user_version`), новое.
- `meetings/store.py` — применение миграций, aware-время, расширенный `audit`, `audit_independent`, `write_tx`, `safe_text`.
- `meetings/auth.py` — роли и capabilities, `MeetError(..., audit=)`, `require/forbidden`.
- `meetings/confirmations.py` — общий механизм preview → confirm, новое.
- `meetings/calendar/{__init__,service,api}.py` — тестовый календарь, новое.
- `meetings/feedback.py` — обратная связь, новое.
- `meetings/api.py` — проверки ролей/ACL на всех маршрутах, аудит отказов, request id, задачи preview/confirm, open_tasks в подготовке, регистрация роутеров.
- `meetings/extract.py` — `kind: risk`, `summary` с проверкой.
- `tests/test_meetings.py` (двойник модели знает summary; PATCH задачи → preview/confirm), `tests/test_track3_core.py`, `tests/test_track3_calendar.py` — новые.

`app.py`, frontend, seed, данные, `meetings/llm.py`, `meetings/knowledge/`, `meetings/management/` не трогал.

## Роли (ОТ-02)

`users.role` остаётся должностью; новый столбец `users.access_role`: `manager` (irina) | `reader` (petr, по умолчанию для новых).

| capability | reader | manager |
|---|---|---|
| `meetings.read`, `prep.generate`, `calendar.view`, `qa.ask`, `overview.read`, `feedback.create` | ✓ | ✓ |
| `meetings.create`, `meetings.edit`, `meetings.share`, `documents.upload`, `documents.share`, `transcript.edit`, `protocol.edit`, `protocol.confirm`, `tasks.change`, `calendar.invite`, `audit.read` | — | ✓ |

Порядок проверки: сначала ACL объекта (чужой/нет → `404 not_found`), затем capability (`403 forbidden_role`). Capability никогда не открывает чужой объект. Изменение `access_user_ids` — только владелец с `meetings.share` (`403 owner_only` для доступного по ACL, но не своего). Пётр — reader, поэтому не может править даже свою встречу «Синк по дизайну».

`GET /api/meet/me` (совместимо: старое поле `user` сохранено и расширено):
```json
{"user": {"id": 2, "login": "petr", "name": "Пётр Смирнов", "role": "Подрядчик (дизайн)", "access_role": "reader",
          "capabilities": ["meetings.read", "prep.generate", "calendar.view", "qa.ask", "overview.read", "feedback.create"]},
 "capabilities": ["…то же…"], "role": {"key": "reader", "label": "Чтение и обратная связь"}, "timezone": "Europe/Minsk"}
```

Для Codex 2: `from meetings.auth import require, has_capability` — `require(user, 'qa.ask', action='qa.ask')`; `current_user(request)` теперь возвращает `access_role`.

## Миграции (`meetings/migrations`)

Базовая схема `store.SCHEMA` заморожена как версия 0. Шаги применяются при первом открытии БД, каждый в `BEGIN IMMEDIATE`; упавший шаг откатывается целиком.

| v | что |
|---|---|
| 1 | `users.access_role` (irina → manager) |
| 2 | `audit`: `request_id, object_type, object_id, result, source_ids, confirmation_id, model, error_code` + индексы |
| 3 | `meetings.version`, `meetings.scheduled_at_legacy`, `tasks.version`, `protocols.summary`; старые naive `scheduled_at` → UTC по **Europe/Minsk** (не по зоне ОС); нераспознаваемый текст переносится в `scheduled_at_legacy` |
| 4 | `confirmations` |
| 5 | `calendar_busy`, `calendar_events`, `calendar_event_participants`, `calendar_outbox` |
| 6 | `feedback` |
| 7 | для Codex 2: `qa_answers`, `production_metrics`, `production_metric_access` |
| 8 | индексы по заявке Codex 2: `production_metric_access(user_id, metric_id)`, `production_metrics(scope, as_of)` |

Проверено на копии реальной локальной `data/meetings.db` (версия 0): после миграции версия 7 (до добавления шага 8), число строк в `users/meetings/documents/utterances/tasks/audit/protocol_items` не изменилось (2/3/4/10/1/8/5), `2026-11-12T10:00` → `2026-11-12T07:00:00+00:00`.

### Таблицы для Codex 2 (согласовано: `docs/track3-handoffs/codex2.md` в их ветке использует шаг 7 без изменений)

- `qa_answers(id, user_id, meeting_id, question_masked, question_sha256, status, answer, claims JSON, source_ids JSON, model, request_id, generated_at)` — ответ хранить с ID источников; перед повторной выдачей заново проверять ACL каждого источника. Маскирование вопроса — `store.safe_text(question)`.
- `production_metrics(id, source_id UNIQUE, owner_id, scope, period_start, period_end, as_of, completed_orders, on_time_orders, produced_units, defective_units, available_capacity, occupied_capacity, created_at)` + `production_metric_access(metric_id, user_id)` — ACL как у документов (владелец или строка доступа). `as_of` — aware ISO.
- Запрошенные индексы добавлены шагом 8. Дальнейшие изменения — новым шагом через handoff.

### Для Codex 3 (seed/данные)

- Пользователи: при вставке указывать `access_role` (`manager|reader`).
- Время встреч и занятости — только aware ISO (`2026-11-20T10:00:00+03:00`). Занятость добавлять через `meetings.calendar.service.add_busy(connection, user_id, start, end, title)`; naive отклоняется.
- Существующий `scripts/seed_meetings_demo.py` пишет naive `scheduled_at`; API читает такие значения как Europe/Minsk (тот же документированный принцип, что и миграция 3), но в новом seed лучше писать с offset.

## Аудит (AI-06, §7.5)

`store.audit(connection, user_id, action, **details)` — сигнатура прежняя; ключи `object_type, object_id, result, source_ids, confirmation_id, model, error_code` идут в столбцы, остальное — в `details`, `request_id` добавляется автоматически (заголовок `X-Request-ID` принимается/возвращается). Заголовки чужих объектов, полный промпт и токены в журнал не пишутся; вопросы/поиск — `store.safe_text` (цифры и e-mail маскированы, длина и короткий хеш).

Отказы: `MeetError(..., audit={...})` записывается обработчиком ошибок **в отдельной транзакции после отката** основной — проверено тестом (`test_denial_survives_rollback_of_the_main_transaction`). Внутри открытой write-транзакции не вызывайте `audit_independent` напрямую — поднимите `MeetError` с `audit`.

AI-цепочка: `ai_prepare` и `protocol_draft` пишут `source_ids` (переданные в модель F/U id), `cited_ids`, `model`, `stage` (`draft` при ошибке модели с `error_code=model_*`, `result` при успехе); подтверждения — `calendar_preview/calendar_confirm/task_change_preview/task_update/confirmation_cancelled` с общим `confirmation_id`; `task_confirmed` с `source_ids` цитат. `GET /api/meet/audit?limit=` — свой журнал (manager).

## Подтверждения (AI-03)

Preview → `{confirmation_id, expires_at (15 мин), preview}`; confirm принимает только `{confirmation_id, idempotency_key}` (`extra=forbid`, подмена полей → 422). Токен привязан к пользователю, действию, объекту и версии. Confirm идёт в `BEGIN IMMEDIATE`: повтор/гонка → `already_confirmed: true` с тем же результатом. Коды: `404 confirmation_not_found` (чужой/не тот объект), `409 stale`, `409 slot_taken`, `409 confirmation_cancelled`, `409 confirmation_expired`, `409 idempotency_key_reused`. Отмена: `POST /api/meet/confirmations/{id}/cancel` (или `/calendar/cancel`) — целевой объект не меняется.

### Задачи

- `PATCH /api/meet/tasks/{id}` → после проверки ACL/роли `409 confirmation_required` (обхода нет).
- `POST /api/meet/tasks/{id}/preview` `{"changes": {"status"?, "assignee"?, "due"?}}` →
```json
{"confirmation_id": "cf_…", "expires_at": "2026-11-11T11:25:59+00:00",
 "preview": {"task_id": 1, "meeting_id": 1, "text": "Подготовить оценку рисков…",
             "before": {"status": "open", "assignee": "Анна Ковалёва", "due": "2026-11-20"},
             "after": {"status": "in_progress", "assignee": "Анна Ковалёва", "due": "2026-11-25"},
             "changes": {"status": {"from": "open", "to": "in_progress"}, "due": {"from": "2026-11-20", "to": "2026-11-25"}},
             "version": 1}}
```
- `POST /api/meet/tasks/{id}/confirm` `{confirmation_id, idempotency_key}` → `{task, already_confirmed, confirmation_id}`. Смена `due` очищает `due_text` (исходная цитата остаётся в `source_quote`).
- `/protocol/confirm` не менялся, идемпотентен (требует `protocol.confirm`).
- Правки исходного транскрипта (`PATCH /utterances/{id}`, `PUT /transcript`) остаются явными действиями пользователя; сервер их сам не вызывает.

## Календарь (§7.2.2), provider `mock`

Интервалы `[start, end)`, шаг 15 мин, рабочие часы по умолчанию 09:00–18:00 пн–пт в указанной зоне, до 31 дня, до 20 слотов. Организатор автоматически входит в участники. Названия чужой занятости не возвращаются.

- `GET /api/meet/calendar/participants` → тестовый справочник `{participants: [{id, name}]}`.
- `POST /api/meet/calendar/slots` `{participant_ids, range_start, range_end, duration_minutes, timezone="Europe/Minsk", work_start?, work_end?, include_weekends?}` →
```json
{"slots": [{"start_at": "2026-11-18T06:00:00+00:00", "end_at": "2026-11-18T07:00:00+00:00",
            "start_local": "2026-11-18T09:00+03:00", "end_local": "2026-11-18T10:00+03:00"}, "…"],
 "timezone": "Europe/Minsk", "participants": [{"id": 1, "name": "Ирина Власова"}, {"id": 2, "name": "Пётр Смирнов"}],
 "duration_minutes": 60, "step_minutes": 15, "provider": "mock"}
```
  Пусто — `"slots": []`. Naive дата → `422 naive_datetime`; неизвестный ID → `422 unknown_participant`.
- `POST /api/meet/calendar/preview` `{meeting_id, participant_ids, start_at (с offset), duration_minutes, timezone?}` → `{confirmation_id, expires_at, preview: {meeting_id, title, start_at, end_at, timezone, start_local, end_local, duration_minutes, participants, invitations: [{recipient_id, recipient_name, channel: "local_outbox", subject, body, has_meeting_access}], provider: "mock", warnings}}`. Ошибки: `403 forbidden_role` (reader), `404` (чужая встреча), `409 slot_taken`, `422 slot_in_past`.
- `POST /api/meet/calendar/confirm` → `{event: {id, meeting_id, title, start_at, end_at, timezone, start_local, end_local, organizer_id, participants, provider, status, created_at}, invitations: [{…, status: "queued_local"}], already_confirmed}`. Повторно проверяются ACL, роль, версия встречи (`409 stale`) и занятость (`409 slot_taken`); встрече проставляется `scheduled_at`.
- `GET /api/meet/calendar/events`, `GET /api/meet/calendar/outbox` (`delivery: "local_outbox_only"`). Приглашённому без доступа к встрече название не показывается («Встреча (нет доступа к материалам)», тема письма «Приглашение на встречу»); приглашение не выдаёт ACL. Реальных писем нет (тест подменяет `smtplib.SMTP` на ошибку).

## Протокол: risk и summary (§7.2.3)

- `items[].kind` теперь также `"risk"` (`KIND_RU['risk'] = 'Риск'`), проверяется как decision/task: без подтверждающей цитаты → отброшено с предупреждением.
- `protocol.summary: [{text, status: "verified"|"needs_clarification", quotes: [{utterance_id, speaker, text, verified}], note, source: "model"|"items"}]`. Утверждения строятся только по проверенным пунктам; без цитаты, без опоры в формулировке или с «решили» про непринятое предложение — `needs_clarification`, `note: "требует уточнения: …"`. Если модель не ответила на резюме — детерминированное резюме из пунктов + предупреждение. `OUTCOME_RU`: принято/отклонено/обсуждалось.

## Подготовка (§7.2.1)

`prep.open_tasks: Task[]` (+ `source: {kind:"task", id:"T1", title, source_at, quote, locator}`) и `prep.task_questions: [{text, task_id, sources}]` — незакрытые задачи доступных предыдущих встреч по цепочке `followup_of` (до 5). Отдельно от `brief` (фактов документов), в модель не передаются, при каждом GET пересчитываются для текущего зрителя.

## Feedback (AI-07)

`POST /api/meet/feedback` `{meeting_id?, answer_id?, target_type: meeting|prep|protocol_summary|protocol_item|task|qa_answer|utterance, target_id, rating: useful|incorrect, comment? (≤1000)}` → `{"feedback_id": 1}`. Недоступная цель или несовпадающий `meeting_id` → `404` (+аудит); `qa_answer` оценивает только автор; если модуль знаний доставлен, дополнительно вызывается `meetings.knowledge.service.load_answer(connection, user_id, answer_id)` (заявка Codex 2: повторная проверка ACL источников; его 404 → наш 404, 409 stale_sources допускает отзыв). `GET /api/meet/feedback` — только свои.

## Время (ОТ-07)

`store.now()` — UTC. `POST/PATCH /meetings`: `scheduled_at` с offset, либо без offset + явный `timezone` (`"Europe/Minsk"`); иначе `422 naive_datetime`. Ответ: `scheduled_at` в UTC с `+00:00`, `timezone: "Europe/Minsk"`, `version`.

## Роутеры Codex 2

`install` подключает `meetings.calendar`, `meetings.feedback` и, если пакеты существуют, `meetings.knowledge.api.router()` и `meetings.management.api.router()`. Отсутствующий модуль пропускается; если модуль есть, но падает при импорте — ошибка не скрывается. В `app.py` ничего добавлять не нужно.

Пробное слияние с `codex/track3-knowledge-overview` (3376ecf) во временном worktree, без push: конфликтов нет; `tests/test_track3_*.py` (обе команды) + `test_meetings.py` + voice → **102 passed**; через `install` реально отвечают `GET /api/meet/overview` (200) и `POST /api/meet/qa` (200, `insufficient_data` на «бюджет на 2030 год» для petr); БД на версии 8.

## Что нужно от Codex 1 (UI) — блокирует сценарии в браузере

1. Создание встречи: передавать `timezone: "Europe/Minsk"` вместе со значением `datetime-local` (`static/meetings.js:423`), иначе сейчас 422.
2. Статус задачи: `meetings.js:1365` использует PATCH → теперь `409 confirmation_required`. Перейти на preview → показ `before/after` → confirm (`idempotency_key` — случайный на одну попытку) / cancel.
3. Протокол: `meetings.js:1144/1189` не знают `risk` — добавить группу «Риски» и подпись «Риск»; вывести `protocol.summary` с цитатами и пометкой «требует уточнения».
4. Подготовка: показать `open_tasks` и `task_questions` отдельным блоком.
5. Роли: прятать кнопки по `capabilities` из `/me`; обрабатывать `403 forbidden_role`.
6. Календарь и feedback — по маршрутам выше.

## Команды и результаты (Windows, `.venv` основной копии, 11.11.2026)

```
python -m pytest -q tests/test_track3_core.py tests/test_track3_calendar.py   # 20 + 13 тестов
python -m pytest -q tests/test_meetings.py tests/test_meeting_voice.py tests/test_meeting_voice_mode.py
```
Результат: `57 passed` (все пять файлов вместе). Полный набор `python -m pytest -q tests`: `759 passed, 12 skipped`. Гоночные тесты проверены мутацией: с обычным `BEGIN` вместо `BEGIN IMMEDIATE` оба падают.

## Ограничения

- Проверено с двойником модели; реальная Ollama, браузер и UI этой веткой не проверялись. Качество summary/risk на реальной модели — за оценкой Codex 3.
- Отзыв ACL у не-владельца через API невозможен для reader-владельца (у reader нет `meetings.share`) — в демо это ожидаемо; отзыв в тестах моделируется прямо в БД.
- Права грантов бинарные (есть ACL — можно читать; редактирует manager с ACL). Раздельных грантов «только чтение/правка» на объект нет: потребовали бы изменить `meeting_access`, в которую seed пишет `VALUES (?,?)`.
- Рабочие часы календаря одни на всех участников; праздники не учитываются.
