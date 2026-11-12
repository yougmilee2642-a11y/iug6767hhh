# Проверки Фокус v2 — 12.11.2026

Это промежуточный отчёт P0/E14; весь объём ТЗ не завершён. Результат привязан
к commit/dirty в первичных JSON. Документационные коммиты не являются новым
прогоном модели. [Самоаудит](SELF_AUDIT.md) содержит риски каждого требования.

## Измеренные проверки

| Проверка | Результат и границы |
|---|---|
| Полный небраузерный Python | 1374 passed, 28 skipped, 0 failed, 92,08 s; `reports/v2-e14-python.log`. Шесть deprecation warnings PyMuPDF; skips не считаются passed. |
| Node | 66 passed, 0 failed; `reports/v2-e14-node.log` |
| Настоящий HTTP, 7 уровней | `reports/v2-e14-http.json`: KPI, ACL, cancel/confirm, CRM/idempotence/restart; явный QA double, не качество модели |
| Недоступная модель через настоящий HTTP | `reports/v2-e14-unavailable-http.json`: реальные provider/prepare/protocol/QA → 503 model_unavailable, расшифровка не изменена, 7 уровней/restart |
| Предыдущий чистый CI | [43157518742](https://github.com/yougmilee2642-a11y/iug6767hhh/actions/runs/43157518742) на 3dbc30c: Linux/Windows, Python/Node/35 UI, оба browser→HTTP и evaluator passed. Не переносится на новый head. |
| E13 на дублёре | `reports/v2-evaluator-double.json`: pipeline_passed, 30 задач/36 вопросов; quality NOT MEASURED, не live recall |
| Первоначальный чистый base | `reports/v2-e14-initial-install.json`: 65,88 s всего; base install 25,28 s прошёл, seed упал без PDF reader; после test-профиля seed/restart прошли |
| Изолированный runtime | `reports/v2-e14-initial-runtime.json`: 12,68 s, повтор seed/HTTP passed; pytest/Playwright/torch/scipy/av/soundfile отсутствуют. Кэш pip не контролировался. Профиль был незакоммичен, код клона 3dbc30c. |
| Исправленная установка base/runtime | Новый `clean_install.py` запускается после commit; отчёты и Windows CI должны быть проверены отдельно. Нельзя считать passed по первоначальному замеру. |
| OpenAPI | `export_api.py` из настоящего app: 67 путей; временная БД, без моделей/рабочей data/ |
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
| ОТ-01 | clean_install base/runtime Linux/Windows | Исправленный профиль ожидает новый прогон; первоначальная ошибка сохранена |
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
