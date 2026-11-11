# Track 3 — проект общего контракта

Статус: **на согласование**. В исходном remote документа не было.
Редактор: Codex 3. Изменения после согласования — только через него.
Авторитетные текущие интерфейсы: код и docs/track3-handoffs/{claude,codex2,codex1}.md
на зафиксированных SHA веток. Этот файл не переопределяет продуктовые API.

- База cb2614b86f3b83636e670c83a0afb8f4c9d6c3c3; владение и порядок merge — README.md рядом.
- Только Claude создаёт миграции и включает зависимые роутеры. Store version 8 —
  ядро+calendar+feedback+qa_answers+production_metrics+production_metric_access.
- Seed использует users.access_role manager/reader, aware ISO даты (UTC или +03:00),
  календарную add_busy(), физическую схему KPI из handoff Codex 2. Никаких своих миграций.
- Производственные строки: source_id UNIQUE, owner_id, scope, period_start/end,
  as_of, on_time_orders/completed_orders, defective_units/produced_units,
  occupied_capacity/available_capacity, created_at; access_user_ids → отдельная ACL.
- QA fixtures: question, user_login, meeting_id?, expected_status,
  expected_document_filenames[], expected_quote_substrings[], forbidden_substrings[].
- Пользователи irina/irina-demo (manager), petr/petr-demo (reader). ACL всегда раньше роли.
  Наличие capability не выдаёт доступ к объекту. Чужое → 404 с безопасным аудитом.
- Результат генерации — черновик. Задачи создаются только protocol/confirm;
  изменения задач и календарь: preview → отдельный confirm/cancel, idempotency_key.
- Источник документа: F-id, точная цитата, locator, source_at=дата загрузки.
  Источник транскрипта: U-id и дата встречи (не выдуманная дата реплики).
- LLM использует единую endpoint policy providers.ollama; удалённый gateway
  обрабатывает данные на машине хоста. Cloudflare добавляет внешнего посредника.
- Отчёты двойников и настоящей модели раздельны. Не подтверждённые вручную
  смысловые совпадения не повышают recall. Один gold не покрывает несколько predictions.
- Любые несовпадения интерфейса сообщаются владельцу, а не чинятся в чужом модуле.
