# API Фокус v2

Базовый адрес: `http://127.0.0.1:8000/api/meet`. Вход — `POST /login`,
cookie `cw_meet_user` (HttpOnly, SameSite). Сервер проверяет роль, отдел,
ACL/конфиденциальность на чтении, до контекста модели и повторно на confirm.
Admin/auditor не получают бизнес-содержимое. Чужой объект → 404 без его названия;
запрещённая операция → 403. В ответе есть `X-Request-ID` для журнала.

Полный срез117 путей: [openapi.json](openapi.json). Он получен из настоящего
`app.app`, а не написан вручную. Обновление без моделей/рабочей БД:

```bash
python scripts/track3/export_api.py --output docs/track3-release/openapi.json
```

Схема отражает формы маршрутов и Pydantic validation; императивные проверки
доступа, cookie и preview/confirm дополнительно описаны здесь и в
[контракте](../track3-team/CONTRACT.md). Примеры: [requests.http](requests.http).
Формат источников и старых маршрутов: [MEETINGS_API.md](../MEETINGS_API.md).

| Назначение | Маршруты относительно `/api/meet` |
|---|---|
| Сессия/роль | `POST /login`, `POST /logout`, `GET /me`, `GET /demo-profiles` |
| Документы | `GET/POST /documents`, `GET /documents/{id}/download`, поиск и fragments |
| Версии/выдержки | `POST /documents/{id}/versions/preview`, `/versions/confirm`, `GET /versions`, `/summary`, `/compare/{other_id}`; [правила](DOCUMENTS.md) |
| Подготовка/протокол | `POST /meetings/{id}/prepare`, `POST /meetings/{id}/protocol/draft`, ручной `PUT /meetings/{id}/protocol` |
| Задачи | `GET /tasks`, `POST /tasks/{id}/preview`, `POST /tasks/{id}/confirm` |
| Решения | `GET /decisions`, `POST /decisions/{item_id}/preview`, `POST /decisions/{item_id}/confirm` |
| QA/источник | `POST /qa`, `GET /qa/{id}`, `GET /sources/{kind}/{id}` |
| Обзор | `GET /overview?as_of=…` — KPI, формула, числитель/знаменатель, as_of, источник |
| Mock CRM | `POST /crm/preview`, `POST /crm/confirm`, `GET /crm/tasks/{id}`, `GET /crm/orders/{order_no}` |
| Календарь ICS/EML | `GET /calendar/export.ics`, `/calendar/feed/{token}.ics`, `POST/GET /calendar/subscriptions`, import preview/confirm; [границы](CALENDAR.md) |
| Интеграции | `GET /integrations`, `POST /integrations/check`, `GET /crm/targets` |
| Администрирование | `GET /admin/users`, `POST /admin/users/preview`, `POST /admin/users/confirm` |
| Делегирование | `POST /delegations` (preview), `POST /delegations/confirm`; текущие права — `GET /me` |
| Журнал | `GET /audit`, `GET /audit?export=true` — фильтры и безопасный CSV |
| Отмена | `POST /confirmations/{confirmation_id}/cancel` |

Точный состав методов/полей проверять по схеме. Два обязательных этапа записи:
preview возвращает `confirmation_id` и изменения; человек проверяет их и передаёт
`confirmation_id` + новый `idempotency_key` в confirm. Повтор того же confirm
возвращает ранее сохранённый результат. Отмена не меняет бизнес-объект.
Изменившиеся права/версия/исполнитель/связь после preview приводят к отказу,
а не к записи старого черновика. CRM timeout → `uncertain`, без слепого повтора.

Ошибки: `{ "code": "model_unavailable", "detail": "…русское объяснение…" }`.
503 `model_*` сохраняет исходные материалы. Контекст модели не отправляется во
внешние CRM/почту. По умолчанию CRM и календарь используют mock/local outbox. Bitrix24 REST и календарный адаптер включаются отдельными флагами и проверены транспортными дублёрами; реальный портал не подключался. Assistant и управление retention реализованы, см. таблицу ниже.

Поиск `/search?q=…` (до2000символов) использует scoped FTS5/BM25; доступ
проверяется SQL до индексации/ранжирования. Secret исключён из snippets.
Источники ответов QA остаются проверенными цитатами. [SEARCH.md](SEARCH.md)
описывает алгоритм, ограничения корпуса и503search_unavailable.

По умолчанию используются актуальные доступные версии. Для истории:
`GET /search?...&include_history=true` и `POST /qa` с JSON `include_history:true`.
QA/summary/compare возвращают предупреждения по `valid_until`/замене редакции.
Сохранённый ответ сохраняет исторические цитаты и предупреждение о замене;
доступ и цитаты перепроверяются при повторном чтении. Новая генерация на
источнике, заменённом во время запроса, отклоняется409.

