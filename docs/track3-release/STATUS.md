# Состояние Фокус v2 — 12.11.2026

[Draft PR #12](https://github.com/yougmilee2642-a11y/iug6767hhh/pull/12),
ветка `track3/v2-fotoprint`. Полное ТЗ v2 не выполнено. Main не изменён.

Реализованы E0/E1/E2, обязательные подготовка/поручения/обзор/решения,
privacy/injection/audit, mock CRM с preview/confirm/uncertain, frozen evaluator v2.
Календарь включает ICS import/export/отзываемые подписки, EML download,
смены/перерывы/буфер/отсутствия и необязательных участников. Поиск/QA используют
FTS5/BM25 с ACL до индексации и статистики ранжирования.

Продолжение E6: неизменяемые редакции через preview/confirm, доступная история,
предупреждения об истёкшем сроке/замене, точные выдержки и diff без модели.
Поиск и QA выбирают актуальную доступную версию; исторический поиск включается
явно. Ссылки встреч на прежние редакции сохраняются. [DOCUMENTS.md](DOCUMENTS.md).

- Последний опубликованный 574ab18:
  [CI 43166951277](https://github.com/yougmilee2642-a11y/iug6767hhh/actions/runs/43166951277)
  полностью success: Python/Node/35 UI, browser→HTTP, Linux base/runtime install,
  Windows release/runtime install. Прежний Windows startup/provider smoke исправлен;
  исходные неуспешные отчёты сохранены в истории и TEST_REPORT.
- Объединение с опубликованным45a3f12 сохраняет мульти-file и metadata UI и
  добавляет hardening источников. Итог:1474 passed/28 skipped/0 failed,216,56s;
  Node66 passed. Целевые47 passed. HTTP/restart/provider503 passed6,22s.
  Старый QA сохраняет цитаты с предупреждением; новые запросы используют актуальное.
- Frozen 5 расшифровок/30 задач/36 QA: double pipeline_passed, 17/17 claims с источником,
  0 прав/ложных действий. Это проверка конвейера и метрик, не качество модели.
- Локальный Chromium ограничен socket policy; новый браузерный путь версий добавлен
  в CI. Новому head нужны собственные CI и clean-install результаты.

Главный оставшийся объём: E3 transport/Bitrix24/Mary, E10 единый чат,
voice v2, media jobs/calls, брифинг/метрика→действие, retention/web-hardening,
экспорт/комментарии/эскалации задач, внешние календари и P2.
Документные противоречия и смысловая сводка ещё не реализованы.
Лицензии PyMuPDF/Silero, внешние шрифты и независимая установка остаются открыты.
Микрофон/ASR/TTS/диаризация/LLM v2 агентом не запускались по ТЗ.

- [Самоаудит каждого требования и эпиков](SELF_AUDIT.md)
- [Проверки и ограничения доказательств](TEST_REPORT.md)
- [Текстовый запуск](V2_QUICKSTART.md), [API](API.md), [календарь](CALENDAR.md), [поиск](SEARCH.md)
- [Демо](DEMO.md), [питч](PITCH_OUTLINE.md), [проверки хоста](LIVE_CHECKS.md)
- [Журнал](../track3-handoffs/agent-v2.md), [исторический v1](STATUS_V1.md)
