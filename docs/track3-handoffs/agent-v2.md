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
