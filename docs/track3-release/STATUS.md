# Состояние Фокус v2 —12.11.2026

PR12 уже merged владельцем. Ветка `track3/v2-fotoprint` содержит опубликованный
срез7a7d383 (assistant/operations/adapters), дерево сверено с локальным
d30114e. Новый main17c3ff4 (оформление, KPI, голосовые приветствия/TTS) включён обычными merge до031e1eb.
Следующая поставка требует нового draft PR; завершённость всего ТЗ не заявляется.

Реализованы домен/seed/роли/ACL, документы/версии/FTS5/источники, подготовка,
протокол/поручения/решения, scoped KPI/брифинг, assistant read-tools/history/
feedback и human-confirmed действия. Voice передаёт read-запросы тем же
сервисам, запись действий требует экранного preview/confirm.

Operations: retention worker, сроки/admin confirm удаления, browser origin/header,
rate limits, CSP/self-hosted Jost, внутренние уведомления/opt-in очереди,
комментарии/история задач, MD/HTML export и локальные EML. Bitrix transport
behind flag проверен только на MockTransport; ERP/Mary/HR остаются синтетическими
витринами. Calendar: ICS/подписки, смены/буферы/optional, Bitrix provider и
предварительная durable reservation; uncertainty не создаёт повтор/письма.

Локальное продолжение E7/E9: consented audio jobs/assets, сохранность при503,
retry/recovery, transcript import preview/confirm, таймкоды/player/аналитика;
звонки с17 темами, цитатным чек-листом/триггерами/сигналами риска, own/dept scope.
Показатель→источник→проект встречи/поручения с повторным proof-check. Повестка:
KPI отдела, просроченные решения, top3 тем звонков недели с источниками.
Документная сводка может выбрать ключевые фрагменты через opt-in модель,
сохраняя утверждения дословными; default — первые подходящие выдержки.

Опубликованный срез7a7d383:1547 Python passed/28 skipped, Node66; HTTPdouble и
HTTPunavailable passed. После E7/нового main запущен отдельный полный прогон.
Target E7/calls/operations/seed30, E9/assistant18, document selector10 passed.
Frozen call rules-control passed на оригинальном и отдельном timed тексте;
старый v2 корпус/hash не менялись. Frozen evaluator30/30 задач и17/17 claims
на double — проверка конвейера, не качество настоящей модели.

Главный остаток: P2 (серии/Google, конфликты/обязательства, weekly digest,
seasonal/quality/PVZ/effect loop/переговорная), окончательные docs/traceability/чистая установка/новый CI.
Live Ollama/ASR/TTS/диаризация/микрофон выполняются хостом по LIVE_CHECKS;
агент модели и реальные аккаунты не запускал. Голосовые лицензии и независимая
установка остаются указанными ограничениями.

[Самоаудит](SELF_AUDIT.md) · [Проверки](TEST_REPORT.md) · [Запуск](V2_QUICKSTART.md)
· [API](API.md) · [Хранение](DATA_POLICY.md) · [Проверки хоста](LIVE_CHECKS.md).

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
