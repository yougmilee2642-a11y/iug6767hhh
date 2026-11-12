# Состояние Фокус v2 — 12.11.2026

[Draft PR #12](https://github.com/yougmilee2642-a11y/iug6767hhh/pull/12),
ветка `track3/v2-fotoprint`. Полное ТЗ v2 не выполнено. Main не изменён.

Реализованы E0/E1/E2, P0 подготовка/поручения/обзор/решения, privacy/injection/audit,
mock CRM с preview/confirm/uncertain, frozen evaluator v2 на дублёре.
E14 добавляет исправление установки, отдельный runtime-профиль, изолированную
проверку install в Linux/Windows CI, README/демо/OpenAPI/самоаудит.

- Локальный общий Python: **1374 passed, 28 skipped, 0 failed**, 92,08 s.
- Node: **66 passed**. HTTP семи уровней/CRM/restart passed.
- Реальный provider на закрытом loopback: prepare/protocol/QA возвращают
  **503 model_unavailable**, расшифровка сохранена; живого инференса нет.
- Предыдущий опубликованный 3dbc30c: [CI 43157518742](https://github.com/yougmilee2642-a11y/iug6767hhh/actions/runs/43157518742)
  полностью passed, включая браузер. Новый head требует нового CI.
- Чистая установка обнаружила отсутствие PDF reader в base requirements;
  зависимости добавлены. Отдельный runtime прошёл seed/restart без голосовых
  или тестовых пакетов. Исправленный base/runtime ещё проверяются новым runner.
- Frozen 5 расшифровок/30 задач/36 QA: double pipeline_passed. Это не live recall.

Главный оставшийся объём: E3 transport/Bitrix24/Mary, E4 смены/ICS/EML,
E6 FTS5/документы, E10 единый чат; затем voice/audio/calls/briefing/retention/web
и P2. Микрофон/ASR/TTS/диаризация/LLM v2 агентом не запускались по ТЗ.
Лицензии PyMuPDF/Silero, внешние шрифты и независимая установка остаются открыты.

- [Таблица каждого требования и эпиков](SELF_AUDIT.md)
- [Тесты, шесть веток и ограничения доказательств](TEST_REPORT.md)
- [Текстовый запуск](V2_QUICKSTART.md)
- [API/OpenAPI](API.md), [демо](DEMO.md), [план защиты](PITCH_OUTLINE.md)
- [Проверки хоста](LIVE_CHECKS.md), [журнал](../track3-handoffs/agent-v2.md)

Исторический v1-отчёт сохранён в [STATUS_V1.md](STATUS_V1.md).
Его старое падение мобильной ширины устранено в v2; старые права владения файлами
заменены одним исполнителем. История отчётов не является статусом нового head.

## Продолжение E4: ICS и приглашения

1389 Python passed/28 skipped/0 failed (97,76 s), Node66 passed. Новый
HTTP/restart проверяет ICS/EML, импорт/подписку/отзыв и provider503 без инференса.
[CALENDAR.md](CALENDAR.md) описывает API и ограничения. Chromium локально всё
ещё блокируется Unix socket policy; расширенный браузерный сценарий включён в CI.
Чистые base/runtime Linux установки и браузер E14 CI43161157327 прошли; Windows
на момент записи queued. Смены/буферы, внешние провайдеры, серии/напоминания и
автоматическая материализация EML остаются. Main не менялся, PR12 draft.
