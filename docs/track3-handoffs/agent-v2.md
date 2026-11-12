# Фокус v2 — журнал исполнения

Исполнитель новых изменений: Codex. Источник задачи: docs/track3-team/V2_SPEC.md
(исходное вложение пользователя, не отчёт о готовности). Ветка track3/v2-fotoprint.
Пользователь отменил прежние зоны владения; запрет дизайна, секретов, реальных
интеграций/данных, запуска моделей и изменения start-gateway.ps1 остаётся.

## E0 — объединение и исходная проверка

- База origin/main e3d37e331daefe70d0f35bd63d7795206ae574a5.
- Integration dfe999352726c7fdfd8795bc6f65b855c52a5530 включена обычным merge.
- PR6 05fb4f9 включён в integration обычным merge: сохранён scorer3 с уже внесённым
  UTF-8/Windows-safe symlinks, добавлен root LF policy. Данные/gold v1 не менялись.
- Минимальный layout-fix: account controls flex-wrap/max-width на мобильном;
  комментарий TODO(design), без изменения цветов/шрифтов/оформления.
- Полный исходный pytest был выполнен:978 passed/28 skipped/2 dependency failures/
  35 browser errors. Причины: scipy/soundfile отсутствовали; Chromium socket()
  запрещён sandbox (Operation not permitted), не продуктовая ошибка браузера.
- После установки CPU wheels scipy/soundfile/av (без моделей), весь небраузерный
  pytest:980 passed/28 skipped,58.64s. Браузерные35 локально NOT RUN; CI проверяет
  точную unittest-команду и настоящий UI→HTTP, без снятия assertions.
