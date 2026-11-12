> Текущий спринт: [V2_SPEC.md](V2_SPEC.md), загруженное пользователем 11.11.2026.
> Один исполнитель, прежнее разделение путей отменено. Ниже сохранён исторический
> пакет v1; API-совместимость/источники/preview-confirm остаются обязательны.
> Живые модели агент v2 не запускает: модельные проверки только на doubles, live scripts для хоста.

# Track 3 — общий пакет выпуска

База: `cb2614b86f3b83636e670c83a0afb8f4c9d6c3c3`. Этот пакет восстановлен
по заданию пользователя: в опубликованных ветках исходные README и CONTRACT
отсутствовали. CONTRACT — проект для согласования, не ранее утверждённый документ.

## Ветки и владение

| Участник | Ветка | Владение |
|---|---|---|
| Claude | claude/track3-core-calendar | Ядро, миграции, роли, подтверждения, календарь; регистрация зависимых роутеров |
| Codex 2 | codex/track3-knowledge-overview | Knowledge QA, обзор и KPI |
| Codex 1 | codex/track3-ui | UI и tests/ui_track3 |
| Codex 3 | codex/track3-release | meetings/llm.py; scripts/seed_meetings_demo.py, scripts/live_meetings_check.py; новые scripts/track3, evaluation/track3, demo/track3, tests/test_track3_release__.py, tests/test_track3_llm__.py, requirements-track3*.txt, .github/workflows/track3.yml; README.md, MEETINGS.md, TEAM_DEVELOPMENT.md, docs/MEETINGS_API.md, docs/MEETINGS_HANDOFF.md; docs/track3-team, docs/track3-release, docs/track3-handoffs/codex3.md |
| Codex 3 | codex/track3-integration | Последовательные merge чужих поставок, без самостоятельной правки чужой логики |

Своя clone/worktree. Не переписывать main, не включать пользовательские файлы.
Не менять start-gateway.ps1 (пользовательская правка), app.py, providers, ASR,
старые requirements, frontend, store/api/extract и модули Codex 2.
Изменения чужой логики возвращать владельцу с воспроизведением. Только Codex 3
редактирует общий CONTRACT после согласования. Не требовать rebase уже слитой истории.

## Полное задание Codex 3

1. Первый коммит: этот пакет, SHA базы, ветки, команды проверки.
2. MeetingLLM использует providers.ollama.endpoint(), Bearer, без redirects и env proxy;
   блокирует cloud и публичный незашифрованный HTTP; сохраняет loopback, schema,
   think=false, лимиты и timeout. Remote host и Cloudflare посредник описываются явно.
3. Отдельный идемпотентный seed «Фотопринт»: ≥20 синтетических документов,
   3 расшифровки (задержка фотокниг, производство, контроль), разные даты/типы/ACL,
   задачи open/overdue/done, календарь, числители и знаменатели KPI. «Орбита» сохраняется.
   Формат берётся из handoff Claude/Codex 2 и проверяется на их схемах.
4. До оценки фиксируются gold: явные задачи, цитаты, исполнитель, срок, допустимые
   формулировки; ≥15 вопросов со ссылками/отказами; injection/cancel/unknown/private.
5. Настоящая модель: recall ≥80% на каждой из 3 расшифровок и в целом; precision,
   ложные задачи, ошибки владельца/срока, цитаты, latency. Взаимно однозначное
   сопоставление, смысл подтверждается цитатой; спорное — ручная проверка.
   Та же модель не единственный судья. Отчёт: model/version, commit, параметры,
   время, dataset, фактические наблюдения. Недоступна модель → NOT RUN, не PASS.
6. Отдельный текстовый путь без голосовых весов. Проверить env/seed/start/2 учётки/
   shutdown/хранение/удаление. Измерить установку, запросить независимый повтор.
   Не обещать 15 минут; скачивания/размеры фиксировать по источникам.
7. Cleanup: dry-run, абсолютный явный путь, флаг подтверждения, запрет рабочего
   default без отдельного согласия. Не стирать data/ для smoke. Тесты — временные БД.
   Политика: запросы/файлы/транскрипты/результаты/аудит/backup и сроки.
8. Реестр фактических библиотек/моделей/заимствований с версиями/commit/лицензиями;
   код и веса отдельно, без технологий только из ресерча и догадок об ограничениях.
9. Чистый CI CPU без секретов: meetings/voice-routing/gateway, новые тесты,
   UI по команде Codex 1, syntax/diff. Live — отдельный локальный запуск.
   Соответствие ТЗ, архитектура/потоки, API, демо 5–7 мин, ≤10 слайдов, ограничения.

## Интеграция

Проверить PR и пути: ядро/миграции → knowledge/overview → UI → release.
Регистрацию зависимых импортов выполняет Claude. Выпуск не сливается в main
до готовности целого. После целевых тестов — релевантные общие, настоящий HTTP/UI,
перезапуск, обе роли, отказ с аудитом, cancel/confirm, QA и KPI. Одно выделенное окно
GPU для трёх расшифровок без тяжёлых параллельных запросов. Старые «3 из 3»
MEETINGS.md не являются новыми измерениями.

## Команды проверки (после интеграции)

```bash
python -m pytest -q tests/test_meetings.py tests/test_meeting_voice.py tests/test_meeting_voice_mode.py tests/test_llm_gateway.py tests/test_track3*.py
node --check static/meetings.js
node --check static/meetings/track3.js
node --test tests/*.cjs
python -m unittest discover -s tests/ui_track3 -p 'test_browser.py' -v
git diff --check
```

## Критерии готовности

- Все поставки слиты в integration, нет неразрешённых замечаний по владению/контракту.
- Чистая установка и независимый повтор измерены; пользовательский путь проверен.
- Gold зафиксирован отдельным коммитом до live; recall и source/ACL проверки пройдены.
- Passed/failed/not run разделены, риски и лицензии проверены; нет замены live двойником.
- Опубликованы integration SHA и PR. Если доступа нет — только локальные коммиты,
  точная причина блокировки. NOT RUN обязательного критерия блокирует выпуск.
