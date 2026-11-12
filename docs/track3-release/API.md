# API Фокус v2

Базовый адрес: `http://127.0.0.1:8000/api/meet`. Вход — `POST /login`,
cookie `cw_meet_user` (HttpOnly, SameSite). Сервер проверяет роль, отдел,
ACL/конфиденциальность на чтении, до контекста модели и повторно на confirm.
Admin/auditor не получают бизнес-содержимое. Чужой объект → 404 без его названия;
запрещённая операция → 403. В ответе есть `X-Request-ID` для журнала.

Полный срез 73 путей: [openapi.json](openapi.json). Он получен из настоящего
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
внешние CRM/почту. Коннектор CRM и календарь сейчас mock/local outbox.
ICS/EML реализованы локально; единого `/assistant`, live Bitrix24 и управления retention пока нет.

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
