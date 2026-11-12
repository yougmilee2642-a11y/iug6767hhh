# Фокус Meetings — API contract (MVP)

All endpoints are JSON, prefix `/api/meet`. Errors: `{"detail": "русский текст", "code": "machine_code"}`.
- 401 `not_authenticated` — no demo-user session.
- 404 `not_found` — resource missing **or not accessible** (never reveal existence to another user).
- 422 validation, 409 conflict, 503 `model_unavailable` / `model_invalid_reply` / `model_timeout` (local LLM problem; data is kept, user may retry).

Page: `GET /meetings` serves `static/meetings.html` (route added by backend).

## Auth (demo users, server-side checks on every endpoint)
Cookie `cw_meet_user` (httponly, samesite=strict, signed).
- `POST /api/meet/login` `{login, password}` → `{user}`
- `POST /api/meet/logout`
- `GET /api/meet/me` → `{user: {id, login, name, role}}` or 401
- `GET /api/meet/users` → `{users: [{id, login, name}]}`
Demo users: `irina` / `irina-demo` — «Ирина Власова, руководитель проекта» (sees the launch meeting + its 3 documents);
`petr` / `petr-demo` — «Пётр Смирнов, подрядчик» (sees only his own meeting «Синк по дизайну» and doc «Гайд по бренду»; must NOT see launch materials).

## Documents
- `POST /api/meet/documents` multipart: `file` (.txt/.docx/.pdf text, ≤ 5 MB), optional `meeting_id`, optional `share_with` (comma-separated user ids). → `{document}`
- `GET /api/meet/documents` → `{documents: [Document]}` (only accessible)
- `GET /api/meet/documents/{id}` → `{document, fragments: [Fragment]}`
- `GET /api/meet/documents/{id}/download` → original file
- `GET /api/meet/fragments/{fragment_id}` → `{fragment}` (open citation in source)
- `GET /api/meet/search?q=...` → `{results: [Fragment & {snippet}]}` (only accessible)

Document: `{id, title, filename, kind: "txt"|"docx"|"pdf", owner_id, fragments_count, created_at}`
Fragment: `{id: "F12", document_id, document_title, idx, location: "стр. 2, фрагмент 3", text}`

## Meetings
- `POST /api/meet/meetings` `{title, topic, scheduled_at?: "2026-11-12T10:00", participants: ["Ирина Власова","Анна Ковалёва",...], access_user_ids?: [ids]}` → `{meeting}`
- `GET /api/meet/meetings` → `{meetings: [Meeting]}`
- `GET /api/meet/meetings/{id}` → `{meeting, documents: [Document], utterances: [Utterance], prep: Prep|null, protocol: Protocol|null, tasks: [Task]}`
- `PATCH /api/meet/meetings/{id}` partial meeting fields
- `POST /api/meet/meetings/{id}/documents` `{document_id}` attach existing accessible doc; `DELETE .../documents/{document_id}` detach

Meeting: `{id, title, topic, scheduled_at, participants: [str], owner_id, access_user_ids, speaker_map: {label: name}, created_at}`

## Preparation
- `POST /api/meet/meetings/{id}/prepare` → `{prep}` (local LLM, chunked over attached accessible docs)

Prep: `{status: "ok"|"insufficient_data", brief: [Claim], agenda: [Claim], questions: [Claim], gaps: [str], generated_at, model}`
Claim: `{text, citations: [{fragment_id, quote, verified: true}]}` — only verified citations are returned; claims without
verified citation are dropped from brief or moved to `gaps`. Agenda/questions may have empty citations.

