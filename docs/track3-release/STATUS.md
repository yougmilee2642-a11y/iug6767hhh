# Track 3 — состояние выпуска, 11.11.2026

**Выпуск заблокирован.** [Draft PR #4](https://github.com/yougmilee2642-a11y/iug6767hhh/pull/4)
содержит актуальный integration SHA и Checks. Ветки release/integration опубликованы.
Codex 3 main не менял; обновление main сопровождающим включено обычным merge.

## Состав и владение

База задания: `cb2614b86f3b83636e670c83a0afb8f4c9d6c3c3`.

| Поставка | Включённый авторский SHA / PR |
|---|---|
| Core, migration v8, роли, календарь | `cd06b4d` / #2; затем main сопровождающего `35ba34c` / #5 |
| Knowledge, overview, KPI | `9eecb94` / #7, поверх исходного #1 |
| Отмена поручений, разные задачи с общим сроком, legacy QA | Claude `58ec401` / #8 |
| UI | `d95b252` / #3 |
| Release | `codex/track3-release`; scorer 3, schema 2 |
| Интеграция | `codex/track3-integration`; обычные merge без rebase авторов |

Собственный release diff проверяет `scripts/track3/verify_ownership.py`: запрещённых
путей нет. app.py/providers/ASR/старые requirements/frontend/start-gateway.ps1
Codex 3 не редактировал. Интеграционные замечания чужой логики возвращены владельцам.

## Passed

| Проверка | Наблюдение и предел применимости |
|---|---|
| Release/gateway/scorer v3 | 73 passed локально, 2.01 s; [Windows CI](https://github.com/yougmilee2642-a11y/iug6767hhh/actions/runs/43041468303/job/130596033605): 73 passed, 7.34 s, PYTHONUTF8=0 |
| Общий Python: прошедшая часть | 256 passed; весь набор **не прошёл**, см. failed ниже. reports/scorer3-joint-* |
| JavaScript | 46 passed; syntax трёх UI-модулей. reports/joint-javascript.log |
| Настоящий app HTTP/restart | Без LLM double: две роли, ACL/аудит отказа, ручной protocol→confirm без дублей, task/calendar cancel-confirm, KPI 90/2/75, cookies/state после restart. 3.84 s; reports/joint-http.json |
| Browser fixtures | 35 passed, 39.744 s на `0844d0e` / merge `79862bb`; [CI job](https://github.com/yougmilee2642-a11y/iug6767hhh/actions/runs/43041468303/job/130596032970) |
| Browser → настоящий HTTP | 44 ответа, 360/768/1440, 0 browser errors, настоящий calendar conflict409, сохранён unknown due; 5.66 s. **Явный LLM double**, качество модели не измерялось |
| Изоляция | Временные БД, torch отсутствует, voice weights не нужны; data/ не очищалась |
| Данные | 24 synthetic TXT деловых типов, 3 transcript; отдельный идемпотентный seed, совместим с «Орбитой»; gold 18 tasks/16 QA frozen до оценки |
| Установка этим участником | Чистый venv 22.11 s, pip 19.83 s, **тёплый кэш**; без модели/cold downloads, reports/install.json |
| Зависимости/целостность | pip check, ownership, compile и финальный diff check passed локально; frozen inputs byte-for-byte сохранены, в том числе Windows autocrlf |

Пройденные проверки отдельных компонентов не означают passed всего выпуска.
Даты/commit в первичных отчётах относятся к моменту наблюдения. Позднейшая правка
документации не является новым прогоном. Первоначальные local/API SHA сопоставлены
в reports/publication-map.json; дальнейшие коммиты имеют Source-Local-Commit trailer.
Git tree каждого опубликованного коммита сверялся с исходным локальным.

## Failed

Общий повтор scorer v3: **256 passed / 15 skipped / 3 failed**, 29.42 s.
Начальный checkout и hash исходного лога — reports/scorer3-joint-checks.json.
Raw bytes сохранены в scorer3-joint-python.raw.log.gz; readable .log убирает только
trailing whitespace. Предыдущий совместный прогон 251/15/3 сохранён отдельно.

Чистый CI на `0844d0e` подтвердил те же **256/15/3**, 42.94 s; Windows 73,
JS 46, UI 35, оба HTTP, browser setup, pip/syntax/diff прошли. Overall workflow
**FAILED** из-за Python. reports/scorer3-ci-observations.json.

Все три failed находятся в knowledge после совместного #7/#8:

1. `test_claim_text_may_copy_document_heading_around_the_quote`: ответ включает
   заголовок/дату вместо ожидаемой одной цитаты факта.
2. Два `test_excerpt_boundaries_cannot_drop_currency_or_newline_condition`: тест #7
   требует отказ, а #8 безопасно расширяет частичную цитату до полного исходного
   предложения. Прямая проверка подтвердила сохранение валюты и предоплаты;
   фактическая потеря условия **не подтверждена**. Нужна согласованная политика
   владельца с проверкой точного output, не снятие assertions.

Воспроизведение направлено владельцам в #7/#8. Codex 3 их логику/тесты не правил.

Исторический Linux CI на 3046943 завершился FAILED: DNS azure.archive.ubuntu.com
при `playwright install --with-deps` и whitespace в readable raw pytest log.
Несмотря на это, JS/UI/оба HTTP шага прошли; Python suite тогда был skipped.
Причины зафиксированы в reports/joint-ci-observations.json. Сейчас CPU диагностика
выполняется первой; apt --with-deps убран, установка Chromium выполняется явно при отсутствии исполняемого файла и
ограничена 5 минутами. Наличие файла не считается passed: UI suites обязаны
успешно запустить его, как в точной команде владельца. Whitespace устранён отдельной readable копией при сохранении
байтового raw gzip. Это не превращает старый workflow в зелёный.

## Not run / открытые критерии

| Критерий | Что требуется |
|---|---|
| Recall≥80% для каждой из 3 расшифровок и в целом, precision/ошибки/latency | Реальная модель, разрешённый gateway и согласованное отдельное GPU-окно. Preflight v3: NOT RUN на gpu_window, 0 LLM calls; reports/evaluation-preflight-v3.json. Loopback doctor: ConnectError, env URL/key/model отсутствуют |
| Независимая проверка модельных чисел коллеги | В #8 запрошены исходные JSON. Повествовательная таблица Qwen2.5:7b не засчитана независимым scorer-v3 результатом; gold не подгонялся |
| Независимая установка другим участником / gold review | Пройти RUNBOOK, измерить время/кэш/модель, проверить обе роли/restart и спорные matches. Тестовый сценарий human-authored не заменяет человеческого участника |
| Общий CONTRACT | Восстановленный проект требует согласования команды |
| Лицензии поставки | Решение владельца по PyMuPDF AGPL/commercial, Silero NonCommercial/base-CIS exception; точная идентификация неподтверждённых voice assets. LICENSES.md, без догадок по лицензии кода |
| Финальный CI на последнем head | Checks PR #4. Старые зелёные run и отдельные прошедшие jobs не сертифицируют новый head |

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
в #3 передана просьба уточнить текст empty state «локальная модель».

Синтетический набор не доказывает качество на реальных встречах. SSO, публичный
production deployment, encrypted-at-rest, настоящая почта и автоматическая
диаризация не входят в выпуск. Обязательный NOT RUN или неразрешённый failed
блокирует готовность по docs/track3-team/README.md.
