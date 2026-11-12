# Codex 3 — передача выпуска и интеграции

**Выпуск не готов.** Ветки codex/track3-release и codex/track3-integration опубликованы;
[Draft PR #4](https://github.com/yougmilee2642-a11y/iug6767hhh/pull/4) содержит актуальный
integration SHA, Checks и список blockers. База cb2614b86f3b83636e670c83a0afb8f4c9d6c3c3.
Отдельные clone/worktree; main Codex 3 не менял, обновление сопровождающего e3d37e3
включено обычным merge. Коллегам rebase не требуется.

## Поставка

- Первый собственный commit — инструкции/SHA/ветки/команды. Отсутствовавшие README/
  CONTRACT восстановлены как проект, согласование не выдумано.
- Отдельный frozen gold до оценки: 24 synthetic TXT документов деловых типов,
  3 transcript, 18 явных задач, 16 QA cases. Local 9d1c2dc опубликован как ca06d6e.
- MeetingLLM через существующий providers.ollama.endpoint(): Bearer, no redirects/
  env proxy/cloud, loopback defaults, прежние schema/think/лимиты/timeout.
- Idempotent seed, две роли/ACL, tasks/calendar/KPI; безопасные start/cleanup/check
  на временных БД, без app.py/voice/provider/старых requirements изменений.
- Scorer 3/schema 2, one-to-one source-verified task matching, independent human review
  для перефразирования, raw checkpoints, новые absolute output paths, offline review.
- Lock, Linux/Windows CI, API/architecture/retention/licenses/runbook/demo/slide outline.
- Авторские core→knowledge→UI merge; затем main e3d37e3, knowledge 9eecb94 и Claude 58ec401; авторское согласование 3104d0c и UI «Фокус» 1ea0a5a.
  Зоны владения сверены. Чужая продуктовая логика вручную не исправлялась.

## Наблюдаемые проверки

Подробности, SHA и первичные артефакты: [STATUS](../track3-release/STATUS.md).

- Общий Python: 304 passed / 15 skipped / 0 failed, 35.82 s; gzip исходника и hash сохранены.
- Собственный release/gateway/scorer:73 passed локально и в clean Windows CI, PYTHONUTF8=0.
- JS 46 passed; UI 35 passed; браузер→реальный HTTP 49 responses / 3 widths / 0 errors с явным
  model double. Product HTTP без LLM double прошёл обе роли/аудит/confirm/restart/KPI.
- pip/ownership/compile/final diff checks passed локально. Data/ не очищалась, torch не нужен.
- Live scorer3 **NOT RUN**: нет gateway/model env/согласованного GPU-окна, 0 inference calls.
  Старые «Орбита 3/3», fixtures и таблица результатов автора не засчитаны новым recall.

## Следующие действия владельцев

1. Knowledge #7/#8 закрыто авторским согласованием3104d0c (#10), не ручной правкой
   Codex3: проверяется полный исходный текст с валютой/условием. Общий повтор259 passed.
   Новый «Фокус» UI включён из main; финальный clean CI43043682513 на1eaee60 прошёл целиком, включая новый UI.
2. GPU/operator #8: передать исходные JSON и выполнить scorer3 в одном согласованном
   окне. Endpoint/model/key задаются через env, секреты не помещать в PR/git.
   `python scripts/live_meetings_check.py --track3 --exclusive-gpu-window --output <новый абсолютный report.json>`.
   Отдельный человек проверяет gold/спорные matches; модель не единственный судья.
3. Другой участник: независимая чистая установка по RUNBOOK, измерение с указанием
   OS/Python/cache/downloads, проверка двух ролей/restart. Текущий install 22.11 s —
   этот же участник с тёплым кэшем, без модели; это не обещание 15 минут.
4. Команда: согласовать CONTRACT. Product owner: закрыть лицензии PyMuPDF/Silero и
   неподтверждённые конкретные voice-assets по LICENSES.md. ASR/installers не патчились.
5. UI #3: уточнить empty-state «локальная модель» для разрешённого remote gateway;
   устранить внешний Google Fonts request для автономного режима либо явно согласовать
   его. Font inventory обновлён по первичному Jost OFL source, точный CDN binary не pinned.
6. Проверить финальные Checks PR #4. Исторический apt DNS failure разобран; CPU checks
   выполняются до browser install, --with-deps убран, raw whitespace сохранён gzip.

Все обязательные gates должны пройти до main merge. Не выдавать narrative результат,
пропущенный прогон или double за независимую реальную оценку. Remote host получает
данные; Cloudflare — внешний посредник, не полностью локальный режим у пользователя.

Итоговое наблюдение: reports/focus-ci.json, 259 passed/15 skipped/0 failed; Windows73,
JS46, browser35, real HTTP49 responses/3 widths. Модельная оценка NOT RUN.

Срез main для передачи — e3d37e3 (#9 voice MVP), включён обычным merge. После него
304 passed/15 skipped/0 failed, JS46, voice JS syntax и text HTTP/restart passed
без torch/voice weights. reports/voice-integration-*. Новые voice-тесты работают
на doubles, а реальный микрофон/ASR/TTS здесь NOT RUN. Последующие main-изменения
рассматриваются отдельной поставкой.

Текущий blocker voice UI: clean CI43046459529 на646bb037 подтвердил304 Python passed,
Windows/JS/UI-fixtures/product HTTP passed, но реальный browser→HTTP упал на
root horizontal overflow360px (http_browser_smoke.py:105). Автору #9 отправлены
точный SHA/команда/trace. Assertions и foreign CSS/JS не ослаблялись. Harness теперь
сохраняет screenshot/DOM geometry после failed, не превращая его в passed.

Точная причина mobile overflow: viewport360/document371, account row и logout
right370.765625px;768/1440 корректны. Источник: reports/voice-layout-diagnostics.json,
CI43048167863 на be1fd6b. Owner #9 получил измерения; нужен его CSS fix. Последний
checkpoint — только отчёт/политика, функциональный код не меняет.