## Transcript
- `PUT /api/meet/meetings/{id}/transcript` `{text}` — pasted text; lines like `Ирина: ...`, `[00:12] Анна: ...`, or plain lines (speaker `Говорящий ?`). Replaces transcript. → `{utterances}`
- `POST /api/meet/meetings/{id}/utterances` `{text, speaker_label?: "Говорящий 1", source: "voice"|"manual", start_ms?}` → `{utterance}` (append, used by live recording)
- `PATCH /api/meet/utterances/{id}` `{text?, speaker_label?}` → `{utterance}` (keeps `original_text`)
- `DELETE /api/meet/utterances/{id}`
- `GET /api/meet/utterances/{id}` → `{utterance, meeting_title}` (open quote in source)
- `PUT /api/meet/meetings/{id}/speakers` `{speaker_map: {"Говорящий 1": "Анна Ковалёва"}}` → `{meeting, utterances}`

Utterance: `{id: "U5"-style string id, meeting_id, idx, speaker_label, speaker (resolved name), text, original_text, edited: bool, source, start_ms}`

## Protocol
- `POST /api/meet/meetings/{id}/protocol/draft` → `{protocol}` (local LLM, chunked; replaces unconfirmed draft items, keeps confirmed ones)
- `PUT /api/meet/meetings/{id}/protocol` `{items: [ProtocolItem (editable fields)]}` → `{protocol}`
- `POST /api/meet/meetings/{id}/protocol/confirm` `{item_ids: [ids]}` → `{created: [Task], already_confirmed: [Task], protocol}` (idempotent; only kind=task items)

Protocol: `{meeting_id, status: "draft"|"partially_confirmed", items: [ProtocolItem], warnings: [str], generated_at, model}`
ProtocolItem: `{id, kind: "decision"|"proposal"|"task"|"open_question", text,
  outcome: "accepted"|"rejected"|"discussed"|null  (for proposals),
  assignee: str|null, assignee_status: "stated"|"unknown",
  due: "YYYY-MM-DD"|null, due_text: str|null, due_status: "stated"|"unknown",
  quotes: [{utterance_id, speaker, text, verified: bool}],
  confirmed: bool, confirmed_by: user_name|null, confirmed_at: iso|null, task_id: int|null, edited: bool}`
Decision and task items always have ≥1 verified quote; otherwise they are moved to `warnings` / demoted to open_question.
A rejected proposal is `kind: "proposal", outcome: "rejected"` — never a decision.

## Tasks board
- `GET /api/meet/tasks?status=&missing=` → `{tasks,counts}` (from accessible meetings only)
- `PATCH /api/meet/tasks/{id}` → `409 confirmation_required` after ACL/role checks in Track 3. Use preview/confirm below.
- `POST /api/meet/meetings/{id}/next-agenda` `{create_meeting?: bool}` → `{agenda: [{task_id, text, assignee, due, status}], meeting?: Meeting}`

Task: `{id, text, assignee, assignee_status, due, due_status, status, meeting_id, meeting_title, protocol_item_id,
  source_quote: {utterance_id, text}, confirmed_by, confirmed_at, created_at}`

## Voice meeting mode (Codex)
`POST /api/transcribe` accepts extra form field `speaker_mode=all` → skips the primary-speaker filter, keeps all participants.
Response may include `segments: [{speaker_label, text, start_ms}]` if diarization is cheap; otherwise UI appends one utterance
with `speaker_label="Говорящий ?"` and the user maps speakers manually. Default mode unchanged.


# Track 3 current API extensions

Current routes and schemas: [API reference](track3-release/API.md).
All dates for new meetings/calendar have an offset or an explicit timezone; Europe/Minsk
is the business date zone. Errors are `{code, detail}` and may include fields; every
route carries X-Request-ID. Hidden objects → 404, available object with insufficient
capability → 403. Role never grants an object ACL.

