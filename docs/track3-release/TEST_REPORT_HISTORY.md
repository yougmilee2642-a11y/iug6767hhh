# Проверки Фокус v2 — 12.11.2026

## Общий срез E7/E9 и текущего main ·12.11.2026

На коде после eaabf95 (основной интерфейс main сохранён):1573 passed/28 skipped,
0 failed,249.31s; Node66 passed. HTTPdouble6.41s и HTTPunavailable5.72s:
семь ролей, versions/briefing/assistant/actions, retained audio503 + download/
foreign404, calls/проблемы/source/action, CRM/ICS/restart. OpenAPI110 путей.
После замены deprecated startup-декоратора на add_event_handler отдельно
проверено7 media/recovery тестов,8.20s, без FastAPI deprecation; inference не было.

Frozen v2:30/30 строгих задач,17/17 claims,0 ошибок владельца/срока/прав/
ложных действий на scripted double. Отдельный frozen original+timed call
rules-control passed. Это проверка конвейера/правил, не live качества.
Target E7/operations/seed30, E9/assistant18, document selector10 passed.
Модельные selector-тесты используют только scripted provider.
Первичные логи/JSON: reports/v2-e7-e9-*. Новый browser/Windows CI и свежая
чистая установка этого среза фиксируются отдельно после commit.

Ниже сохранены предыдущие измерения и ограничения соответствующих срезов.


Это промежуточный отчёт P0/E14; весь объём ТЗ не завершён. Результат привязан
к commit/dirty в первичных JSON. Документационные коммиты не являются новым
прогоном модели. [Самоаудит](SELF_AUDIT.md) содержит риски каждого требования.

## Измеренные проверки

