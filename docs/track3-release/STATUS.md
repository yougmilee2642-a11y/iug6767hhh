# Track 3 release status — 11.11.2026

**НЕ ГОТОВ К ВЫПУСКУ.** Локальная интеграция выполнена, main не менялся.
Точные commit в machine reports относятся к проверенному коду, не к последующим
документационным checkpoint. Итоговый integration SHA выводится в handoff/сообщении.

## Поставки и происхождение

| Пакет | Проверенная ветка / SHA | PR |
|---|---|---|
| Core, roles, migrations v8, calendar | claude/track3-core-calendar / cd06b4d696147805ed0f2a4dfa62e485a1b6d865 | #2 (draft у автора) |
| Knowledge, overview | codex/track3-knowledge-overview / e03536b027fe20364d4233d4ffe35077340a5e2a | #1 |
| UI | codex/track3-ui / 3dc09e711f84e3f54761d0e04c9266cc0e44664e | #3 |
| Assignment / frozen gold | release: 9a51a28 / 9d1c2dc | Не опубликовано |
| Integration | codex/track3-integration, merge в отдельной clone/worktree | Не опубликовано |

Пути каждого PR сверены через GitHub changed filenames и локальный diff от базы.
Пакеты не меняют app.py/providers/ASR/старые requirements/start-gateway.ps1. Новые
backend textutil helper и tests/test_meetings.py входят только в авторский core PR.
Codex 3 меняет лишь свою release-зону; verify_ownership.py проверяет её автоматически.

## Проверки: passed

- 199 passed, 10 skipped по общей целевой команде, 23.79 s на срезе 4ec358b;
  10 skips — явные opt-in real Ollama/real-model HTTP tests. Полный лог reports/python.log.
  Финальные значения после новых тестов cleanup/scoring зафиксированы в итоговом логе.
- 46/46 Node regressions и syntax трёх модулей. Речевые алгоритмы не менялись;
  Python базовые meetings/voice-routing/gateway включены в целевой набор.
- Настоящий HTTP существующего app.py, **без двойника LLM**: 30 запросов (точный список
  в reports/http.json), две роли/404/403/аудит, ручной протокол→confirm без дублей,
  task cancel/confirm, calendar cancel/confirm/local_outbox, QA-отказ по 2030,
  KPI 90/2/75 и 2 open/1 overdue, cookies/состояние после перезапуска.
  3.29 s; torch отсутствует, речевые веса не нужны. Grounded QA/генерацию он не доказывает.
- Новый seed повторяется без новых строк, совместим с отдельной «Орбитой».
- Повтор установки в чистый venv: 22.11 s, в том числе pip 19.83 s, **тёплый кэш**,
  тот же участник. Скачивания модели/первый cold start исключены; reports/install.json.
- pip check: зависимости согласованы. Изолированные test DB; data/ не очищалась.

## Failed / not run

| Статус | Проверка | Причина / следующий шаг |
|---|---|---|
| FAILED setup; сценарии NOT RUN | Chromium UI suite | process_singleton_posix: socket() Operation not permitted, до первого сценария. reports/browser-blocked.log. Проверить в CI/на машине без этого ограничения |
| NOT RUN | 3 расшифровки и 16 вопросов на настоящей модели | Loopback Ollama metadata preflight: ConnectError. reports/live-not-run.json. Нужны разрешённый gateway/установленная модель и одно согласованное GPU-окно |
| NOT RUN | Новый recall ≥80%, precision/false tasks/latency | Модель не отвечала; значений нет. Эталон и оценщик готовы, прежняя «Орбита 3 из 3» не засчитывается |
| NOT RUN | Независимая установка другим участником | Сценарий и точные зависимости готовы, но другой участник здесь не выполнял установку |
| NOT RUN | GitHub CI | Workflow создан локально, не запущен на GitHub до публикации |
| BLOCKED | Push / release PR / integration PR | Подключён Listopad33; get_repo: pull=true, push=false. Проверка collaborator permission → 403 Resource not accessible by integration. git push --dry-run → could not read Username (terminal prompts disabled). Не было push/PR |
| PENDING | Согласование общего CONTRACT | Файлов не было на remote; восстановлен проект контракта, согласование не выдумывается |
| PENDING | Лицензирование поставки | PyMuPDF dual AGPL/commercial и неподтверждённые условия конкретных voice-assets; LICENSES.md |

Полный проектный pytest всех треков не запускался в новом минимальном окружении:
выполнены целевые и релевантные общие проверки; голосовые веса/GPU не установлены.
Физический микрофон и реальная почта не проверялись. Реальной почты в test calendar нет.

## Соответствие ТЗ

| Пункт | Поставка | Состояние |
|---|---|---|
| 1 Инструкции/база/ветки | Первый release commit 9a51a28; docs/track3-team | Локально готово, публикация/согласование заблокированы |
| 2 Защищённый MeetingLLM | Общий endpoint(), Bearer, no redirects/proxy/cloud; unit checks | Passed |
| 3 Фотопринт | 24 деловых документа, 3 transcript, ACL/status/calendar/KPI; idempotent seed | Passed в интеграции |
| 4 Gold/QA | 18 задач, 16 вопросов, frozen SHA до оценки | Готово |
| 5 Реальная оценка | evaluate.py + независимый review, сохранение raw evidence | Реальная модель NOT RUN |
| 6 Текстовый запуск | Existing app.py без torch/голосовых весов; RUNBOOK | HTTP passed; независимый повтор pending |
| 7 Очистка/хранение | Marker, absolute path, dry-run, explicit confirm; RETENTION | Passed unit/integration, политика ручная |
| 8 Лицензии | Lock, metadata inventory, отдельные code/weights | Текстовый inventory готов; указанные license gates pending |
| 9 CI/документы/демо | Workflow, API, architecture, 5–7 мин, 10 слайдов | Документы готовы, UI/CI не выполнены в этой среде |

## Риски и передачи

1. Релиз не прошёл quality gate модели; frozen набор небольшой и синтетический.
2. Лексический QA может пропускать синонимы; точная цитата сама по себе не доказывает
   правильность выводов. Спорные task matches требуют независимого человека.
3. Public product deployment, SSO, encrypted-at-rest storage, настоящая доставка
   календарных приглашений и автоматическая диаризация не входят в этот выпуск.
4. Remote host получает данные; Cloudflare — внешний посредник, не «полностью локально».
5. Демо-даты зафиксированы; календарь текущего HTTP-smoke выбирает будущие слоты
   динамически. Исторический as_of не является восстановлением статусов задач.
6. Ни один обязательный NOT RUN не закрывается успешными двойниками/старыми отчётами.
