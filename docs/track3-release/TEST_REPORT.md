# Проверки Фокус v2 — 12.11.2026

Это отчёт прототипа. Проверки на scripted/transport doubles не измеряют качество
настоящих моделей и не подтверждают подключение внешних аккаунтов.
[История измерений](TEST_REPORT_HISTORY.md) сохраняет старые срезы и ошибки;
актуальная сводка ниже заменяет старые утверждения о незавершённых P1/P2.

## Воспроизводимые результаты

| Проверка | Результат / первичный отчёт |
|---|---|
| Расширенные отчёты, весь Python на 0207c3c | 1653 passed, 28 skipped, 0 failed, 308.95с; reports/v2-radar-full.log |
| Отчёты/operations/briefing | 34 passed; формулы, нулевая мощность, ACL, подпись источника, устаревший confirm, weekly cancel/replay и эффект111→96 |
| Доставка/operations | 16 passed; tests/test_track3_delivery.py и test_track3_operations.py, только транспортные дублёры |
| Финальный небраузерный Python | 1660 passed, 28 skipped, 0 failed, 337.41с на fafc326; reports/v2-final-full.log |
| Финальный JS | 66 passed, 0 failed; reports/v2-final-node.log |
| Настоящий HTTP | Passed: восемь ролей, источники/чужой404, cancel/confirm/replay, series/insights/weekly, закрытая SMTP, restart; reports/v2-final-http.json |
| Чистая runtime установка 110741f | Passed, 29.898с: clone/venv/pip check, seed дважды, HTTP8ролей/restart/model503, inventory; reports/v2-radar-runtime.json |
| Frozen v2 evaluator | Pipeline passed на double:30/30 задач,17/17 claims с источником,0 ошибок владельца/срока/прав/ложных действий; reports/v2-final-eval.json |
| Браузер, Linux/Windows | Финальный CI отдельно; локальный Chromium ограничен средой (socket EPERM), локальный browser NOT RUN |
| Ollama / ASR / TTS / диаризация | NOT RUN; LIVE_CHECKS.md, только скрипты для хоста |
| Настоящие Bitrix / Google / Telegram / SMTP | NOT RUN; транспортные MockTransport/SMTP doubles |
| Независимая установка человеком | NOT RUN; агентская/CI установка не является независимой |

Кэш pip не контролируется; время установки не включает скачивание весов.
Пропущенные тесты не засчитываются как passed. Требование live recall≥80%
остаётся проверкой хоста, даже при double recall=100%.

## Критерии §7.5 и ОТ-01..08

| Критерий | Тест/доказательство | Вывод |
|---|---|---|
| §7.5 recall≥80% | evaluate_v2 / test_track3_v2_evaluation.py / frozen gold | Конвейер проверен; live v2 NOT RUN |
| Утверждение→источник | core/knowledge/hardening/action_basis/document_insights/advanced_reports | CPU/double passed, семантическая полнота live неизвестна |
| Чужая роль и аудит отказа | test_access_matrix.py, core denial-survives-rollback, HTTP | Проверяется до модели и повторно при чтении/confirm |
| Отмена без записи | core/calendar/CRM/assistant/series/weekly/delivery | Cancel не создаёт бизнес-объект или отправку |
| Протокол↔поручение↔реплика | test_track3_core.py, task_controls, ui_track3/http_browser_smoke.py | API/HTTP и браузерная навигация в CI |
| ОТ-01 запуск | clean_install.py base/runtime, V2_QUICKSTART | Текстовый запуск измерен; ≤15мин с весами не заявляется |
| ОТ-02 права | access_matrix, roles/delegations/secret tests | Серверные SQL/объектные проверки; SSO не реализован |
| ОТ-03 данные | test_fotoprint_seed.py, frozen hash / generator | Только синтетика; новая seasonality отдельно от frozen v1/v2 |
| ОТ-04 журнал | core/privacy/operations/audit filters/CSV | Аудит отказа переживает откат; секреты/PII маскируются |
| ОТ-05 ошибки | model_*503, audio retained, provider/SMTP/notification timeouts | Сохранность исходника; uncertain без слепого повтора |
| ОТ-06 русский/адаптив | Node, UI35 и v2_ui_check360/768/1440 | Новый финальный browser CI обязателен; ручной accessibility-аудит неполон |
| ОТ-07 даты/формулы | management/domain_metrics/calendar/planning/advanced_reports | Europe/Minsk/IANA/DST, BYN, числитель/знаменатель, null вместо деления на0 |
| ОТ-08 лицензии | LICENSES.md, metadata/notice hashes | Условия голосовых весов и PyMuPDF требуют решения владельца |