| Endpoint | Request / behavior |
|---|---|
| GET /api/meet/me | user.access_role, user.capabilities plus top-level capabilities, role, timezone |
| POST /api/meet/tasks/{id}/preview | `{changes:{status?,assignee?,assignee_user_id?,due?,priority?,linked_entities?}}` → confirmation_id, expires_at, preview.before/after/version |
| POST /api/meet/tasks/{id}/confirm | `{confirmation_id,idempotency_key}` (8–80 chars key); repeat returns already_confirmed |
| POST /api/meet/confirmations/{id}/cancel | Cancel only the caller’s preview; target unchanged |
| GET /api/meet/calendar/participants | Synthetic directory `{participants:[{id,name}]}` |
| POST /api/meet/calendar/slots | participant_ids, range_start/end, duration_minutes, timezone, optional work_start/end/include_weekends; aware time, ≤31 days |
| POST /api/meet/calendar/preview | meeting_id, participant_ids, start_at, duration_minutes, timezone → preview incl. local invitation bodies |
| POST /api/meet/calendar/confirm | confirmation_id, idempotency_key → event, invitations, already_confirmed; provider mock |
| GET /api/meet/calendar/events and /outbox | Own/participating events and local_outbox_only; no actual mail |
| POST /api/meet/qa | `{question,meeting_id?}` → answer_id, status grounded/insufficient_data, claims/sources with kind/id/title/source_at/quote/locator |
| GET /api/meet/qa/{answer_id} | Caller’s answer; ACL and source integrity checked again; revoked → 404, stale → 409 |
| GET /api/meet/overview?as_of=... | Aware ISO cutoff; metrics with key/value/unit/formula/source, overdue_tasks, warnings; zero denominator=null |
| GET /api/meet/sources/{kind}/{source_id} | kind=task or metric, dynamic source resolver; fragments/utterances keep existing endpoints |
| POST /api/meet/feedback | target_type, target_id, rating useful/incorrect, optional meeting_id/answer_id/comment; target ACL checked |
| GET /api/meet/feedback | Caller’s feedback only |
| GET /api/meet/audit?scope=mine\|my_objects | Manager; response `{events,scope}`; my_objects includes safe denial metadata for owned objects |

Roles: reader can read/generate prep/view calendar/QA/overview/feedback within ACL;
manager additionally edits/shares/uploads/confirms/invites/audit. Detail and examples: [API reference](track3-release/API.md).
Protocol adds kind=risk and summary with verified/needs_clarification, quotes and note.
GET meeting includes a live followup open_tasks/task_questions block even when prep is null.
Prep also adds current-ACL open_tasks/task_questions from the followup chain. Reader-generated
prep is personal and unsaved. Transcript change during draft → 409 stale_transcript.
Calendar/task stale/expired/cancelled/conflicting confirmations → 409.

Source dates: document source_at is upload timestamp, not authored date; transcript
citation shows meeting date, not a fabricated utterance timestamp. Overview as_of is
oldest included snapshot; generated_at is calculation time. Task counts use current
statuses even with historical as_of. Aggregated source IDs are opaque signed IDs,
never authorization. QA asks the model to select offered excerpt_ids; the server renders the stored text.
The legacy quotation envelope remains supported. Lexical retrieval normalizes common
Russian inflections/polite wording and the release synonym, but can still miss relevant
wording. The owner reconciled legacy quotation policy in 3104d0c: a partial quote is widened
to the full stored sentence including units/conditions; unpunctuated heading lines
remain part of that sentence. Tests assert the full exact answer and source. Model failures → 503 model_*; no hidden
cloud fallback. Remote inference/data boundaries are in the runbook.


## Авторский voice MVP (#9, main e3d37e3)

| Endpoint | Контракт / ограничения |
|---|---|
| POST /api/meet/voice/ask | `{text,meeting_id?,speak_private?:false}`; текст1–1000 символов. Возвращает route/status/answer/display/spoken/speak/silent_reason/open_page. Чтение через существующие QA/overview и ACL; команды изменения получают отказ и ссылку на экран preview/confirm |
| POST /api/meet/voice/transcribe | Multipart WAV≤5 MiB; require qa.ask, локальный ASR, иначе503 local_asr_required; ответ `{text}`, Cache-Control:no-store. Весов для обычного text start не требует |
| POST /api/meet/voice/wake | Multipart≤256 KiB; только loopback-клиент без proxy headers и с локальным ASR. Возвращает `{wake,question}`; чужая речь не возвращается как question. Ограничение размера/пустой сегмент→413, remote client→403 wake_local_only |