- Node46 passed; static/mts-shell/tests20 passed. Регрессия —66 Node tests.
- Команды: python scripts/track3/check.py -q tests --ignore=tests/ui_track3;
  node --test tests/*.cjs static/mts-shell/tests/*.mjs.
- Окружение/лицензии CPU wheels — requirements-track3-v2-test.txt,
  reports/v2-e0-dependencies.json; логи reports/v2-e0-*.log.

## Карта кода

- meetings/store.py: SQLite baseline, connection/transactions, ACL, serializers.
- meetings/migrations:8 выпущенных append-only шагов; новая схема — только новым шагом.
- meetings/auth.py: session cookie, user resolution, capabilities; access.py будет
  единой точкой v2 policy, при сохранении legacy manager/reader.
- meetings/api.py: install/app middleware и CRUD документов/встреч/стенограмм/
  протокола/задач; app.py менять для новых маршрутов не требуется.
- meetings/knowledge: retrieval/context/excerpt verification/QA persistence;
  meetings/management: KPI snapshots/formulas/source resolver; voice.py — read routing.
- meetings/confirmations.py + calendar: preview/confirm/cancel/idempotence/outbox.
- static/meetings.js + meetings/{track3,protocol,voice}.js: текущий UI; расширение
  только функциональными формами/таблицами в существующих классах.
- Новые domain/access/privacy/connectors/media/assistant сервисы подключаются из
  meetings.api.install; внешние транспорты только mocks, модели только doubles.

## План и состояние

| Эпик | Состояние |
|---|---|
| E0 | CPU/Node и CI Linux/Windows/browser passed, run 43074018765, head f86a433 |
| E1 | Реализован; синтетический seed/генератор/миграция, детали ниже |
| E2 | Policy/API/базовые формы реализованы; новая UI-проверка ожидает CI; финальный аудит впереди |
| E8.1–4/E9.1/E11.1–4 | P0 после E1/E2 |
| E13/E14 | P0 evaluator v2/double + self-audit/live scripts/docs |
| E3/E4/E6/E10 | P1 connectors/calendar/documents/assistant |
| E5/E7/E9.2–3/E11.5–6 | P1 voice/audio/calls/briefing/retention/web safety |
| E12/E15/прочие P2 | После зелёных P0/P1 |

Модельные результаты хоста v1 (18/18 задач,16/16 QA,11.11.2026) — только reported
из handoff Claude; первичные JSON не получены. Агент их не повторяет и не выдаёт
за измерение v2. Live v2 на Ollama/ASR/TTS/диаризации будет выполнять хост.

## E1/E2 · домен, seed, доступ и формы

- Миграция 9: оргструктура, атрибуты пользователей/документов/встреч/задач,
  версионность документов, CRM/ERP/Mary/HR/финансовые витрины, делегирование.
  Пустая БД и заполненная v8 проверены; исходные BLOB/ACL сохранены.
- Стандартный CLI seed теперь Фотопринт v2; `--legacy`/импортируемая функция
  `seed()` сохраняют Орбиту. Только явный абсолютный путь вне data/; reset
  требует тестовый маркер. Источник импорта и хеш всего набора фиксируются.
- 18 пользователей,12 отделов,54 документа/7 форматов,5 контрольных стенограмм,
  отдельная история5 поручений,600 заказов,250 клиентов,400 обращений,
  50 сделок,30 планов/прогнозов,1040 смен. Цены вымышленные.
- Генератор воспроизводит одинаковые байты. V1/frozen SHA не менялся.
  В2 gold30 задач зафиксирован до модели; качество модели v2 NOT RUN.
- Стандартные читатели CSV/XLSX/PPTX/MD/HTML/EML без новых зависимостей:
  заголовки/строки/листы/слайды в локаторах; формулы не исполняются,
  DTD/ENTITY/опасные ZIP-пути отклоняются. Строки не обрезаются посреди условия.
- `access.decide` и SQL-предикат: ACL/classification + capability;
  SQL-фильтрация до ранжирования/агрегации. Admin/auditor не читают содержимое;
  secret исключён из QA/prepare/protocol-модели даже для директора.
- Employee меняет только статус своей задачи; lead не пишет в чужой отдел.
  Делегирование ограничено отделом/временем, без автоматического доступа к
  confidential/secret; права перепроверяются на confirm, истечение проверено.
- Пользователи: admin preview/confirm/cancel, немедленная деактивация session,
  запрет изменения собственных админских полномочий. Аудитор видит весь журнал,
  head — журнал отдела, legacy my_objects/invalid_scope сохранены.
- UI: базовые таблицы пользователей/аудита, форма делегирования, бейдж роли/отдела,
  селект конфиденциальности загрузки, демо-роли только при MEETINGS_DEMO=1.
  Только существующие классы; дополнительный CSS ограничен layout TODO(design).
- Проверки: полный небраузерный прогон1284 passed/28 skipped,97.26s до пяти
  добавленных тестов; затем расширенные новые тесты309 passed,9.33s.
  Node66 passed; syntax passed. Diff-check выявил пробелы PDF xref;
  PDF явно отмечен binary в .gitattributes, формат файла сохранён. EML
  генерируется с LF для совпадения байтов checkout/генератора на Windows/Linux. Перед финальным выпуском — снова
  полный набор на конечном head, а не перенос этих чисел на будущий код.
- HTTP существующего app.py:6 ролей, KPI97.6%/1.8%/3 overdue,
  cancel/confirm/idempotence/restart passed,4.95s. Report честно содержит
  working_tree_dirty=true, поскольку измерен незакоммиченный кандидат от f86a433.
- Локальный Chromium NOT RUN: TargetClosedError/socket() Operation not permitted.
  Workflow дополнен v2 HTTP и реальным UI:6 ролей×3 viewport, admin preview/cancel.
  До результата нового CI не называть браузер v2 зелёным.
- Новый runbook: docs/track3-release/V2_QUICKSTART.md. Общие P0 E8/E9/E11,
  connectors/mock CRM, E13/E14 и полный self-audit ещё не завершены.
  main не изменён, PR12 остаётся draft.

## Проверка опубликованного E1/E2 и E11.1–4

- E1/E2 опубликованы: head54bc4cc08e280e2ce5d448d8d6da9e3320f40b15, PR12 draft.
  Локальные исходные коммиты42d923d/9deca6b/7f57811 сохранены; API-коммиты
  содержат Source-Local-Commit. Проверено побайтовое совпадение деревьев.
- CI43144578710: Windows passed; Linux1289 passed/28 skipped/80.88s,
  Node66 passed, legacy35 browser passed, оба HTTP/restart passed.
  Новый v2-browser failed: director768px → document775px. Никакого общего
  success этому запуску не присвоено. Account layout исправлен переносом на
  всех ширинах; новый CI обязателен, assertion не ослаблен.
- Фильтр ПДн вынесен перед provider.json во всех extraction/QA стадиях,
  включая doubles. Изменение Unicode сначала затронуло многоточие системного
  промпта; исправлено нормализацией только совместимых одиночных символов,
  исходные системные инструкции и существующие тесты сохранены.
- Добавлены intent refusals QA/voice, корпус15 инъекций + filename/title,
  независимая проверка ID/цитат, отсутствие записи задач/календаря/outbox.
  Старый путь делимитированных недоверенных данных сохраняется, безопасные факты
  и инструкции различаются валидатором; тесты не переписаны под новый результат.
- Аудит дополнен logout, маскированным вопросом QA, фильтрами и безопасным CSV.
  Реальные модели и внешние интеграции не запускались. Границы шаблонного
  фильтра и незавершённой автоматизации хранения явно описаны:
  PRIVACY_GUARDS.md и DATA_POLICY.md. Остальные P0 E8/E9/E13/E14 ещё в работе.

- Финальный для блока privacy полный CPU прогон:1333 passed/28 skipped,
  92.61s; Node66 passed; compile/diff passed; v2 real HTTP/restart passed4.52s.
  Предыдущий прогон нашёл9 регрессий голосового audit-контракта: восстановлены
  hash-only для формулировки голоса и result=refused для прежнего маршрута action;
  новые запрещённые намерения продолжают иметь result=denied. Старые тесты
  не изменены и проходят. Логи: reports/v2-privacy-*.

## E8 · подготовка и контроль поручений

- Task metadata:5 статусов,4 приоритета, устойчивый assignee_user_id,
  linked_entities(order/customer/document), readonly external_ref. Preview
  показывает изменения; confirm повторно проверяет роли/связи/версию.
  Сотрудник меняет только статус своих задач, lead не назначает чужой отдел.
- Фильтры/счётчики без владельца/даты; blocked остаётся открытой задачей,
  cancelled исключается из открытых/просроченных и следующей повестки.
- Подготовка дополнена доступными задачами отдела/общего заказа независимо
  от followup_of, открытыми вопросами прежних протоколов с проверенной репликой,
  KPI отдела с формулой/числителем/знаменателем/as_of. SQL-права до отбора.
  Источник задачи имеет дату подтверждения, не плановую будущую дату встречи.
- Подсказка владельца по теме помечена assumption, не записывается.
  UI даёт локальный проект повестки с источниками; он явно не сохраняется
  на сервере и очищается при выходе. Добавлены обратные переходы протокол↔задача.
- Предыдущий CI43147049303: CPU1333/28,Node66,Windows и real HTTP passed;
  legacy UI34/35 (возврат фокуса после Escape), v2 UI failed на неуточнённом
  assert после cancel. Исправлен синхронный возврат фокуса на cancel;
  v2-script ждёт завершения async cancel и даёт traceback. Assertions сохранены.
- Новый v2 browser-script дополнен read-only приоритетом сотрудника,
  preview/cancel блокировки и фильтром журнала аудитора. Локальный браузер
  по-прежнему недоступен из-за socket policy; нужен зелёный CI нового head.
- Целевые тесты E8:7 passed до добавления отдельного lead cross-department
  rollback-теста; legacy/core/access контроль350 passed. Финальные результаты
  полного прогона будут записаны ниже. E9/E13/E14 и mock CRM P0 ещё впереди.

- Завершённый прогон E8:1341 passed/28 skipped,112.84s; Node66 passed;
  compileall/diff/syntax passed; actual product HTTP/restart passed5.46s.
  Это CPU/double evidence, не live-model измерение. Логи:
  reports/v2-tasks-preparation-*. Локальный Chromium повторно не запускался:
  прежний sandbox socket запрет не изменился; проверяет CI опубликованного head.

## E9 · витрины и решения на контроле

- В обзоре: SLA368/400=92%,Mary272/400=68%,очередь модерации18,
  невостребованные31,просроченные завершённые12 с причинами7/3/2,
  пик прогноза888/800=111%; первые4 доступных будущих периода с явными датами.
  Значения из синтетических источников, не измерение бизнеса/модели.
- Витрины фильтруются SQL-политикой до агрегации/периода/актуальности.
  Все Source открываются и повторно проверяют ACL; изменение исходных строк
  инвалидирует прежнее доказательство. T-prefixed task Source теперь разрешим.
  Нулевой знаменатель → null/warning; сумма больших конечных часов вычисляется
  через Decimal, без NaN/Infinity в JSON. Демо-пороги вынесены в конфиг.
- Добавлена миграция10 decision_controls и human preview/confirm/cancel
  с проверяемым decision-пунктом/репликой/версией/правами. Повтор не дублирует.
  Владелец/срок могут быть неизвестны. Отдельные open/overdue decision KPI;
  граница даты проверена по Europe/Minsk. UI — базовая форма в протоколе и список
  контроля в обзоре. Рассылок, платежей и кадровых действий нет.
- CI43149579323 на E8: CPU1341/28,Node66,Windows,оба HTTP и legacy35 browser
  passed. Новый v2 UI failed на точном доступном имени select «Приоритет»;
  поле получило явный aria-label, точный тест сохранён. Добавлен браузерный путь
  постановки вручную написанного решения на контроль (без модели).
- Для E9 полный CPU:1348 passed/28 skipped,79.85s; Node66 passed;
  actual HTTP/restart passed3.60s; compile/syntax/diff passed. Отдельно7 тестов
  витрин/решений passed; миграция с заполненной v8 сохраняет данные через9/10.
  Браузер нового head ожидает CI; реальное качество LLM NOT RUN.
- Следующие P0: mock CRM, evaluator/gold v2 и self-audit/runbook/live scripts.
  Остальные P1/P2 не объявлены завершёнными. main не изменён, PR12 draft.

## E3 · P0 mock CRM / outbox

- Head E9 `c11c4a761729dee040d381d65772d0624ff487d9` опубликован.
  CI43153766117 SUCCESS: Linux1348 passed/28 skipped,Node66,legacy35 browser,
  оба HTTP и v2 UI6 ролей×3 ширины; Windows release SUCCESS.
  CI проверял PR merge `afa5164eba8d943695b88d4dbacc4b5484115ef5`.
- Добавлен CRMConnector/SQLite MockCRM. Read-side ERP/клиенты/обращения
  фильтруется до чтения; клиент только псевдоним, поля source_id/as_of/fetched_at.
  Явные номера заказа/клиента распознаются, задача сохраняет доступные связи;
  карточка заказа показывает ERP-историю и доступные обращения.
- Миграция11: integration_outbox + mock_crm_objects. Экспорт задачи и
  прикрепление подтверждённых пунктов протокола только preview→confirm;
  отмена0 записей, повтор/гонка1 объект, изменённые права/цитата/версия/маппинг
  не проходят confirm. Head ограничен своим/делегированным отделом.
- timeout после preview сохраняет uncertain+503; down — failed+503.
  Повтор возвращает сохранённый сбой, не вызывает запись заново. Новый preview
  той же задачи также блокируется. Это однотранзакционный mock, не доказательство
  распределённого exactly-once и не проверка сети Битрикс24.
- UI: отправка/статус задачи, attach-preview протокола, ERP-карточка,
  admin «Интеграции» с реальным mock-check. Реальный портал, импорт сотрудников
  из отдельной системы, разрешение uncertain, внешнее обновление задач ещё не
  реализованы. Не выдавать список уже имеющихся маппингов за синхронизацию.
- Полный CPU1364 passed/28 skipped89.98s; Node66 passed; actual HTTP6 ролей,
  CRM cancel/confirm/replay и restart passed3.41s. Целевой CRM16 passed10.10s.
  Логи reports/v2-crm-*. После небольших уточнений контракта/метаданных повторно
  проверяется CRM; браузер нового блока будет проверен следующим CI.
- Модели/реальные интеграции NOT RUN. start-gateway.ps1 не менялся, main не
  переписывался. Следующие P0: frozen QA-gold/evaluator v2, self-audit/runbook/live
  scripts. Остальные P1/P2 по ТЗ остаются отдельной работой.
- Финальный targeted CRM:18 passed11.03s, в том числе запрет экспорта
  done/cancelled и неизвестного action. Полный1364 был до добавления этих двух
  параметризованных случаев; следующий CI проверит весь финальный набор.

## E13 · frozen v2 / оценщик

- CRM head `dd67886b4432a7d85beac3b5f1e884cc81380279`:CI43155600711 SUCCESS,
  Linux1366/28,Node66,legacy35 browser, оба HTTP и v2 UI (отправка mock CRM,
  статус, admin-check, роли/ширины); Windows SUCCESS. PR merge проверен как
  `097acbb3caf13b805713a7c6e445a9339e8f5c84`.
- **До** первого прогона v2 отдельный локальный коммит `df23bc5` зафиксировал
  gold:5 текстов/30 задач/36 контролей/64 хеша. Вопросы включают8 ACL-negative,
  4 no-data,4 injection,3 stale;3 stale читают детерминированный обзор, не LLM.
  Gold после ответов не менялся. Полные имена нормализуются только по точному
  уникальному имени участника frozen roster этой встречи, без fuzzy-сопоставления.
- Новый `evaluate.py --dataset photoprint-v2 --scripted-double`:scripted fixture
  → настоящий HTTP API → source resolution → независимый deterministic scorer.
  Первая попытка30/30,36/36; финальный наблюдаемый reports/v2-evaluator-double.json:
  pipeline_passed,30/30,precision1,ошибки владельца/срока/ложные0,claims17/17,
  rights/false_actions0. **Это проверка конвейера, качество LLM не измерено.**
  Report помечен dirty=true, gold_commit и evaluator_sha256 сохранены.
- Дублёр никогда не конструирует MeetingLLM и не читает endpoint. Live-ветка
  требует чистый checkout/явное окно GPU/реальные version+digest, иначе NOT RUN.
  JSON checkpoint, исходные ответы, параметры, задержки, hashes predictions/QA;
  независимый rescore не может обойти цитаты/подмену наблюдений/модельного судью.
- call_defect — контроль задач по готовому тексту звонка. ASR/звук/диаризация и
  полная аналитика E7 явно NOT RUN, не входят в эти успешные результаты.
- Полный CPU1373 passed/28 skipped94.24s;Node66;actualHTTP/restart3.94s.
  После добавления CLI/no-overwrite теста targeted evaluator8 passed6.47s;
  следующий CI должен включить его в полный набор. PowerShell parser/runtime
  здесь отсутствует: live_eval.ps1 не запускался. Написаны LIVE_CHECKS.md и
  host-only live_eval.ps1 (UTF-8 BOM для Windows PowerShell), добавлен CI double CLI.
- Office ZIP помечены binary в .gitattributes для защиты CRC от EOL-конверсии;
  сами байты frozen-набора не менялись. Локальный Chromium не перезапускался
  при неизменившемся ограничении sandbox. Старые host-v1 результаты18/18,16/16
  только атрибутированы integration-handoff11.11.2026, не переизмерены этим агентом.
- Следующий P0: E14/self-audit, чистая установка, API/OpenAPI/демо/риски.
  P1/P2 остаются по спецификации; main не менялся, PR12 остаётся draft.


## E14 · воспроизведение установки и промежуточный самоаудит

- Предыдущий head3dbc30c/CI43157518742 прошёл Linux/Windows/браузер целиком.
- Новый чистый клон/venv: base requirements устанавливается, но seed падает
  без PDF reader. Первичное наблюдение сохранено, не переписано. В base
  добавлены numpy/pypdf/PyMuPDF существующих проверенных версий; старый
  requirements-track3.txt/lock не изменён. Новый runtime профиль не ставит
  pytest/Playwright/ASR CPU libraries; независимый lean venv прошёл за12.68s
  с неконтролируемым кэшем. Не холодный benchmark и не независимый человек.
- clean_install.py клонирует чистый commit/создаёт отдельную venv/seed twice,
  проверяет7 уровней, реальный HTTP/CRM/restart/503. Отчёт новый вне repo,
  модели не устанавливает и endpoint принудительно закрыт. CI matrix:
  Linux base/runtime + Windows runtime. Новый CI обязателен.
- v2_http_smoke теперь7 уровней включая lead; --unavailable не подменяет
  MeetingLLM, проверяет настоящий provider→503 prepare/protocol/QA на port1,
  сохранность реплик и restart. Продуктовые handlers не изменены.
- README/QUICKSTART отделяют runtime от regression profile; актуальны API,
  OpenAPI60 paths/exporter, requests.http, архитектура v11, DEMO/PITCH,
  SELF_AUDIT/TEST_REPORT. STATUS v1 архивирован, новый отражает v2.
  Не заявлены отсутствующие чат/брифинг/call analytics/ICS/with-drafts.
- Полный CPU1374 passed/28 skipped/0 failed92.08s; Node66 passed; оба HTTP
  passed; compile/diff passed. Raw evidence reports/v2-e14-* относится к
  рабочему кандидату; публикация/чистая установка ещё впереди.
- Secret history scan96 commits/106431 added lines: три повтора одного
  отрицательного URL fixture https://u:p@example.com; реальные ключи по
  format rules не обнаружены. Это ограниченный scan, не DLP/credential validation.
- Все live модели NOT RUN, frozen gold не менялся; P1/P2 не завершены,
  main не меняется. Автор новых изменений Codex; ложное авторство не добавлено.

## E14 publication / E4 · ICS и локальные приглашения

- Незавершённый a11f836 опубликован через API с идентичным tree как7c98d1c.
  Старый локальный commit сохранён отдельной веткой. Новый CI43161157327:
  Linux base/runtime и весь text/browser SUCCESS; Windows queued.
- Чистые install reports:base23,31s/runtime19,964s, кэш неконтролируемый,
  без моделей;7 ролей/seed twice/provider503/restart passed. Финальные raw JSON
  добавлены без замены первоначального failed evidence.
- Миграция12: отзывные signed busy-only ICS subscriptions (90 дней) и состояние
  личного импорта. Export только моих подтверждённых событий, текущий ACL;
  import только интервалы, preview/confirm/cancel/replay/concurrency/stale.
  Старые ручные busy/events не удаляются. Повторы не дублируют.
- MIME .eml download с ICS, synthetic .invalid addressees, доступ организатор/адресат.
  Проверяются обе текущие ACL; safe_outbox теперь также редактирует старые названия.
  Никаких SMTP/реальных сервисов; data/outbox/*.eml автоматом не создаются.
- UI — существующие элементы/стили, disclosure на Встречах, импорт/подписка/отзыв,
  загрузкиICS/EML. Нового CSS нет. OpenAPI67 путей, RFC5545 primary references
  в CALENDAR.md. Зависимости не добавлены.
- Новый targeted37 passed; full1389/28/0,97,76s; Node66/0; HTTP7 ролей/ICS/EML/
  подписка/restart/revoke/503 passed3,94s. Первый full с неверным venv имел2
  ModuleNotFoundError старых dual_asr CPU tests; лог сохранён. Полный повтор
  в track3-clean-venv зелёный без изменения тестов.
- Double evaluation повторён:30 задач/36QA/17claims,0 rights/false_actions;
  это только pipeline. Локальный Chromium socket forbidden, UI NOT RUN; новый
  путь в v2_ui_check и CI. LiveLLM/ASR/TTS/диаризация не запускались.
- Осталось E4: смены/буферы/необязательные участники, внешние провайдеры, серии,
  напоминания, автоматические файлыEML. Остальные P1/P2 по SELF_AUDIT не закрыты.
  start-gateway.ps1/main не менялись. PR12 остаётся draft.

## E4.2 · смены, free/busy и повторная проверка

- `availability.py`: явные смены/перерывы, зона каждого пользователя, буфер 10 минут,
  HR-отсутствия по табельному коду без причин/названий. Отдельная производная
  free-busy проекция не выдаёт строки HR. Без графика — предупреждённый офисный
  fallback; если смены не попали в период — слотов нет.
- Smart slots/preview и optional_participant_ids; организатор обязательный.
  Top-3: число optional-конфликтов, затем время. В UI флажок и отметка optional
  для выбранных людей. Legacy API без smart сохранён. Подбор/сбой источника в аудите.
- Confirm повторно проверяет график, пояс, active, busy и новые warnings. Downtime:
  503 без event/outbox; новый конфликт: 409/422; cancel 0/replay 1. Inactive/admin/
  auditor исключены из приглашения. Тесты покрывают роли, смены, таймзоны, optional,
  отсутствие, старые/повреждённые графики, нет данных и недоступный источник.
- Full: 1405 passed/28 skipped/0 failed, 100,84 s; Node: 66/0. Затем добавлен
  path-regression, targeted: 45/0, 8,03 s. Real HTTP: 7 уровней, 3 smart-слота,
  preview/cancel, ICS/EML/restart/provider503 passed. Gold/модели не менялись.
  Chromium после прежнего socket refusal не перезапускался.
- CI 43162911735 на 020c515: Linux целиком, browser/base/runtime passed;
  Windows release passed; Windows clean install failed за 52,19 s: install/seed
  прошли, server exited. Raw JSON сохранён. Стартовый путь теперь канонизируется
  перед проверкой marker (гипотеза tempfile Windows 8.3); отдельный relative-path
  regression passed. Исправление Windows ждёт нового CI. Smoke сохраняет stderr,
  installer сохраняет HTTP JSON и при ошибке.
- Main/start-gateway не менялись, PR12 draft. Внешние провайдеры/SMTP/автоматические
  EML/серии/напоминания остаются. Остальные P1/P2 — по SELF_AUDIT.

## Windows · повторный smoke и контракт provider failures

- На b294178/CI43164400635 Windows сервер уже запустился: runtime install и seed
  пройдены, HTTP дошёл до503 model_timeout. Предыдущая startup-проблема после
  canonical path больше не наблюдается. Первичный диагностический JSON сохранён
  в reports/v2-windows-provider-diagnostic.json; весь clean-install пока FAILED.
- Closed loopback на Windows может завершиться connect timeout, а на Linux —
  connection refused. Smoke теперь требует503 и принимает только два известных
  кода model_unavailable/model_timeout с непустым объяснением. Фактические коды
  сохраняются в observed_model_errors. Успех/пустой ответ/другая ошибка не проходят;
  отдельные позитивные и негативные тесты. Инференс не запускался.
- Новый локальный runtime install чистого b294178 passed22,898s, кэш неизвестен;
  старые ошибки не перезаписаны. Последний полный CI Python на b294178 прошёл;
  финальная Windows/браузерная приёмка нового исправления ещё впереди.
- Scan добавленных строк от3dbc30c доb294178:9484 строки,0 совпадений форматов
  private/GitHub/Slack/Bitrix/Telegram ключей; ограниченный scan, не DLP.
  Защищённые пути отсутствуют в новых изменениях.

## E6.3 · FTS5/BM25 и изоляция статистики

- Новый knowledge/index.py: SQL отбирает доступные документы до TEMP FTS5,
  поэтому BM25 corpus statistics тоже не содержат чужих документов. Индекс
  удаляется в finally. Для54 документов принят пересчёт на запрос; большая
  коллекция потребует оптимизации, performance улучшение не заявляется.
- Ручной поиск: русский lexeme/ё-е, все термины через безопасный MATCH, limit50,
  source_at, q до2000. Secret исключён; admin/auditor403 с аудитом. Файл владельцу
  по-прежнему доступен отдельно. UI скрывает контентный поиск этим двум ролям.
- QA сохраняет scope/числовые anchors/eligibility/цитаты/бюджет до top-k и повторную
  проверку источников; BM25 ранжирует только допустимые фрагменты. Backend failure
  возвращает503search_unavailable, без скрытого fallback. Зависимости не добавлены.
- Первые375 существующих проверок passed. Полный1426/28/0,108,70s; затем дополнительный
  role-denial case и targeted52/0,11,29s. Node66/0. Real HTTP7 ролей/search/QA/
  provider failures/CRM/ICS/smart/restartpassed3,99s. Browser-ветка поиска добавлена
  в v2_ui_check, локальный Chromium не повторялся после socket refusal.
- Frozen double pipeline passed30/30 задач,36/36QA,17/17claims,0rights/false_actions.
  Gold и live модели не менялись; host должен повторить QA после смены ranking.
- Версии/valid_until/сводка/diff/противоречия остаются. Main/start-gateway не меняются.
  Прежний Windows smoke cc00745 ещё ждёт runner; его успех не заявлен.

## E6.2/E6.4 · версии, актуальность, выдержки и diff

- Восстановление среды подтвердило чистый574ab18. GitHub доступен. Предыдущий
  CI43166951277 полностью success: text/browser, Linux base/runtime, Windows
  release/runtime. Старые startup/provider failures не перенесены в PASS задним числом.
- Миграция13: временные файлы preview и индекс потомков. Owner-only загрузка
  редакции, неизменяемые оригинал/фрагменты, наследование ACL/metadata; confirm
  сверяет content/fragments/ACL/metadata/file, replay/concurrency, cancel без записи.
- SQL выбирает актуальный доступный потомок до FTS. Явная история в QA, динамические
  expiry/superseded warnings, saved answer409 при замене, повторный ACL. Встречи
  сохраняют явные ссылки на редакцию; новая версия сама не подменяет материалы.
  Prepare фильтрует старые прикреплённые редакции и проверяет замену под write_tx.
- «Знания» получили библиотеку, фильтр, историю, upload preview/cancel/confirm,
  краткие выдержки с источниками и diff Было/Стало. Secret никогда не используется
  в этих аналитических ответах; невидимые версии и predecessor ID не раскрываются.
  Новых цветов/шрифтов/CSS/зависимостей нет. App.py/start-gateway не менялись.
- Target26 passed. Первый full1450/28/0; после3 дополнительных случаев и write_tx
  финальный1453 passed/28 skipped/0 failed,155,76s. Node66/0. Старые тесты не удалены.
  Во время разработки помощник теста повторял ключ для разных подтверждений;
  сервер правильно дал409, помощник исправлен на уникальные ключи.
- HTTP7 ролей/provider503/CRM/ICS/смены/версии/cancel/replay/restart passed5,47s;
  вызовов модели нет. Frozen double30/30 задач,36/36QA,17/17claims,0rights/false_actions.
  Полные отчёты reports/v2-document-versions-*. Миграции пустой/v8 и повторseed
  прошли в full. OpenAPI72; Python/JS syntax/diff и YAML parsed (системный PyYAML;
  он не добавлен в продукт). Scan8042 добавленных строк/новых файлов:0 совпадений
  форматов private/GitHub/AWS/Telegram/Slack/Bitrix/телефонов, не полный DLP.
- UI путь новой редакции добавлен в v2_ui_check с360/768/1440. Локальный Chromium
  повторно не запускался после socket policy refusal; новый CI ещё обязателен.
  Модели/микрофон/настоящие аккаунты не запускались.
- Границы DOCUMENTS.md: «Кратко» — точные выдержки, не смысловой пересказ; partial
  помечает пропуски. Противоречия/обязательства/полный редактор metadata/несколько
  файлов/фоновые retention jobs остаются. Draft BLOB удаляется при confirm/cancel,
  purge либо следующем preview по expiry; максимум10 файлов по5МБ на пользователя.
  Слияние полного v2 пока не допускается: E10/частьP1/P2 не выполнены, PR12 draft.