| Проверка | Результат и границы |
|---|---|
| Полный небраузерный Python | 1494 passed, 28 skipped, 0 failed, 209,53 s; `reports/v2-document-briefing-python.log`. Шесть deprecation warnings PyMuPDF; skips не считаются passed. |
| Node | 66 passed, 0 failed; `reports/v2-document-briefing-node.log` |
| Настоящий HTTP, 7 уровней | `reports/v2-document-briefing-http.json`: KPI/ACL/CRM/ICS/smart slots, версии/cancel/replay/restart; без инференса |
| Недоступная модель через настоящий HTTP | `reports/v2-document-briefing-http.json`: реальные provider/prepare/protocol/QA → 503 model_*, расшифровка не изменена; наблюдаемые коды сохранены |
| Предыдущий чистый CI | [43166951277](https://github.com/yougmilee2642-a11y/iug6767hhh/actions/runs/43166951277) на 574ab18: Linux base/runtime, Windows release/runtime, Python/Node/35 UI, browser→HTTP и evaluator success. Новые версии требуют нового CI. |
| E13 на дублёре | `reports/v2-document-integration-double.json`: pipeline_passed, 30 задач/36 вопросов; quality NOT MEASURED, не live recall |
| Первоначальный чистый base | `reports/v2-e14-initial-install.json`: 65,88 s всего; base install 25,28 s прошёл, seed упал без PDF reader; после test-профиля seed/restart прошли |
| Изолированный runtime | `reports/v2-e14-initial-runtime.json`: 12,68 s, повтор seed/HTTP passed; pytest/Playwright/torch/scipy/av/soundfile отсутствуют. Кэш pip не контролировался. Профиль был незакоммичен, код клона 3dbc30c. |
| Исправленная установка base/runtime | CI43166951277 Linux base/runtime и Windows runtime success; новые версии проверяются после commit отдельно. Кэш пакетов неконтролируемый. |
| OpenAPI | `export_api.py` из настоящего app: 73 пути; временная БД, без моделей/рабочей data/ |
| Secret scan истории | Форматы ключей/private keys/webhooks/credential URLs. Три credential-URL совпадения — один отрицательный fixture `https://u:p@example.com` в повторённой истории теста; реальных ключей этими правилами не обнаружено. Не полноценный DLP-аудит. |

## Критерии приёмки §7.5

| Критерий | Проверка | Результат |
|---|---|---|
| ≥80% явных задач | frozen 5×6, scorer v3/evaluate_v2; `test_track3_v2_evaluation.py` | Конвейер double passed; live требует хоста |
| Источник каждого утверждения | knowledge claims/excerpt integrity, core risk/summary quotes | CPU/double passed; полнота live неизвестна |
| Чужая роль получает отказ, отказ в журнале | access_matrix, core denial-survives-rollback, HTTP | Passed |
| Cancel без изменения | core/task/calendar/decision/CRM cancel tests | Passed |
| Протокол↔поручение | core confirm/idempotence, task controls; UI/HTTP navigation | Passed на предыдущем CI; новый CI обязателен |

## ОТ-01..08

| ID | Тест/доказательство | Результат |
|---|---|---|
| ОТ-01 | clean_install base/runtime Linux/Windows | CI43166951277 success для Linux base/runtime и Windows runtime; новый head проверяется отдельно, первоначальные ошибки сохранены |
| ОТ-02 | `test_access_matrix.py`, HTTP семи уровней, отозванные права/истёкшее делегирование | Passed |
| ОТ-03 | `test_fotoprint_seed.py`, генератор и хеши v1/v2 | Passed |
| ОТ-04 | core/privacy audit/filter/CSV/logout; auditor/director/head-scope | Passed |
| ОТ-05 | real unavailable HTTP, model error/garbage/timeout tests, CRM uncertain | Passed на CPU/локальном HTTP |
| ОТ-06 | UI35 + v2 browser, русские сообщения | Предыдущий CI passed, новый ожидается; ручной аудит неполон |
| ОТ-07 | management/domain_metrics/decision_controls/calendar time tests | Passed |
| ОТ-08 | LICENSES + metadata/notice hashes | Частично: юридические решения не заменяются тестами |

## Шесть веток лекции — карта покрытия

Сокращения: core=`test_track3_core.py`, QA=`test_track3_knowledge.py`,
CRM=`test_track3_crm.py`, calendar=`test_track3_calendar.py`,
KPI=`test_track3_management.py`. Все файлы в `tests/`.
«Частично» означает пробел, а не пройденный критерий.

| Функция | Обычный путь | Нет прав | Повтор | Нет данных | Источник недоступен | Устаревание |
|---|---|---|---|---|---|---|
| QA | QA grounded/dated/source | QA each_document_acl | QA saved/revalidated | QA no_relevant_data | QA saved source revoked/corrupt; hardening tests | v2 stale controls + retrieval/source_at |
| Протокол | core risk/summary/status | core reader/foreign | core confirm idempotent | meetings empty_transcript | core transcript_edited_during_draft, ACL recheck; внешний источник не нужен | Частично: version/recheck есть, полного отдельного ageing сценария нет |
| CRM | CRM create/status | CRM employee/foreign_token | CRM replay/concurrent | CRM missing_mapping/source_empty | CRM down/timeout durable | CRM stale fault/changed state before confirm |
| Календарь | calendar slots/preview/confirm | calendar roles/ACL/revocation | calendar double_confirm/races | calendar no-free-interval/participant checks | Частично: mock provider есть, отдельного transport outage нет | calendar stale_meeting/slot taken; возраст витрин смен ещё не реализован |
| Обзор | KPI known formulas | KPI ACL-before-count/sum | Повтор GET, resolver recheck | KPI empty/missing/hidden + zero denom | domain source mutation, missing table; CRM fault warning | KPI snapshot_freshness + conservative source_at |

Устаревшая витрина, изменившийся preview и отозванная цитата проверяют разные
свойства. Эта карта не заявляет полное покрытие ещё не реализованных P1-маршрутов.

## Команды воспроизведения

```bash
python -m pip install -r requirements-track3-v2-test.txt
python scripts/track3/check.py -q tests --ignore=tests/ui_track3
node --test tests/*.cjs static/mts-shell/tests/*.mjs
python scripts/track3/v2_http_smoke.py --output /absolute/new-http.json
python scripts/track3/v2_http_smoke.py --unavailable --output /absolute/new-unavailable.json
python scripts/track3/clean_install.py --profile runtime --output /absolute/new-runtime-install.json
python scripts/track3/clean_install.py --profile base --output /absolute/new-base-install.json
```

Полная установка и smoke выполняются с синтетическими временными БД. Рабочая
`data/` не очищается. Локальный Chromium не перезапускался при прежнем запрете
Unix socket; браузер проверяет CI. Хост отдельно запускает LIVE_CHECKS.
Живые Ollama/ASR/TTS/диаризация, настоящая почта/CRM, микрофон и независимый
человеческий install не выполнялись агентом.

## E4: календарный обмен (12.11.2026)

- Полный pytest:1389 passed/28 skipped/0 failed,97,76s (`reports/v2-calendar-python.log`).
  Первый запуск выбрал неполное окружение без PyAV/SciPy:1387 passed/28 skipped/2 failed;
  исходный лог `v2-calendar-python-incomplete-env.log` сохранён. Повтор в v2 CPU
  окружении не менял существующие тесты/порог успеха. Новых календарных случаев15.
- Node66/0, syntax/diff passed. `v2-calendar-http.json`:7 уровней, ICS/EML,
  import preview/confirm, subscription/restart/revoke, provider503;3,94s.
- Frozen evaluator повторён без изменения gold: pipeline_passed30/30 задач,
 36/36 QA,17/17 claims,0 rights/false_actions. Это scripted double, не live качество.
- `v2-calendar-ui-local.json`: браузер NOT RUN, launch заблокирован socket policy.
  Новый UI путь cancel/confirm import, subscription/revoke,360/768/1440 включён
  в v2_ui_check.py и должен пройти на опубликованном CI.
- Финальные E14 чистые установки на локальном a11f836:base23,31s/runtime19,964s;
  отчёты `v2-e14-base-final.json`, `v2-e14-runtime-final.json`. Кэш неконтролируемый,
  модели не скачивались. API-публикация имеет идентичное дерево7c98d1c; CI43161157327
  уже подтвердил base/runtime Linux и text/browser. Windows ещё queued.
- Миграция12 работает на пустой и заполненной v8; повтор seed сохраняет количества.
  Расширено ожидание списка миграций в старом тесте: теперь9..LATEST вместо9,10,11;
  ни один старый тест не удалён. Подписки хранят hash токена, права и срок
  перепроверяются; устаревший outbox больше не выдаёт название после отзыва ACL.

Границы: [CALENDAR](CALENDAR.md). Реального SMTP/Outlook/Google/Битрикс24 нет.

## E4.2: график и Windows startup

- Full: 1405 passed, 28 skipped, 0 failed, 100,84 s; `v2-smart-calendar-python.log`.
  Затем добавлен regression canonical marker path: targeted 45 passed, 8,03 s
  (`v2-smart-calendar-target.log`); новый CI проверит полный состав. Node: 66/0.
  OpenAPI сохраняет 67 путей и расширяет поля slots/preview.
- `v2-smart-calendar-http.json`: настоящий сервер, 7 уровней, 3 smart-слота,
  preview/cancel, ICS/EML/подписка/restart/revoke/provider503. Без моделей.
- До smart-изменений CI 43162911735: Linux full/Node/browser35/новый calendar UI,
  base/runtime install — SUCCESS; Windows release — SUCCESS. Windows clean install —
  FAILED: pip/seed twice прошли, сервер завершился, 52,19 s
  (`v2-calendar-windows-install-failed.json`). Этот fail не переписан на PASS.
  Причина падения в старом smoke терялась в DEVNULL.
- `start.configure` канонизирует абсолютный путь (проверена регрессия relative path);
  Windows 8.3 остаётся гипотезой до CI. Smoke сохраняет tail stderr, installer
  сохраняет HTTP JSON даже при сбое. Исправленный Windows требует нового прогона.

Шесть веток smart: нормальный слот; роль/отказ в аудите; replay/cancel;
нет смен/слотов; source down/corrupt; устаревший график/новые предупреждения.

## Windows: уточнённая причина после исправления startup

CI43164400635: Windows сервер запустился, но smoke упал на503 model_timeout
вместо ожидавшегося model_unavailable. RawJSON: v2-windows-provider-diagnostic.json.
Новая проверка допускает только эти два503 provider-кода и непустое объяснение,
записывает фактический код. Семь тестов проверяют оба допустимых отказа и
отклоняют успешные/пустые/посторонние результаты. Живой инференс отсутствует.

Чистый runtime b294178 локально passed22,898s: v2-calendar-candidate-runtime.json;
кэш неконтролируемый. Финальный Windows результат требует нового CI.

## E6.3: FTS5/BM25

- `v2-fts-python.log`:1426 passed/28 skipped/0 failed,108,70s. Затем добавлен
  role-denial/audit case; targeted52 passed11,29s (`v2-fts-target.log`).
- `v2-fts-node.log`:66 passed. HTTP7 ролей/поиск/QA/provider failures/CRM/календарь/
  restart passed3,99s (`v2-fts-http.json`). Новая browser search ветка в v2_ui_check.
- `v2-fts-double.json`: frozen pipeline passed30 задач/36QA,17/17claims,0rights/
  false_actions. Gold не изменён. Live качество после смены ранжирования неизвестно.
- Приватные документы исключаются SQL до TEMP-индекса; добавление15 закрытых
  документов не меняет порядок доступных результатов. Проверены немедленный отзыв
  ACL, обновление/удаление фрагмента, контекст встречи, ё/е/окончания, BM25,
  отсутствие данных, FTS/SQL операторы как текст, безопасный сбой/аудит/повтор.
- Secret отсутствует в snippets и model index. Открытие файла владельцем сохранено.
  Дата загрузки source_at возвращается поиском. Версии/valid_until не закрываются
  этими тестами и остаются E6.2/E6.4.

## E6.2/E6.4: редакции, актуальность и выдержки (12.11.2026)

- 26 новых случаев в `test_document_versions.py`: нет записи до confirm, cancel
  удаляет временный BLOB, concurrent/replay создают одну редакцию, stale ACL/metadata/
  content/fragments/file отвергаются, не возникает ветка из двух preview.
- Owner-only запись, server ACL на каждой редакции, admin/auditor deny с аудитом,
  secret исключён из summary/diff/model. Скрытый потомок или промежуточная версия
  не влияют на выдачу и не раскрываются ссылкой. Цитаты разрешаются в исходный F-id.
- SQL выбирает актуальную доступную редакцию до FTS; явная история, сохранённые
  ответы/отзыв прав, expiry warnings, подготовка встречи и добавление новой редакции
  во время генерации проверены. Привязки встреч не меняются автоматически.
- Шесть веток: обычный confirm/summary/diff; foreign/admin denial; replay/concurrent;
  пустой/неподходящий источник; отсутствующий/изменённый BLOB409; expired/superseded
  и источник, заменённый в процессе запроса. Это локальные источники, не внешний API.
- Full1453/28/0 и Node66/0. Миграция13 на пустой/заполненной БД и повторный seed
  входят в полный набор; старые тесты не удалены. Прежняя полная база CI1427: +26.
- `v2_http_smoke.py` расширен версиями/cancel/confirm/replay/summary/diff/restart.
  Новый сценарий UI добавлен в `v2_ui_check.py`; локально Chromium не запускался
  повторно после установленного запрета Unix socket. Нужен CI нового head.
- Frozen double повторён:30/30 задач,36/36 QA,17/17 claims,0 прав/ложных действий.
  Gold не изменён, live модели не запускались. Новых зависимостей нет.
- Границы: DOCUMENTS.md. Смысловая сводка/противоречия/обязательства и фоновая
  очистка временных файлов остаются. Формат ошибок и дата Source сохранены.


## E6.2 / E6.4 / E6.5 · версии документов

- Полный CPU: **1448 passed, 28 skipped, 0 failed**, 163,94 s. Новые21 проверки
  покрывают версии/отмену/конкуренцию/ACL/актуальность/миграцию v12→13/метаданные.
  Ни один старый тест не удалён. Raw: reports/v2-documents-python-final.log.
- Node: **66 passed**, синтаксис новых/изменённых JS и compileall/diff passed.
- Настоящий HTTP:7 уровней, immutable версии/отмена/replay/summary/diff/restart
  passed. Режим без модели также passed: prepare/protocol/QA дают503
  model_unavailable; версии/документы работают. Raw: v2-documents-*http.json.
- Frozen photoprint-v2 pipeline:30/30 задач,36/36QA,17/17 claims с источником,
  0 нарушений прав/ложных действий. Gold не менялся. Это double, не live-качество.
- Локальный browser NOT RUN: Chromium упал до открытия страницы с socket()
  Operation not permitted. Raw: reports/v2-documents-browser.json. Новый путь
  upload→summary→preview/cancel→confirm→history/diff включён в v2_ui_check.py/CI.
- Новых библиотек/весов нет. Semantic-summary и P2-противоречия/обязательства
  не заявлены: кнопка «Кратко» возвращает явно помеченные дословные выдержки.
- Предыдущий574ab18/CI43166951277 завершился SUCCESS целиком, включая Windows.
  Новый срез требует отдельного CI; прежний успех на него не переносится.

## Совмещение с опубликованным45a3f12

Merge сохраняет обе поставки и все тесты:1474 passed/28 skipped/0 failed,
216,56s; Node66/0; целевые47/0. Дополнительная проверка Source.source_at=дата
загрузки, а не authored_at:1 passed. HTTP/restart/provider503/версии passed6,22s.
Файлы `v2-document-integration-*` относятся к совмещённому рабочему дереву
(до merge commit, JSON честно показывает dirty и прежний HEAD7e18d23).

Сохранён опубликованный контракт исторического ответа QA:200 с прежними цитатами
и предупреждением. При новой генерации смена источника по-прежнему409. Из нашей
новой тестовой поставки изменены ожидания двух чтений и owner-only404; защиты
прав/цитат/актуальности не отключены. Исходные тесты и21 тест удалённой поставки
не удалены. Мульти-file/metadata/filters сохранены, partial и File после cancel
добавлены в UI; CI должен проверить2 файла, повторpreview и мобильные ширины.

До merge чистый7e18d23: base40,693s/runtime27,094s, оба passed, первичные JSON
`v2-document-versions-{base,runtime}-install.json`. Запуски параллельны, кэш
неконтролируемый, без моделей. Совмещённый commit требует отдельной установки.


## E9.3 · дневной брифинг / импортированные документы

- ПолныйCPU: **1468 passed,28 skipped,0 failed**,207,05s; Node66/0.
  Raw reports/v2-briefing-python.log и v2-briefing-node.log. Целевой84/0
  выполнен до двух дополнительных проверок calendar-attendee/list-bound, которые
  вошли в полный прогон. Новые20 тестов суммарно после E6, старые не удалялись.
- Настоящий HTTP с моделью-дублёром и без модели:7 ролей, брифинг/голосовой
  маршрут/источник встречи/отказы/restart passed. Новые записи во внешние
  системы не добавлены. 503model_* остаются честными для генерации.
- Новая версия импортированного документа больше не копирует UNIQUEsource_ref:
  внешний ID остаётся у оригинала, цепочка supersedes_id сохраняет происхождение.
  Регрессионный тест на этот случай passed.
- Чистая runtime-установка E6-кандидата165c561 (дерево идентично45a3f12) прошла
  за51,505s, кэш неконтролируемый, без моделей; raw v2-documents-clean-runtime.json.
  Это результат E6, не отдельное измерение нового E9-кандидата.
- CI43184793897 на45a3f12: Linux CPU/JS/HTTP/eval/browser и обе clean-install
  прошли. Windows оставался queued. Новый брифинг требует своегоCI.
- Browser-маршрут кнопка→дата→ответ включён в v2_ui_check.py. Локально повторно
  не запускался после неизменившейся socket policy. Живые ASR/TTS/микрофон NOT RUN.

## Финальное сведение E6 и опубликованного E9

1494 passed/28 skipped/0 failed,209,53s; Node66/0. HTTP7 ролей/версии/брифинг/
voice text/restart/provider503 passed6,34s. Первичные v2-document-briefing-*.
Полный pytest запускался во время исправления синтаксиса HTTP helper; закончил
без падений. Отдельный HTTP затем запускался только после ast.parse и прошёл.
Брифинг/voice работают без модели; ASR/TTS/LLM не запускались. Старые raw-отчёты
сохранены и не объявляются проверкой нового дерева.

## Чистая установка итогового E6+E9

Из нового локального клонаe58a904 (tree da3191d, идентичен GitHub e496e4e):
Linux runtime34,330s/base37,937s, оба passed. Venv/pip-check/seed twice/HTTP
семи ролей/versions/briefing/restart/provider503/inventory прошли. Запуски
параллельны; кэш неконтролируемый, модели не скачивались. Первичные JSON:
`v2-document-briefing-runtime-install.json`, `v2-document-briefing-base-install.json`.
Это не независимая установка человеком и не результат Windows нового head.

## Проверка исправленной установки E7/E9

HEAD543467b, новые изолированные checkout/venv: runtime27.884s, base33.597s,
оба passed: зависимости/seed дважды/HTTP семи ролей/restart/model503/audio/
calls/actions/inventory. Кэш неконтролируемый, запускали параллельно, модели
не скачивали. Первоначальный base с FastAPI0.162.5/Starlette1.10 упал на удалённом
add_event_handler; переведён на APIRouter lifespan. Ошибка и повтор хранятся
раздельно. Наличие этой проверки не заменяет независимую установку человеком.

## E5.2/E7 · параметры действий и предлагаемые моделью темы (12.11.2026)

Текущая база main17c3ff4 включена merge031e1eb: сохранены оформление,
читаемые KPI, разговорные ответы/приветствия и мужской TTS, внесённые в main.
Новые функции: справочник имён с падежами и ё/е, сроки/дни недели/числа словами,
редактируемые поля поручения, параметры подбора календаря. Неоднозначность
показывается явно. Confirm проекта встречи не назначает время/приглашения.
Роль/отдел/делегирование и имена участников повторно проверяются на confirm.

Темы звонков по MEETINGS_CALL_TOPIC_MODEL=1 выбираются из17кодов и разрешённых
ID реплик. Цитаты берутся из БД, свободные утверждения не принимаются.
ACL/роль/secret и изменение текста проверяются до/после модели. Аудиоконвейер
перепроверяет доступ перед декодированием, загрузкой backend, каждым ASR-окном
и сохранением. Secret не обрабатывается моделью даже для владельца.

Целевые проверки: intent/voice89→94 passed на промежуточных срезах;
финальные intent/topics/media/basis26 passed24.24s. Node66 passed.
HTTPdouble5.662s и HTTPunavailable6.073s:7ролей, restart, voice-поля/проект
без приглашений, audio retained503, calls и metric action passed.
Frozen v2double30/30задач,17/17claims,0rights/falseactions.
Новый локальный UI запуск снова остановлен средой Chromium(socket EPERM),
это NOT RUN; assertions не удалялись. Browser должен пройти в новом PR CI.

live_voice_check.py/live_read_tools.py подготовлены, проверен только --help.
Модели, микрофон и реальные аккаунты агент не запускал. API111путей.
Полный pytest/чистая установка и новый PR фиксируются следующим результатом.

## Проверенный checkpoint042c036 (E5.2/E7)

Полный небраузерный pytest:1614passed/28skipped/0failed,279.20s; Node66/66.
Linux чистые установки из042c036: runtime33.259s, requirements.txt38.675s,
обе passed (clone/venv/install/pip check/seed twice/HTTP7roles/restart/503/inventory).
Это агентские проверки с неконтролируемым pip-cache, не независимая установка
человеком. Модели не скачивались/не запускались. Полные первичные результаты:
reports/v2-p1-fields-{python.log,node.log,http.json,unavailable.json,
runtime-install.json,base-install.json,ui.json}. UI report failed по причине
Chromium socket EPERM до запуска сценариев; browser NOT RUN локально.
Проверка конвейера evaluator:30/30tasks,17/17citedclaims,0rights/falseactions.
Новые P1 исходники/Node/HTTP соответствуют полному прогону. Protected-path и
finite secret-pattern scan passed, start-gateway/.env/data/models не изменены.

## E4.4–4.5/P2 · локальные серии и Google adapter

Миграция20: спецификация конечной серии и настройка reminder_minutes.
Серии2..30daily/weekdays/weekly, IANA-зона, smartshift/break/buffer-check,
previewвсехдат/confirm/replay/cancel/stale/busy. Каждая встреча и протокол
отдельные; открытые задачи серии — в личном контексте next-agenda.
UI в существующих controls, без изменения оформления. Напоминания0..1440мин
через preview/confirm;0выключает. Google переиспользует integrations transport
и networkgates; частная reservationорганизатора, local ICSдлягостей;
mapping proof и durableuncertain безповтора. Реальных аккаунтов нет.
Целевые24passed20.89s, расширенная регрессия80passed25.65s;
HTTP7roles/restart/series6.534s passed; Node66passed. Полный набор запускается
отдельно. Локальный browser остаётся NOTRUN(socket EPERM); CI blocked publication.
API114пути.

Публикация локального3de1126 заблокирована automatic approvalreview: create_tree
с точнымtree0a9909d0ef413daed40cc5f76b816825a80cad86 создан, create_commit
отклонён с причиной недостаточного явного разрешения на124файла иназначение.
Не повторять другимипутями и не обходить отказ. Remotebranch остаётся7a7d383,
новогоPR/CIнет. Полная проверка локального кода продолжается; после подготовки
конкретного набора нужно прямое разрешение пользователя на публикацию.

## E4 законченный локальный срез d0f4895 и следующий пункт E6.4

Календари: full1619passed/28skipped/0failed282.78s; Node66passed;
HTTPseries/restart6.534s passed; cleanruntime26.482s passed.
Первичные reports/v2-planning-*. После этого новый main5272c1c
(голосовые списки,1.25x,автоматический wake) включён mergeaf29c96.
Оба набора поведения сохранены;98voice/chat/intent tests passed14.05s.
Дополнительно голосовые списки теперь исключают secret и учитывают только
доступные актуальные редакции, а не факт наличия чужой новой версии.

Следующий пункт: document-insights, source-bound promises/contradictions;
37targetpassed17.25s. Детерминированные ключи «сущность+атрибут»/разные даты
с двумя цитатами, карта обещаний из документов/встреч, ручной actiondraft с
Basisdocument/utterance и повторной ACL/snapshot/version проверкой.
Знания/подготовка: функциональные controls без изменения дизайна. API115путей.
Ограничения грамматики/полноты/исполнения изложены в DOCUMENTS.md.

Новое прямое указание Лёши12.11.2026: «начиная со следующего пункта лей все
в мейн но не забывай проводить автотесты». Оно разрешает публикацию следующего
проверенного пункта и накопленного необходимого кода в main репозитория
yougmilee2642-a11y/iug6767hhh; отдельное повторное разрешение не нужно.
Предыдущий automatic approvalblock разрешён новым прямым указанием.
Публикация через branch/PR с проверкой CI, затем обычный merge; безforce/rebase.
Текущая работа готовится к полному набору/HTTP/чистой установке и публикации.
Liveмодели/аккаунты не запускались, ими автоматические тесты не заменяются.

## E15.1/E15.6 и актуальная браузерная проверка

Срез241a70c:1646Python passed/28skipped/0failed287.45s; это полный CPU
с room-hints/corridor, до последнего UI-fixture regression. Целевой новый
UI-transport+room5passed4.51s; Node66passed. Ранее E6.4source230fdfe:
1642passed/28skipped286.51s; cleanruntime28.092/base29.534passed;
HTTP5.726s passed. Первичные reports/v2-document-insights-* иv2-meeting-hints-*.

PR13 опубликован. Первый CI43213981781: Linux/base/runtime и Windows/release/
installpassed. Browser35scenarios failed2/errors39: icon-arrow изменял
accessible name; multipart wake WAV ошибочно читался JSON fixture; старые
селекторы card не соответствовали current main rows. Отдельно выявлен mobile
overflow. Исправлены явный aria-label, binary-awarefixture, семантическое
время/пояс, актуальные selectors без удаления assertions, min-width grid shrink.
Реальные UI сценарии должны пройти новыйCI. Фикс private speech: wake-mode
не является разрешением озвучить личные ответы; нужен явный solo-roomфлажок.
Модель/аккаунты/живой микрофон не запускались. Браузер локально socketEPERM.


## Расширенные отчёты — локальная проверка 12.11.2026

На коммите 0207c3c: полный Python — **1653 passed / 28 skipped / 0 failed**
за 308.95с (`reports/v2-radar-full.log`). Целевые отчёты/operations/briefing —
34 passed. HTTP — passed, восемь ролей, источники insight/чужой404, личный
дайджест/повтор confirm/перезапуск (`reports/v2-radar-http.json`, записан dirty:
добавлены явные метки полей и sup_head в HTTP-клиенты).
Настоящие модели и внешние сервисы не запускались. Браузерный результат этой
поставки ещё ожидается в CI; число Python-тестов не заменяет браузер.