Озвучивание по умолчанию разрешено только если каждый слушатель видит те же данные;
иначе ответ только на экране. speak_private — явный выбор пользователя для одного
вопроса, не изменение ACL. Маршруты чтения проверяют qa.ask/overview.read. Voice audit
записывает маршрут/результат/источники, без raw вопроса/ответа; вопрос QA может оставить
обычный hash/result в qa_answers. Аудио не записывается этими route handlers в БД.
Настоящий microphone/ASR/TTS в этой среде не проверен; 45 CPU tests — doubles.
Подробнее: [голосовой режим](MEETINGS.md).


## Photoprint v2 · подготовка и поручения (текущая ветка)

`GET /api/meet/meetings/{id}` и `POST .../prepare` дополняют followup/prep
текущими данными роли. `open_tasks` включает доступные задачи отдела и общих
заказов, а также связанные прежние встречи; отменённые/завершённые исключены.
`previous_questions` содержит только вопросы с повторно проверенной репликой;
`kpi_context` — срез отдела с `as_of`, формулой, числителем/знаменателем и
разрешимыми источниками. Всё вычисляется без новой модели. Legacy-пользователи
сохраняют прежний набор связанных встреч.

Task `status`: `open|in_progress|blocked|done|cancelled`.
Task `priority`: `low|normal|high|urgent`, по умолчанию normal.
`assignee_user_id` связывает назначение с действующим пользователем; свободное
имя сохраняется для явно названного внешнего ответственного. `external_ref`
доступен только для чтения; вручную записать фиктивный CRM ref нельзя.

`linked_entities` — не более20 объектов `{kind,id}`; kind — `order|customer|document`,
id — строка. Пример: `[{"kind":"order","id":"PP-2611-00042"}]`.
В preview и снова в confirm проверяются доступ к каждой связи, действующий
ответственный, версия задачи и scope роли. У сотрудника разрешён только статус
своей задачи; при делегировании — только действующий отдел делегирования.
Руководитель группы не назначает в чужой отдел.

`GET /api/meet/tasks?missing=assignee|due|either` отбирает незакрытые задачи без
владельца/даты. `counts.missing_assignee` и `counts.missing_due` считаются по
полному доступному незакрытому реестру. Нераспознанный срок словами считается
неуточнённой датой; исходная формулировка сохраняется.

`assignee_suggestion` — необязательная подсказка по теме, с `status=assumption`;
она не заполняет поля владельца и ничего не записывает. В UI пункты можно
добавлять в явно обозначенный локальный проект повестки: это память вкладки,
не изменение встречи/документа на сервере.

Навигация: пункт протокола → task_id; задача → protocol_item_id/meeting_id и
source_quote. Интерфейс позволяет перейти к задаче, её пункту протокола и
реплике. Источник задачи датируется регистрацией/последним изменением записи, а не будущей плановой датой
встречи. Любой источник при открытии повторно проверяет доступ.


## Photoprint v2 · витрины и контроль решений

`GET /api/meet/overview?as_of=<aware ISO>` дополнен scoped KPI:
`support_sla`, `mary_resolution`, `moderation_queue`, `unclaimed_pickup`,
`late_order_causes`, `capacity_forecast_peak`, `missing_assignee`, `missing_due`,
`open_decisions`, `overdue_decisions`. Для новых показателей возвращаются
`as_of`, `formula`, числитель/знаменатель, `source` и `status`.
Пороги `meetings/management/thresholds.json` демонстрационные, не согласованные
нормативы предприятия. Source проверяется повторно и открывает фактические
строки/счётчики; недоступные строки исключаются до агрегации и выбора периода.

