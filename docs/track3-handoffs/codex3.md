# Codex 3 — передача выпуска и интеграции

**Выпуск не готов.** Ветки codex/track3-release и codex/track3-integration опубликованы;
[Draft PR #4](https://github.com/yougmilee2642-a11y/iug6767hhh/pull/4) содержит актуальный
integration SHA, Checks и список blockers. База cb2614b86f3b83636e670c83a0afb8f4c9d6c3c3.
Отдельные clone/worktree; main Codex 3 не менял, обновление сопровождающего35ba34c
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
- Авторские core→knowledge→UI merge; затем main 35ba34c, knowledge 9eecb94 и Claude 58ec401.
  Зоны владения сверены. Чужая продуктовая логика вручную не исправлялась.

## Наблюдаемые проверки

Подробности, SHA и первичные артефакты: [STATUS](../track3-release/STATUS.md).

- Общий Python: 256 passed / 15 skipped /**3 failed**, 29.42 s; gzip исходника и hash сохранены.
- Собственный release/gateway/scorer:73 passed локально и в clean Windows CI, PYTHONUTF8=0.
- JS 46 passed; UI 35 passed; браузер→реальный HTTP 44 responses / 3 widths / 0 errors с явным
  model double. Product HTTP без LLM double прошёл обе роли/аудит/confirm/restart/KPI.
- pip/ownership/compile/final diff checks passed локально. Data/ не очищалась, torch не нужен.
- Live scorer3 **NOT RUN**: нет gateway/model env/согласованного GPU-окна, 0 inference calls.
  Старые «Орбита 3/3», fixtures и таблица результатов автора не засчитаны новым recall.

## Следующие действия владельцев

1. Knowledge #7/#8: согласовать 3 failed. Heading/date показываются вместо одной цитаты;
   два других — противоречие политики отказа и безопасного расширения partial quote.
   Валюта/предоплата сохраняются; потери условия не подтверждено. Воспроизведения в PR.
2. GPU/operator #8: передать исходные JSON и выполнить scorer3 в одном согласованном
   окне. Endpoint/model/key задаются через env, секреты не помещать в PR/git.
   `python scripts/live_meetings_check.py --track3 --exclusive-gpu-window --output <новый абсолютный report.json>`.
   Отдельный человек проверяет gold/спорные matches; модель не единственный судья.
3. Другой участник: независимая чистая установка по RUNBOOK, измерение с указанием
   OS/Python/cache/downloads, проверка двух ролей/restart. Текущий install 22.11 s —
   этот же участник с тёплым кэшем, без модели; это не обещание 15 минут.
4. Команда: согласовать CONTRACT. Product owner: закрыть лицензии PyMuPDF/Silero и
   неподтверждённые конкретные voice-assets по LICENSES.md. ASR/installers не патчились.
5. UI #3: уточнить empty-state «локальная модель» для разрешённого remote gateway.
6. Проверить финальные Checks PR #4. Исторический apt DNS failure разобран; CPU checks
   выполняются до browser install, --with-deps убран, raw whitespace сохранён gzip.

Все обязательные gates должны пройти до main merge. Не выдавать narrative результат,
пропущенный прогон или double за независимую реальную оценку. Remote host получает
данные; Cloudflare — внешний посредник, не полностью локальный режим у пользователя.