## Шесть веток поведения

Сокращения обозначают `tests/test_track3_<имя>.py`. Это карта конкретных
сценариев, а не утверждение, что каждый тест проверяет всю систему.
«Не применяется» означает чистое чтение без доставки/зависимости, а не успешный вызов сервиса.

| Функция / файлы | Обычный путь | Нет прав | Повтор | Нет данных | Источник недоступен | Устаревание / изменение |
|---|---|---|---|---|---|---|
| QA: knowledge, knowledge_hardening, fts | цитатный ответ | SQL до поиска | saved answer recheck | insufficient_data | удалённая/отозванная цитата | replaced/valid_until/изменение во время модели |
| Протокол: core, document_summary | проверенные реплики | reader/foreign/secret | confirm без дубля | пустая расшифровка | model503/timeout/garbage | версия/редактирование после draft |
| CRM: crm, bitrix | reviewed create/update | employee/foreign token | replay/concurrency | нет mapping/данных | down/transport timeout | changed state / stale mirror |
| Календарь: calendar, calendar_availability, calendar_providers | слоты/приглашение | роли/ACL | durable replay | нет слотов/участника | unavailable provider | смены старше24ч / слот занят / DST |
| Серия/Google: planning | конечная серия/freebusy | capability/mapping | отдельные встречи без дубля | пустой календарь/конфликт | Google gate/timeout | изменённые люди/слоты/настройки |
| Обзор/брифинг: management, domain_metrics, briefing | формулы/claims | scoped суммы | GET без записей | null/нулевой знаменатель | витрина/CRM fault | as_of предупреждение |
| Документы: document_versions, document_insights | версии/diff/цитаты обещаний | чужой/secret/hidden successor | confirm одной версии/задачи | нет обещаний/условные фразы | источник исчез/сменил текст | current-version/proof recheck |
| Ассистент/голос: assistant, voice, intent | allowlisted reads/редактируемый draft | ACL/private speech/secret | action idempotence | честное уточнение | model router failure | права/поля/цитата после preview |
| Аудио/звонки: media, calls, call_topics | consent/import/17тем | own/dept/secret | retry/import/recovery | нет времени/реплик | asr503 сохранённый файл | ACL/source меняется во время обработки |
| Сезонный/PVZ/quality: advanced_reports |75×1.48=111/явный срок | scopeLOG/PROD | чтение без записи | нулевая мощность/нет истории | proof перестал разрешаться | HMAC меняется вместе с данными |
| Недельный дайджест: advanced_reports | preview→личный EML | чужой404 | один confirm/outbox | нет доступных claims | изменённый источник409 | текущий snapshot/hash recheck |
| Контроль результата: advanced_reports |111→96/цель≤100 | ACL снимков | один tick/confirm | waiting_data | недоступный снимок | новый снимок после контроля, ≤48ч |
| Переговорная/коридор: meeting_hints | подсказки/3фразы | consent/private/secret | чистое чтение | честное отсутствие встречи | нет доступной реплики | каждый запрос читает текущий ACL; нет долговечного ответа |
| Доставка: delivery, operations | genericTG/Bitrix, reviewedSMTP | владелец/ACL/active | durable claim, terminal uncertain | нет mapping/gate | timeout/обрыв sending | settings/config/address/hash/старше24ч |
| Хранение: operations | worker/policy/delete | admin confirm | replay/идемпотентная очистка | пустая тестовая БД | нет test-marker отказ | изменённая policy/preview |

## Команды

```bash
python -m pip install -r requirements-track3-v2-test.txt
python scripts/track3/check.py -q tests --ignore=tests/ui_track3
node --test tests/*.cjs static/mts-shell/tests/*.mjs
python scripts/track3/v2_http_smoke.py --output /absolute/new-http.json
python scripts/track3/v2_http_smoke.py --unavailable --output /absolute/new-unavailable.json
python scripts/track3/evaluate.py --dataset photoprint-v2 --scripted-double --output /absolute/new-eval.json
python scripts/track3/clean_install.py --profile runtime --output /absolute/new-runtime.json
python scripts/track3/clean_install.py --profile base --output /absolute/new-base.json
python -m unittest discover -s tests/ui_track3 -p 'test_browser.py' -v
python scripts/track3/v2_ui_check.py --output /absolute/new-ui.json --artifacts /absolute/new-ui
```

Все тестовые БД временные. Рабочие `.env`, `data/`, `models/` и пользовательский
`start-gateway.ps1` не изменяются. Результаты чистой установки привязаны к commit
в JSON; документационный commit не считается новым прогоном модели.