Поддержка считается за42 дня снимка, а не плавающие42 дня часов браузера.
`capacity_forecast` — первые4 доступных будущих периода (даты явные),
`delay_reasons` — число/знаменатель/доля причин просрочки с источником.
Нулевой знаменатель даёт null и предупреждение; устаревшие витрины отмечаются.
Статусы задач/решений — текущий реестр; as_of задаёт дату просрочки и срез
внешней витрины, а не восстановление исторического состояния задач.
`GET /api/meet/sources/task/T12` и числовой вариант `/task/12` совместимы.

Решение ставится на контроль только из существующего пункта `kind=decision`
с проверяемой репликой. API:

| Метод/путь | Тело/результат |
|---|---|
| GET /api/meet/decisions | доступные `{decisions}`; owner_user_id/due/status/источник/version |
| POST /api/meet/decisions/{protocol_item_id}/preview | `{owner_user_id:null|id,due:null|YYYY-MM-DD,status:open|done|cancelled}` → token + before/after + реплика |
| POST /api/meet/decisions/{protocol_item_id}/confirm | `{confirmation_id,idempotency_key}` → decision_control_id; повтор не дублирует |

Отмена — общий `/confirmations/{id}/cancel`. При confirm повторно проверяются
права, актуальность решения/реплики, версия контроля и действующий ответственный.
Контроль не вызывает внешние действия. Подтверждённый пункт протокола сохраняется
при попытке обычной правки; поля контроля меняются отдельным подтверждением.
Неизвестные владелец/срок остаются null. Отсутствие срока не считается просрочкой.
Календарная дата просрочки определяется в Europe/Minsk.

### V2 · CRM mock (миграция 11)

Только локальная SQLite-имитация; реальные внешние системы не подключены.
Подробности и ограничения: `docs/track3-release/CRM_MOCK.md`.

| Метод/путь `/api/meet` | Доступ / результат |
|---|---|
| `POST /crm/preview` | crm.write + ACL; `{action: "task.create"|"protocol.attach", object_id, entity_ref?}`; токен и маскированная карточка |
| `POST /crm/confirm` | `{confirmation_id,idempotency_key}`; повтор возвращает тот же результат; recheck прав/версии/источников/маппинга |
| `POST /confirmations/{id}/cancel` | закрывает собственный токен; 0 экспортов |
| `GET /crm/tasks/{task_id}` | ACL встречи; outbox и внешний mock-статус, без изменения задачи |
| `GET /crm/orders/{order_no}` | SQL-права до чтения; ERP, история статусов, доступные обращения, as_of/fetched_at/stale |
| `GET /crm/targets?meeting_id=…` | crm.write + scope; доступные сделки и экспортированные задачи встречи |
| `GET /integrations` | integrations.manage; метаданные, число сопоставлений, время проверки/отправки |
| `POST /integrations/check` | integrations.manage; настоящий вызов mock.list_departments + аудит |

`entity_ref`: `deal:<id>` либо `mock:task:…`. При отправке протокола object_id —
ID встречи, при создании задачи — ID подтверждённой задачи.
Ошибки `{code,detail}`: 403 forbidden,404 not_found,409 stale/export_exists,
422 employee_mapping_required/source_quote_required/no_confirmed_items/restricted_action,
503 unavailable/config/uncertain. При сбое **после** preview confirm сохраняет
терминальный outbox и ответ с `status`, `outbox_id`, `mode:"mock"`, `http_status`.
Повтор такого confirm возвращает 503 с тем же статусом и `already_confirmed:true`;
это не новая попытка отправки. Не подменять эти ответы успешной записью.

Задача дополнена `crm_status` (null/sent/failed/uncertain); `external_ref` по-прежнему
записывается только сервером. Пункт протокола содержит распознанные явные
`linked_entities`; наличие номера не даёт доступа к связанной сущности.
