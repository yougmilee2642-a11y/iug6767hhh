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

## Продолжение E4: рабочий график

Smart-подбор учитывает смены, перерывы, HR-отсутствия, буфер10 минут, пояса и
необязательных участников; top3 с объяснениями. Confirm повторно проверяет
доступность, источник/новые предупреждения. Full1405 passed/28 skipped/0 failed
(100,84s), после добавления path-regression targeted45 passed. Node66/0; настоящий
HTTP выдал3 smart-слота и проверилpreview/cancel, ICS/EML/restart/503.

CI43162911735 на020c515: Linux/base/runtime/весь browser и Windows release passed;
Windows clean-runtime failed52,19s при старте сервера после успешного install/seed.
Первичный JSON сохранён. Следующий кандидат канонизирует путь изtempfile перед
сверкой seed-marker (Windows8.3/relative) и сохраняет stderr при падении; диагноз
и исправление Windows должны быть подтверждены новым CI, успех не заявляется.

## E6.3: поиск с правами до статистики ранжирования

Ручной поиск и QA используют FTS5/BM25 с русской нормализацией. Временный индекс
строится только по доступным и допустимым источникам; чужой корпус не влияет
даже на BM25 statistics. Secret исключён из snippets, admin/auditor получают403.
Индекс пересобирается на запрос: это прототип для демо-корпуса, не масштабирование
на миллионы документов. Версии/diff/сводка остаются. Подробнее: SEARCH.md.

Полный локальный прогон1426/28/0,108,70s; после дополнительного role-denial теста
целевая группа52/0. Node66/0. Double evaluator30/30 задач,36/36QA,17/17claims,
0 rights/false_actions; не live качество. Новый CI должен проверить полный состав.
Windows smoke cc00745 ждёт runner; успех Windows пока не заявлен.
