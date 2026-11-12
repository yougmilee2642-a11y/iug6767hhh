# Самоаудит Фокус v2 — 12.11.2026

Промежуточный аудит `track3/v2-fotoprint`, [PR #12](https://github.com/yougmilee2642-a11y/iug6767hhh/pull/12).
Полное ТЗ не выполнено; PR остаётся draft. Нумерация взята из сводки §2
`V2_SPEC.md`: отдельного полного первоисточника хакатона в checkout нет.
«Выполнено» означает реализацию с CPU/double/HTTP проверками указанного объёма,
не подтверждение качества настоящей модели или production-готовности.

| Требование | Статус | Доказательство | Риск/оставшаяся проверка |
|---|---|---|---|
| ОТ-01: запуск ≤15 минут | Частично | `clean_install.py`, V2_QUICKSTART; исходный чистый клон 65,88 s выявил пропуск PDF reader; runtime 12,68 s прошёл | Base/runtime Linux CI 43161157327 passed; Windows пока queued; кэш тёплый, модели не включены |
| ОТ-02: серверные роли | Выполнено | `test_access_matrix.py`, SQL/classification matrix, HTTP семи уровней | Production identity/SSO отсутствует |
| ОТ-03: синтетика | Выполнено | `test_fotoprint_seed.py`: генератор, хеши, 18 пользователей, 54 документа, 600 заказов/250 клиентов/400 обращений | Не представляет реальные данные/нагрузку |
| ОТ-04: журнал | Выполнено | core denial-survives-rollback; privacy audit/logout/filters/CSV tests | Нет внешнего неизменяемого журнала/авторотации |
| ОТ-05: ошибки | Выполнено | `test_meetings.py` model errors; HTTP `--unavailable`; CRM uncertain/replay | Реальные порталы не проверены |
| ОТ-06: русский/адаптив/клавиатура | Частично | 35 UI-тестов, v2 UI 360/768/1440 в CI | Финальный CI нового head; полный ручной accessibility-аудит отсутствует |
| ОТ-07: TZ/валюта/формулы | Выполнено | `test_track3_management.py`, domain_metrics, decision_controls; Europe/Minsk/BYN | as_of не восстанавливает прошлую историю статусов задач |
| ОТ-08: лицензии | Частично | LICENSES; `reports/v2-e0-dependencies.json`, notice hashes | PyMuPDF AGPL/commercial, Silero noncommercial, bundled FFmpeg/libsndfile |
| §7.2.1: подготовка | Выполнено | `test_track3_preparation_v2.py`, core previous-meeting tests | Семантика live неизвестна; локальный проект повестки не сохраняется |
| §7.2.2: календарь | Выполнено | `test_track3_calendar.py`: занятость/cancel/гонки/replay/ACL | Mock/local outbox, ICS/EML и отзыв подписок: test_track3_calendar_interchange.py; смены/провайдеры остаются P1 |
| §7.2.3: протокол/цитаты | Требует живой проверки хостом | core summary/risk/outcome/unknown/edited/quote tests; evaluator v2 | Настоящая модель не измерена |
| §7.2.4: поручения | Выполнено | `test_track3_task_controls.py`, core confirm/cancel/filter/link tests | Комментарии/эскалация остаются P1 |
| §7.2.5: QA с источником | Требует живой проверки хостом | knowledge tests; frozen 36 QA, double pipeline | Единый чат/FTS5 ещё не реализованы |
| §7.2.6: обзор | Выполнено | domain_metrics/management/decision_controls tests | Брифинг и метрика→действие остаются P1 |
| AI-01: источник/дата | Выполнено | Source resolver, knowledge_hardening, KPI/protocol tests | Цитата подтверждает текст, не истинность источника |
| AI-02: права до модели | Выполнено | `test_access_matrix.py::test_designer_budget_and_secret_never_reach_model`, SQL predicate | Распространить на будущие коннекторы |
| AI-03: человек подтверждает | Выполнено | core/task/decision/calendar/CRM confirm/cancel/concurrency | Ручное редактирование отдельно от AI-предложений |
| AI-04: статусы решений | Выполнено | core accepted-outcome-contradicted→discussed, extract status tests | Реальные неоднозначные формулировки не измерены |
| AI-05: не выдумывать | Требует живой проверки хостом | Цитаты/имена/сроки, no_data/refusal, scorer v3 | Правила не доказывают полноту/семантику |
| AI-06: аудит AI | Выполнено | core/knowledge/privacy: masked question, source/model/stage/request ID | Автоматическое хранение/очистка ещё не реализованы |
| AI-07: правка/feedback | Выполнено | core edit/recheck/feedback tests | Полного UI version diff нет |
| §7.4: ограничения/защита | Частично | privacy/injection corpus≥15, intent refusals, secret exclusion, DATA_POLICY | Шаблонный PII-фильтр, свободные адреса, retention/CSRF/rate limits не закрыты целиком |
| §7.5: recall≥80%/sources/ACL/cancel/links | Требует живой проверки хостом | Frozen 5 текстов/30 задач/36 QA, double pipeline; CPU/HTTP остальные условия | Live v2 NOT RUN; v1 18/18 и 16/16 — только старое сообщение хоста |
| §8: набор данных | Выполнено | seed/generator/hash tests, календарь/задачи/классификации | Только синтетика |
| §9: комплект сдачи | Частично | README, ARCHITECTURE, API/OpenAPI/requests, TEST_REPORT, политики/лицензии/live, DEMO/PITCH | Финальные проверки и остальная реализация P1/P2 впереди |

## Эпики целиком

| Эпик | Состояние |
|---|---|
| E0 | Выполнено: поставки объединены без переписывания истории |
| E1 | Выполнено: домен/синтетика/миграции/seed |
| E2 | Матрица/администрирование/делегирование выполнены; новые P1-маршруты впереди |
| E3 | P0 mock CRM выполнен; Bitrix24 transport/Mary-адаптер/импорт-сверка не выполнены |
| E4 | Mock, ICS export/import/subscriptions и EML download выполнены; смены/провайдеры и автоматические .eml-файлы не выполнены |
| E5 | Унаследован voice MVP; v2-команды частично, микрофон/модели NOT RUN |
| E6 | Форматы/цитаты/ACL/устаревание есть; FTS5/сводка/сравнение не выполнены |
| E7 | Унаследованы аудио endpoints; jobs/storage/call analytics v2 не выполнены |
| E8 | P0 подготовка/поручения/протокол выполнены; история/комментарии/эскалация/экспорт P1 |
| E9 | P0 KPI/решения выполнены; отклонение→действие/брифинг не выполнены |
| E10 | Единый чат не выполнен |
| E11 | P0 privacy/injection/audit выполнены с границами выше; retention/web-hardening остаются |
| E12 | Центр уведомлений не выполнен |
| E13 | Оценщик/frozen controls выполнены; live у хоста, E7 call analytics NOT RUN |
| E14 | Документация/автопроверка установки в этом блоке; приёмка после CI |
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
UX 20%: браузерная регрессия есть, новые P1-экраны ещё не сделаны. Интеграции 15%:
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
