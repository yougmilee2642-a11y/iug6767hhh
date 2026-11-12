# Самоаудит Фокус v2 — 12.11.2026

Промежуточный аудит `track3/v2-fotoprint`, [PR #12](https://github.com/yougmilee2642-a11y/iug6767hhh/pull/12).
Полное ТЗ не выполнено; PR остаётся draft. Нумерация взята из сводки §2
`V2_SPEC.md`: отдельного полного первоисточника хакатона в checkout нет.
«Выполнено» означает реализацию с CPU/double/HTTP проверками указанного объёма,
не подтверждение качества настоящей модели или production-готовности.

| Требование | Статус | Доказательство | Риск/оставшаяся проверка |
|---|---|---|---|
| ОТ-01: запуск ≤15 минут | Частично | `clean_install.py`, V2_QUICKSTART; Linux base/runtime и Windows runtime CI43166951277 success на574ab18 | Новый head проверяется отдельно; кэш неконтролируемый, модели не включены; независимый человек не запускал |
| ОТ-02: серверные роли | Выполнено | `test_access_matrix.py`, SQL/classification matrix, HTTP семи уровней | Production identity/SSO отсутствует |
| ОТ-03: синтетика | Выполнено | `test_fotoprint_seed.py`: генератор, хеши, 18 пользователей, 54 документа, 600 заказов/250 клиентов/400 обращений | Не представляет реальные данные/нагрузку |
| ОТ-04: журнал | Выполнено | core denial-survives-rollback; privacy audit/logout/filters/CSV tests | Нет внешнего неизменяемого журнала/авторотации |
| ОТ-05: ошибки | Выполнено | `test_meetings.py` model errors; HTTP `--unavailable`; CRM uncertain/replay | Реальные порталы не проверены |
| ОТ-06: русский/адаптив/клавиатура | Частично | 35 UI-тестов, v2 UI 360/768/1440 в CI | Финальный CI нового head; полный ручной accessibility-аудит отсутствует |
| ОТ-07: TZ/валюта/формулы | Выполнено | `test_track3_management.py`, domain_metrics, decision_controls; Europe/Minsk/BYN | as_of не восстанавливает прошлую историю статусов задач |
| ОТ-08: лицензии | Частично | LICENSES; `reports/v2-e0-dependencies.json`, notice hashes | PyMuPDF AGPL/commercial, Silero noncommercial, bundled FFmpeg/libsndfile |
| §7.2.1: подготовка | Выполнено | `test_track3_preparation_v2.py`, core previous-meeting tests | Семантика live неизвестна; локальный проект повестки не сохраняется |
| §7.2.2: календарь | Выполнено | `test_track3_calendar.py`: занятость/cancel/гонки/replay/ACL | Mock/local outbox, ICS/EML и отзыв подписок: test_track3_calendar_interchange.py; смены/буферы/optional реализованы; Bitrix provider/reservation/uncertain реализованы: test_track3_calendar_providers.py; Google/series остаются P2 |
| §7.2.3: протокол/цитаты | Требует живой проверки хостом | core summary/risk/outcome/unknown/edited/quote tests; evaluator v2 | Настоящая модель не измерена |
| §7.2.4: поручения | Выполнено | `test_track3_task_controls.py`, core confirm/cancel/filter/link tests | Комментарии/история/эскалация реализованы; внешняя доставка уведомлений ещё не подключена |
| §7.2.5: QA с источником | Требует живой проверки хостом | knowledge tests; frozen 36 QA, double pipeline | FTS5/BM25 со scoped corpus проверен; единый чат реализован: test_track3_assistant.py; live router не проверен |
| §7.2.6: обзор | Выполнено | domain_metrics/management/decision_controls tests | Дневной брифинг реализован/read-only (test_track3_briefing.py); метрика→действие остаётся P1 |
| AI-01: источник/дата | Выполнено | Source resolver, knowledge_hardening, KPI/protocol tests | Цитата подтверждает текст, не истинность источника |
| AI-02: права до модели | Выполнено | `test_access_matrix.py::test_designer_budget_and_secret_never_reach_model`, SQL predicate | Распространить на будущие коннекторы |
| AI-03: человек подтверждает | Выполнено | core/task/decision/calendar/CRM confirm/cancel/concurrency | Ручное редактирование отдельно от AI-предложений |
| AI-04: статусы решений | Выполнено | core accepted-outcome-contradicted→discussed, extract status tests | Реальные неоднозначные формулировки не измерены |
| AI-05: не выдумывать | Требует живой проверки хостом | Цитаты/имена/сроки, no_data/refusal, scorer v3 | Правила не доказывают полноту/семантику |
| AI-06: аудит AI | Выполнено | core/knowledge/privacy: masked question, source/model/stage/request ID | Worker хранения реализован; внешние/скачанные копии удаляются отдельно |
| AI-07: правка/feedback | Выполнено | core edit/recheck/feedback tests | История редакций протокола ещё не реализована |
| §7.4: ограничения/защита | Частично | privacy/injection corpus≥15, intent refusals, secret exclusion, DATA_POLICY | Шаблонный PII-фильтр, свободные адреса, retention/Origin+header/rate limits реализованы: test_track3_operations.py; свободные адреса всё ещё ограничение PII-фильтра |
| §7.5: recall≥80%/sources/ACL/cancel/links | Требует живой проверки хостом | Frozen 5 текстов/30 задач/36 QA, double pipeline; CPU/HTTP остальные условия | Live v2 NOT RUN; v1 18/18 и 16/16 — только старое сообщение хоста |
| §8: набор данных | Выполнено | seed/generator/hash tests, календарь/задачи/классификации | Только синтетика |
| §9: комплект сдачи | Частично | README, ARCHITECTURE, API/OpenAPI/requests, TEST_REPORT, политики/лицензии/live, DEMO/PITCH | Финальные проверки и остальная реализация P1/P2 впереди |

## Эпики целиком

| Эпик | Состояние |
|---|---|
| E0 | Выполнено: поставки объединены без переписывания истории |
| E1 | Выполнено: домен/синтетика/миграции/seed |
| E2 | Матрица/администрирование/делегирование и новые scoped маршруты проверяются target/full/HTTP; live UI нового main ждёт CI |
| E3 | Mock + Bitrix transport/Mary/1C/HR adapters и admin mapping реализованы; реальный портал NOT RUN; Amo/Zoho stubs |
| E4 | ICS/подписки/смены/буферы/optional/EML и Bitrix calendar реализованы; durable sending/uncertain; Google/серии P2 остаются |
| E5 | Read tools и action drafts реализованы; уточнение имён/дат/слотов и live скрипт голоса ещё нужны; микрофон/модели NOT RUN |
| E6 | Форматы/ACL/FTS5/версии/актуальность/diff/экстрактивные выдержки; opt-in model fragment selector с recheck; конфликты/обязательства P2 остаются |
| E7 | Jobs/storage/consent/retry/recovery/import/player/analytics/calls17 topics реализованы и target checked; optional model topics/ATC watcher остаются; live ASR/diarization NOT RUN |
| E8 | Подготовка/задачи/протокол, comments/history, escalation, MD/HTML export/local EML; scoped контекст next-agenda; live семантика не проверена |
| E9 | KPI/решения/брифинг и source→human-confirmed meeting/task реализованы; digest/seasonal/effect P2 остаются |
| E10 | Read tools/allowlisted selector/evidence/private history/feedback и action preview/confirm реализованы; live router NOT RUN |
| E11 | Privacy/injection/audit, retention/delete request/admin confirm, Origin/header/rate-limit/CSP/self-hosted font реализованы; описанные границы PII остаются |
| E12 | Внутренний центр/settings/назначение/срок/эскалация/meeting/audio/briefing; opt-in внешние очереди и physical EML, внешние Telegram/Bitrix senders ещё не включены |
| E13 | Frozen v2/double и отдельный original+timed call rules-control; live модели и независимая семантическая проверка у хоста |
| E14 | Docs/OpenAPI/live scripts обновляются; clean-install и новый CI после общего среза |
| E15 | Не начат; автоматической проверки эффекта решения нет |

Шесть веток поведения сопоставлены в TEST_REPORT. Одна общая проверка не
засчитывается за шесть случаев каждой функции. Stale витрина, изменённый preview
и отозванная цитата — разные проверки. Документация не закрывает пробелы P1.

## Проверки перед публикацией

Новые исходники не включают `.env`, `data/`, `models/`, `secrets/` или
`start-gateway.ps1`. История добавленных строк проверяется на ключи/webhooks/
private keys; известные вымышленные номера — тестовые фикстуры. Full pytest/Node,
diff и результаты установки записываются в TEST_REPORT после завершения.
Gold не меняется. Зелёный CI не превращает partial/not-run в готовность всего ТЗ.

## Сильные и слабые стороны по весам оценки

Бизнес 25%: данные/поручения/KPI есть, полный signal→action и звонки отсутствуют.
UX 20%: P1-формы реализованы в существующем оформлении; новые browser-сценарии ожидают CI. Интеграции 15%:
витрины/mock, без реального Bitrix24. Техника 15%: транзакции/миграции/CI;
масштабирование 5% ограничено локальным прототипом. Безопасность 15%:
роли/цитаты/confirm есть, retention/rate limits/лицензии остаются. Презентация 5%:
сценарий написан, живой показ не отрепетирован. Баллы не выставляются.

Пять рекомендаций хосту:

1. Запустить live_eval из LIVE_CHECKS на чистом опубликованном SHA и сохранить исходный JSON.
2. Отдельно проверить микрофон/ASR/TTS/диаризацию и latency; текстовый double их не проверяет.
3. Пройти DEMO на отдельной временной БД, не скрывать ручной путь/mock.
4. Решить условия PyMuPDF/Silero и внешних UI-шрифтов до распространения.
5. Завершать P1 по порядку ТЗ, не добавлять P2 до зелёных P0/P1 и не сливать draft по одному числу тестов.

## Продолжение E3/E4/E5/E8/E10/E11/E12 ·12.11.2026

Реализованы assistant read-tools/evidence/history, подтверждаемые task/meeting/
task-status drafts; voice делегирует им без скрытых записей. Протокол: MD/HTML,
локальная рассылка, comments/history. Хранение, delete request/admin confirm,
CSRF, limits, внутренние уведомления и generic opt-in очереди.
Bitrix: HTTPS transport double, local scope до remote read, маппинг людей/
сущностей, обезличенные contact/activity, safe uncertainty. Calendar: commit
reservation до HTTP, replay/crash→uncertain/no resend, no invitation on failure.
Ни одного реального аккаунта/модели не использовано.

Проверки до последнего calendar-провайдера:1509 passed/28 skipped; обе ветки
HTTP (double/unavailable) passed; Node66 passed. Новый полный прогон и CI
фиксируются в журнале исполнения. Не подменять этим live acceptance.

Крупный остаток: E7 аудио/звонки; E9.2 action drill-down; E8.6 источники
следующей повестки; E6 semantic-selector и P2; финальная traceability/evaluation/
проверка установки и живые скрипты. Весь ТЗ по-прежнему не закрыт.

Общий срез после merge E6+assistant/operations/adapters:1547 passed,28 skipped,
0 failed; Node66; HTTPdouble и HTTPunavailable passed. Первичные отчёты
`reports/v2-assistant-operations-*`. Browser/Windows проверяются новым CI отдельно.

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
