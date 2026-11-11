# Track 3 — состояние выпуска, 11.11.2026

**Выпуск заблокирован.** [Draft PR #4](https://github.com/yougmilee2642-a11y/iug6767hhh/pull/4)
содержит актуальный integration SHA и Checks. Ветки release/integration опубликованы.
Codex 3 main не менял; обновление main сопровождающим `0e99e32` включено обычным merge.

## Состав и владение

База задания: `cb2614b86f3b83636e670c83a0afb8f4c9d6c3c3`.

| Поставка | Включённый авторский SHA / PR |
|---|---|
| Core, migration v8, роли, календарь | `cd06b4d` / #2; затем main сопровождающего `0e99e32` |
| Knowledge, overview, KPI | `9eecb94` / #7, поверх исходного #1 |
| Отмена поручений, разные задачи с общим сроком, legacy QA | Claude `58ec401` / #8 |
| UI | `d95b252` / #3; «Фокус» `1ea0a5a`, включённый сопровождающим |
| Согласование knowledge | `3104d0c` / #10: точный полный answer/source вместо обрезанной цитаты |
| Release | `codex/track3-release`; scorer 3, schema 2 |
| Интеграция | `codex/track3-integration`; обычные merge без rebase авторов |

Собственный release diff проверяет `scripts/track3/verify_ownership.py`: запрещённых
путей нет. app.py/providers/ASR/старые requirements/frontend/start-gateway.ps1
Codex 3 не редактировал. Интеграционные замечания чужой логики возвращены владельцам.

## Passed

| Проверка | Наблюдение и предел применимости |
|---|---|
| Release/gateway/scorer v3 | 73 passed локально, 2.01 s; [Windows CI](https://github.com/yougmilee2642-a11y/iug6767hhh/actions/runs/43043682513/job/130601886677): 73 passed, 8.25 s, PYTHONUTF8=0 |
| Общий Python после нового main | **259 passed, 15 skipped, 0 failed**, 30.17 s; reports/focus-checks.json и focus-python.* |
| JavaScript | 46 passed; syntax трёх UI-модулей. reports/focus-javascript.log |
| Настоящий app HTTP/restart | Без LLM double: две роли, ACL/аудит отказа, ручной protocol→confirm без дублей, task/calendar cancel-confirm, KPI 90/2/75, cookies/state после restart. 4.08 s; reports/focus-http.json |
| Browser fixtures | 35 passed, 65.406 s на «Фокус» `1eaee60` / merge `353099b`; [CI job](https://github.com/yougmilee2642-a11y/iug6767hhh/actions/runs/43043682513/job/130601886953) |
| Browser → настоящий HTTP | 49 ответов, 360/768/1440, 0 browser errors, настоящий calendar conflict409, сохранён unknown due; 6.13 s. **Явный LLM double**, качество модели не измерялось |
| Изоляция | Временные БД, torch отсутствует, voice weights не нужны; data/ не очищалась |
| Данные | 24 synthetic TXT деловых типов, 3 transcript; отдельный идемпотентный seed, совместим с «Орбитой»; gold 18 tasks/16 QA frozen до оценки |
| Установка этим участником | Чистый venv 22.11 s, pip 19.83 s, **тёплый кэш**; без модели/cold downloads, reports/install.json |
| Зависимости/целостность | pip check, ownership, compile и финальный diff check passed локально; frozen inputs byte-for-byte сохранены, в том числе Windows autocrlf |

Пройденные проверки отдельных компонентов не означают passed всего выпуска.
Даты/commit в первичных отчётах относятся к моменту наблюдения. Позднейшая правка
документации не является новым прогоном. Первоначальные local/API SHA сопоставлены
в reports/publication-map.json; дальнейшие коммиты имеют Source-Local-Commit trailer.
Git tree каждого опубликованного коммита сверялся с исходным локальным.

**Чистый итоговый CI на `1eaee60` прошёл целиком:** Linux 259/15/0, Windows 73,
JS 46, UI 35, оба HTTP, pip/syntax/diff. reports/focus-ci.json и focus-ci-*-http.json.
Это наблюдение кода на указанном SHA; следующий отчётный commit не является новым
модельным прогоном. Актуальные Checks всегда находятся в PR #4.

## Закрытые сбои и история проверок

Текущий общий Python не имеет failed. Три расхождения #7/#8 закрыты **авторским**
согласованием `3104d0c`: тесты требуют полный исходный answer/source с валютой и
предоплатой. Заголовок без полной остановки считается частью исходного предложения;
политика явно описана автором. Codex 3 foreign-тесты и product logic не редактировал.

Предыдущие 259/256/251 — разные наблюдения, не суммируются. На старом `0844d0e`
clean CI имел 256 passed/15 skipped/3 failed, остальные steps прошли;
reports/scorer3-ci-observations.json. Raw bytes и hashes исторических локальных
сбоев сохранены в scorer3-joint-* и joint-*.

Исторический Linux CI на 3046943 провалил apt DNS и whitespace readable log,
хотя 35 UI и оба HTTP прошли; reports/joint-ci-observations.json. Эти причины
исправлены: CPU диагностика первая, исходный raw log в gzip, readable без лишних
пробелов. Browser setup использует уже доступный Chromium или явно устанавливает
его при отсутствии; реальный launch проверяют UI suites. Setup ограничен 5 минутами.
Старый failed workflow не объявлен зелёным.

## Not run / открытые критерии

| Критерий | Что требуется |
|---|---|
| Recall≥80% для каждой из 3 расшифровок и в целом, precision/ошибки/latency | Реальная модель, разрешённый gateway и согласованное отдельное GPU-окно. Preflight v3: NOT RUN на gpu_window, 0 LLM calls; reports/evaluation-preflight-v3.json. Loopback doctor: ConnectError, env URL/key/model отсутствуют |
| Независимая проверка модельных чисел коллеги | В #8 запрошены исходные JSON. Повествовательная таблица Qwen2.5:7b не засчитана независимым scorer-v3 результатом; gold не подгонялся |
| Независимая установка другим участником / gold review | Пройти RUNBOOK, измерить время/кэш/модель, проверить обе роли/restart и спорные matches. Тестовый сценарий human-authored не заменяет человеческого участника |
| Общий CONTRACT | Восстановленный проект требует согласования команды |
| Лицензии поставки | Решение владельца по PyMuPDF AGPL/commercial, Silero NonCommercial/base-CIS exception; точная идентификация неподтверждённых voice assets. LICENSES.md, без догадок по лицензии кода |

15 skips общего набора — opt-in сценарии настоящей модели и другие явно пропущенные
проверки; они не засчитаны как passed. Полный pytest остальных треков, физический
микрофон и доставка настоящей почты не проверялись. Календарь — local outbox/mock.

## Соответствие заданию и пределы

Пакет заданий был первым собственным коммитом; frozen gold — отдельным до оценки.
Защищённый MeetingLLM, seed, безопасная очистка, оценщик, lock, CI, API, архитектура,
retention, сценарий 5–7 минут и структура≤10 слайдов поставлены в разрешённых путях.
Формат seed проверен на миграциях авторов; dependent imports добавлял Claude.

Scorer v2 устранил substring/отрицание, дублирование контроля и claim без опоры.
Scorer v3 дополнительно закрыл обрезание цитат после «тыс.»/инициалов/переноса строки
независимой проверкой. Это исправления проверок, **не результаты модели**. Старые
отчёты сохраняют свою версию; expected/frozen gold не менялись.

Remote gateway обрабатывает данные на машине хоста; Cloudflare добавляет внешнего
посредника. Такой режим не полностью локален на машине пользователя. UI-владельцу
в #3 передана просьба уточнить текст empty state «локальная модель». Новый «Фокус»
загружает Jost через Google Fonts: это внешний asset request, не inference. Полностью
автономный UI пока не подтверждён; запрос self-host/system fallback передан владельцу.

Синтетический набор не доказывает качество на реальных встречах. SSO, публичный
production deployment, encrypted-at-rest, настоящая почта и автоматическая
диаризация не входят в выпуск. Обязательный NOT RUN или неразрешённый failed
блокирует готовность по docs/track3-team/README.md.
