# Track 3 release status — 11.11.2026

**НЕ ГОТОВ К ВЫПУСКУ.** Обе ветки опубликованы; открыт [draft PR #4](https://github.com/yougmilee2642-a11y/iug6767hhh/pull/4). Codex 3 main не менял; обновление main сопровождающим учтено обычным merge.
Точные commit в machine reports относятся к проверенному коду, не к последующим
документационным checkpoint. Итоговый integration SHA выводится в handoff/сообщении.

## Поставки и происхождение

| Пакет | Проверенная ветка / SHA | PR |
|---|---|---|
| Core, roles, migrations v8, calendar | claude/track3-core-calendar / cd06b4d696147805ed0f2a4dfa62e485a1b6d865 | #2 (draft у автора) |
| Knowledge, overview | codex/track3-knowledge-overview / e03536b027fe20364d4233d4ffe35077340a5e2a | #1 |
| UI | codex/track3-ui / d95b252e237e02141028359efa9023f50bf4497f | #3 |
| Assignment / frozen gold | release: 9a51a28 / 9d1c2dc | Опубликовано; mapping SHA в reports/publication-map.json |
| Integration | codex/track3-integration, merge в отдельной clone/worktree | Опубликовано; mapping SHA в reports/publication-map.json |

Пути каждого PR сверены через GitHub changed filenames и локальный diff от базы.
Пакеты не меняют app.py/providers/ASR/старые requirements/start-gateway.ps1. Новые
backend textutil helper и tests/test_meetings.py входят только в авторский core PR.
Codex 3 меняет лишь свою release-зону; verify_ownership.py проверяет её автоматически.

## Проверки: passed

- 203 passed, 10 skipped по общей целевой команде, 23.00 s на срезе 2d3eb95;
  10 skips — явные opt-in real Ollama/real-model HTTP tests. Полный лог reports/python.log.
  После safe-reset/test-isolation изменения на f2bf0c2 дополнительно прошли 13 release-тестов и два CLI reset.
  Неудачный промежуточный запуск из смешанных checkout исправлен выбором ROOT в check.py; итоговый лог не смешивает процессы.
- 46/46 Node regressions и syntax трёх модулей, повтор после финального UI merge на 419e41a; reports/javascript.log. Речевые алгоритмы не менялись;
  Python базовые meetings/voice-routing/gateway включены в целевой набор.
- Настоящий HTTP существующего app.py, **без двойника LLM**: 30 запросов (точный список
  в reports/http.json), две роли/404/403/аудит, ручной протокол→confirm без дублей,
  task cancel/confirm, calendar cancel/confirm/local_outbox, QA-отказ по 2030,
  KPI 90/2/75 и 2 open/1 overdue, cookies/состояние после перезапуска.
  2.98 s на f2bf0c2; torch отсутствует, речевые веса не нужны. Grounded QA/генерацию он не доказывает.
- Новый seed повторяется без новых строк, совместим с отдельной «Орбитой».
- Повтор установки в чистый venv: 22.11 s, в том числе pip 19.83 s, **тёплый кэш**,
  тот же участник. Скачивания модели/первый cold start исключены; reports/install.json.
- pip check: зависимости согласованы. Изолированные test DB; data/ не очищалась.

## Failed / not run

| Статус | Проверка | Причина / следующий шаг |
|---|---|---|
| PASSED в GitHub CI | Chromium UI suite | 35/35 сценариев, 41.260 s. Первоначальный локальный setup оставлен в reports/browser-blocked.log; это ограничение локальной среды, закрыто внешним CI-прогоном |
| NOT RUN | 3 расшифровки и 16 вопросов на настоящей модели | Loopback Ollama metadata preflight: ConnectError. reports/live-not-run.json. Нужны разрешённый gateway/установленная модель и одно согласованное GPU-окно |
| NOT RUN | Новый recall ≥80%, precision/false tasks/latency | Модель не отвечала; значений нет. Эталон и оценщик готовы, прежняя «Орбита 3 из 3» не засчитывается |
| NOT RUN | Независимая установка другим участником | Сценарий и точные зависимости готовы, но другой участник здесь не выполнял установку |
| PASSED | GitHub CI | [run 43030022726](https://github.com/yougmilee2642-a11y/iug6767hhh/actions/runs/43030022726): 203 Python passed/10 skipped; 46 JS; 35 browser; HTTP/restart; install/pip check/syntax/diff. reports/github-ci.json; актуальный head — Checks PR #4 |
| RESOLVED | Публикация | Выбран подключённый yougmilee2642-a11y с push=true; обе ветки опубликованы через GitHub API, PR #4 draft. Отдельный release → integration PR не нужен: release уже включён в integration. Первоначальная блокировка Primary Listopad33 оставлена в истории |
| PENDING | Согласование общего CONTRACT | Файлов не было на remote; восстановлен проект контракта, согласование не выдумывается |
| PENDING | Лицензирование поставки | PyMuPDF dual AGPL/commercial и неподтверждённые условия конкретных voice-assets; LICENSES.md |

Полный проектный pytest всех треков не запускался в новом минимальном окружении:
выполнены целевые и релевантные общие проверки; голосовые веса/GPU не установлены.
Физический микрофон и реальная почта не проверялись. Реальной почты в test calendar нет.

## Соответствие ТЗ

| Пункт | Поставка | Состояние |
|---|---|---|
| 1 Инструкции/база/ветки | Первый release commit 9a51a28; docs/track3-team | Опубликовано; согласование CONTRACT pending |
| 2 Защищённый MeetingLLM | Общий endpoint(), Bearer, no redirects/proxy/cloud; unit checks | Passed |
| 3 Фотопринт | 24 деловых документа, 3 transcript, ACL/status/calendar/KPI; idempotent seed | Passed в интеграции |
| 4 Gold/QA | 18 задач, 16 вопросов, frozen SHA до оценки | Готово |
| 5 Реальная оценка | evaluate.py + независимый review, сохранение raw evidence | Реальная модель NOT RUN |
| 6 Текстовый запуск | Existing app.py без torch/голосовых весов; RUNBOOK | HTTP passed; независимый повтор pending |
| 7 Очистка/хранение | Marker, absolute path, dry-run, explicit confirm; RETENTION | Passed unit/integration, политика ручная |
| 8 Лицензии | Lock, metadata inventory, отдельные code/weights | Текстовый inventory готов; указанные license gates pending |
| 9 CI/документы/демо | Workflow, API, architecture, 5–7 мин, 10 слайдов | Документы готовы; UI и CPU CI passed на GitHub runner |

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

Финальный UI owner update d95b252 добавлен обычным merge: зоны времени и retry.
Python-продуктовые файлы он не менял. Локально повторены JS/syntax/diff, браузерные
35 сценариев прошли на GitHub runner; исходное локальное ограничение Chromium сохранено как историческое наблюдение.

При публикации собственные commit SHA изменились из-за авторских метаданных API,
**git tree каждого из 31 коммитов совпал с исходным локальным**. История коллег
не переписывалась. Первоначальный gold commit 9d1c2dc опубликован как ca06d6eba2fe697073609181d40f1dfe24e3f459.
Старые machine reports сохраняют первоначальные commit ID; соответствие — publication-map.json.

Внешний чистый CPU runner подтвердил установку lock и полный pipeline. Это
самостоятельный прогон CI, но не обещанный независимый повтор другим участником
и не проверка модели: эти два gate остаются открытыми.


## Аудит после первой публикации

Реальные дефекты оценщика воспроизведены отдельно от модели: отрицание давало
recall=1; три delay давали passed; QA с неподтверждённым claim проходила при наличии
настоящей цитаты. Это были дефекты **проверок выпуска**, не новые результаты Qwen.
Они закрыты scorer v2 с регрессиями; frozen dataset/gold не менялись.

Дополнительно закрыты перезапись первичных отчётов и потеря маркера очистки при
частичном filesystem failure. Checkpoints и interrupted сохраняются, review не
вызывает модель. Doctor с read-only metadata проверкой остаётся not_ready:
URL/ключ/model env отсутствуют, loopback даёт ConnectError. Исходный отчёт —
reports/doctor-audit.json. Новый CI включает реальный браузерный HTTP-сценарий;
его результат оценивается по актуальным Checks PR #4, отдельно от старого pipeline.


Проверки аудита: **228 passed, 10 opt-in skipped, 26.35 s**; полный исходный лог
reports/audit-python.log. Frozen dataset и gold byte-for-byte совпадают с первой
публикацией. GitHub CI текущего аудита проверяет также новый UI → HTTP harness;
актуальный результат и опубликованный head находятся в PR #4. Никакое из этих
чисел не является recall/precision настоящей модели.


## Совместная проверка новых поставок PR #7 / #8

11.11.2026 main сопровождающего `35ba34c`, knowledge `9eecb94` и eval fixes
`58ec401` включены обычными merge, без переписывания истории и ручной правки
чужой логики. На локальном интеграционном срезе `380b2a9`: **251 passed,
15 skipped, 3 failed**, 44.25 s. Исходный лог: reports/joint-python.log.
Это актуальная регрессия интеграции; предыдущие успешные CI относятся к прежним SHA.

Три failed относятся к knowledge: отображение заголовка вместо одной цитаты,
два расхождения политики отказа/расширения legacy-цитаты. Дополнительная проверка
подтвердила, что валюта и условие предоплаты сохраняются в полном исходном тексте;
их фактическая потеря не подтверждена.
Владельцам отправлены воспроизведения в PR #7/#8; их тесты не ослаблены.
До авторского исправления эти проверки блокируют выпуск.

Исправления UTF-8 из PR #6 адаптированы к scorer v2 в разрешённых release-путях.
LF задаётся вложенными .gitattributes внутри demo/track3 и evaluation/track3,
корневой .gitattributes не изменялся. Windows CI проверяет без PYTHONUTF8 mode.
Linux CI запускает независимые JS/UI/HTTP/syntax шаги и при падении Python suite,
чтобы получить полный отчёт, сохраняя failed итог workflow.

В PR #8 автор сообщил новые числа Qwen2.5:7b. Пока доступна только повествовательная
таблица; исходные JSON запрошены. Они не засчитываются независимым результатом
scorer v2. Настроенный model endpoint/GPU здесь по-прежнему отсутствует.


При сверке границ найден отдельный дефект собственного QA-оценщика: перенос строки
или точка в «тыс.» могли считаться допустимой границей обрезанной цитаты. Scorer v3
устраняет этот обход независимо от product helper, с отрицаниями/инициалами/валютой
в регрессиях. Schema остаётся 2; старые отчёты сохраняют scorer_version=2 и не
переименовываются. Gold/expected не меняются.


Windows clean CI на опубликованном `3046943` прошёл: **68 passed, 7.91 s**,
PYTHONUTF8=0, [job 130585515388](https://github.com/yougmilee2642-a11y/iug6767hhh/actions/runs/43039018306/job/130585515388).
Scorer v3 после этого локально: **73 passed, 2.01 s**, reports/scorer3-python.log.
Новый общий прогон всё ещё блокируют три упомянутых owner-разногласия; старые зелёные
прогоны их не закрывают. 46 JS passed; новый HTTP/restart без LLM double прошёл
за 3.84 s, reports/joint-http.json.

Первичный joint Python log сохранён побайтно в reports/joint-python.raw.log.gz;
SHA256 в reports/joint-checks.json. Читаемая .log-копия удаляет только trailing
whitespace, чтобы syntax/diff gate не ломался на pytest presentation.
Preflight v3: NOT RUN на gpu_window, 0 LLM calls; отчёт сохранён отдельно от v2.


CI порядок уточнён: CPU/Python/JS/HTTP/syntax выполняются до установки Chromium,
чтобы загрузка браузера не задерживала продуктовую диагностику. У browser install
есть отдельный timeout 5 минут; его отказ не скрывается зелёным статусом.


Полный повтор после scorer v3: **256 passed / 15 skipped / 3 failed**, 29.42 s.
Исходный байтовый лог и hash — reports/scorer3-joint-python.raw.log.gz и
reports/scorer3-joint-checks.json; readable — scorer3-joint-python.log.
Это те же три owner-разногласия, новых failures от scorer v3 нет.
CI запускается по PR или вручную, без дублирующего push; superseded PR run
может отменяться новым run и не засчитывается ни passed, ни product failure.


Завершён Linux CI на `3046943` (merge `1ad3d2a`): overall FAILED. Причина установки
— DNS azure.archive.ubuntu.com при --with-deps, а не недоступный Chromium. Фактически
**35 UI passed (42.398 s)**; браузер → реальный HTTP **passed**, 44 ответа,
360/768/1440, 0 browser errors, настоящий calendar conflict 409, явный LLM double.
Product HTTP без LLM double тоже passed (3.53 s). Python suite тогда skipped после
install failure; diff failure из trailing whitespace уже закрыт отдельно.
Машинная выжимка: reports/joint-ci-observations.json; весь workflow не назван зелёным.

В текущем workflow browser install больше не вызывает apt --with-deps: на проверенном
ubuntu-24.04 runner необходимые библиотеки и рабочий Chromium уже есть. Явная
установка Playwright Chromium сохранена; реальный launch/UI suite проверяют пригодность
браузера. Если системных библиотек на другом runner нет, сценарий упадёт явно.