Дневной брифинг: `GET /briefing?date=2026-11-11`, только данные в текущем scope;
источник встречи: `GET /sources/meeting/{id}`. [BRIEFING.md](BRIEFING.md).

## Assistant, audio/calls и контроль

| Назначение | Маршруты | Ограничение |
|---|---|---|
| Ассистент | POST /assistant/ask; GET /assistant/conversations, /assistant/conversations/{id} | Личная история, ACL/source recheck; read-tools allowlist |
| Предложения | POST /assistant/actions/preview, /confirm | task / meeting / task_change; optional basis {kind:metric/call,id}; proof/version recheck |
| Аудио | POST/GET /meetings/{id}/audio; GET /media-jobs/{id}; POST /retry | Consent;64МБ default;503/asr_unavailable сохраняет файл |
| Реплики аудио | POST /media-jobs/{id}/import/preview, /import/confirm | append; speaker_map только из участников; cancel/replay/stale |
| Оригинал/аналитика | GET /media-assets/{id}/audio; GET /meetings/{id}/analytics | Текущий ACL; без таймкодов доли/паузы не выдумываются |
| Звонки | POST /calls/preview, /calls/confirm; GET /calls, /calls/{id}, /calls/problems | Consent; own/dept scope + confidential meeting; правило с цитатой |
| Источник звонка | GET /sources/call/C{id} | Повторный calls.read + ACL |
| Контекст повестки | POST /meetings/{id}/next-agenda | context — личный read-only контекст; не рассылается в followup |
| Выбор выдержек | GET /documents/{id}/summary?semantic=true | opt-in model IDs only; цитаты/версия/ACL проверяются после вызова |
| Комментарии | GET/POST /tasks/{id}/comments | Владелец/scoped задача, история изменений |
| Протокол | GET /meetings/{id}/protocol/export (format: md или html); POST /protocol/mail/preview, /confirm | Подтверждённые пункты; повторный ACL получателей, local EML |
| Контроль данных | GET /retention; POST /retention/policy/preview, /policy/confirm; /privacy/delete-request | Admin policy/cleanup/deletion через отдельный preview/confirm |
| Уведомления | GET /notifications; POST /notification-settings/preview, /confirm | Внешние каналы — opt-in queue, реальные отправители не включены |

Точные пути операций хранения/уведомлений см. OpenAPI. Для браузерных мутаций
требуется Origin той же системы и X-Focus-Request:1. Скрипты без browser Origin
поддерживаются. calendar delivery503/uncertain сохраняет reservation; повтор
не отправляет запрос и не создаёт приглашения. Самостоятельно очищать outbox
для повтора запрещено: сначала ручная сверка с порталом.

## Предзаполнение голосовых действий и темы звонка

`proposed_action` содержит редактируемые `assignee_user_id`, `due` или
`calendar_hint` (участники, aware-диапазон, длительность, Europe/Minsk),
`requires_clarification`. Разбор детерминированный: ё/е, падежные формы
справочника, дни недели, завтра, даты и числа словами. Неоднозначные поля
остаются пустыми. Диапазон и участники повторно проверяются на preview/confirm.
Подтверждение проекта встречи создаёт только несогласованный проект; отдельная
кнопка открывает подбор слотов. Приглашения требуют своего preview/confirm.

`GET /calls/{id}/topics` — необязательный выбор тем моделью, только при
`MEETINGS_CALL_TOPIC_MODEL=1`. Модель выбирает коды из17тем и ID разрешённых
реплик; сервер возвращает исходные цитаты. Предложения требуют проверки
человеком. ACL/роль/версия проверяются повторно после вызова; secret не
передаётся модели. Стандартный анализ по правилам остаётся доступен без модели.

## Повторяющиеся встречи и напоминания

`GET /calendar/series`, `POST /calendar/series/preview`, `/confirm`: конечная
локальная серия2..30встреч, daily/weekdays/weekly, IANA-зона, smartshift-check.
Все даты/участники видны на preview и повторно проверяются на confirm;
протоколы каждой встречи независимы. Отмена/занятый слот/устаревший preview
не создают ни серию, ни приглашения. Внешние серии отключены, каждая внешняя
встреча требует собственного подтверждения.
`notification-settings` принимает reminder_minutes0..1440, default15;0выключает.
Google provider выключен по умолчанию; настройки/ограничения: CALENDAR.md.

`GET /document-insights?meeting_id=…`: возможные противоречия и обещания с
цитатами, только текущие доступные документы/реплики. Basis для manualactions
расширен document:F… и utterance:U…; доступ/содержимое/редакция перепроверяются
на confirm. `GET /sources/document/F…`, `/sources/utterance/U…` — канонический
исходник. Secret не появляется ни в анализе, ни в голосовых списках.

`GET /corridor`: три коротких предложения с источниками о ближайшей личной встрече. `POST /meetings/{id}/room-hints`: consent и временные drafts, только transcript.edit; без моделей/бизнес-записей. См.BRIEFING.md.
