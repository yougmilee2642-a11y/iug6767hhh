# Callwise — Iteration 3.2: отчёт для независимого аудита

Дата: 28 сентября 2026. Область: корректность Evaluation и надёжность live provider path.
Статус: критерии 3.2 A–F выполнены, включая настоящий Groq tool round trip.
Это не production-сертификация и не полный live readiness benchmark. Iteration 4 не начата.

## 19 запрошенных пунктов

1. **Почему падал pricing-only.** trusted_scenarios и EvaluationPlan получали любые сведения об услуге через booking_context. Обращение service["employees"][0] вызывало IndexError при employees=[]; план также безусловно читал сотрудника, дату и время.

2. **Разделение контекстов.** service_context возвращает только service_id, service_name, price, currency, duration. booking_context расширяет эти факты допустимым сотрудником, датой, временем и рассчитанным по расписанию слотом. При отсутствии условий для записи возвращает {}. Pricing и его перефразировки не запрашивают booking facts. План сохраняет непокрытые booking axes, а не придумывает запись на полночь.

3. **Pricing coverage требует knowledge.** Нужен непустой каталог services; каждая оцениваемая услуга должна иметь конечную неотрицательную цену и валюту из трёх заглавных букв. Сохранённые price/currency сверяются с BusinessInput. Generic FAQ допустим как способ ответа только при наличии проверенных цен. Пустой или неверный каталог даёт MISSING; обязательный pricing сохраняет price_grounded, поэтому «нет информации о цене» не становится pricing PASS. Overall не READY. Длительность, сотрудники и календарь не являются зависимостями pricing coverage.

4. **Pricing-only без сотрудников.** Price Test / Консультация / 50 BYN / 30 минут / Консультант / employees=[] создаётся существующим Builder, проходит validation, сохраняется и запускает Evaluation. План имеет только service_pricing, без employee/schedule axes. Booking-not-requested проверки не требуют booking capability/tools. Тесты проверяют канонические 50 BYN; в браузере реплика составила 50.0 BYN без инструментов. Локальный результат: 12 PASS, 0 FAIL, 0 ERROR, READY только проверенного scope.

5. **Классификация ошибок.** ProviderError различает rate_limit, tool_generation_failed, invalid_request, model_unsupported, structured_output_failed, timeout, network, authentication, unknown. Поля: provider, model, operation, status_code, category, retryable, safe_reason, request_count/retry_count. Неизвестный model ID отображается как unrecognized_model, а не произвольный текст .env. Ошибка провайдера остаётся ERROR / INCONCLUSIVE; доказанная до неё небезопасная запись по-прежнему даёт NOT_READY — регрессия сохранена.

6. **Безопасная диагностика Groq.** Сохраняются только разрешённые type/code, наличие failed_generation, фиксированный код причины генерации, разрешённое имя инструмента, известный parameter/capability mismatch и стадия операции. Произвольный failed_generation.reason не копируется: он преобразуется в безопасный код. Нет ключей, headers, raw request/response, reasoning, полных attempted arguments и клиентских персональных данных в ошибках. Тесты подставляют секрет/телефон-маркеры и проверяют в том числе сохранённый отчёт.

7. **Как доказана retryability.** HTTP 400 при наличии tools плюс tool_use_failed либо явный признак invalid function generation / неверного JSON отделяется от ошибки параметров, схемы или модели. Unsupported parameter/schema/config имеет приоритет даже при failed_generation. Некорректный JSON аргументов в полученном tool call также является явным дефектом генерации. Произвольного HTTP 400 или одного наличия failed_generation для повтора недостаточно.

8. **Когда делается повтор.** Максимум один retry для доказанного tool_generation_failed. Messages/tools остаются теми же, AgentConfig и prompt не меняются; temperature снижается с .2 до 0. Нет retry для arbitrary 400, schema/config, unsupported parameter, authentication, invalid model, timeout/network или 429. Транспортные повторы SDK выключены. Каждая попытка расходует общий бюджет, retry metadata видна и при последующем успехе. Вторая ошибка останавливает вызов; остаток бюджета в один запрос не разрешает повтор.

9. **Provider preflight.** Отдельные harmless probes: видимый текст; lookup_test_value(probe_item); локальное исполнение проверенного lookup и возврат role=tool с matching tool_call_id и JSON; strict JSON schema для capabilities Generator/Judge. Одинаковая structured model проверяется один раз, разные — независимо. Проверенный allowlist из GPT-OSS 20B/120B закрывает cloud path для неизвестных env IDs. Cloud Evaluation выполняет preflight до сценариев: при FAIL сценарии ERROR/not_run, инфраструктурная причина сохранена. Локальные doubles используют NOT_REQUIRED. Лимит 6 запросов, включая разрешённый retry; BusinessInput и клиентская история не отправляются.

10. **Текущий gpt-oss preflight.** Модель openai/gpt-oss-20b; начало 2026-09-28T08:10:57Z. agent_text PASS, agent_tools PASS, tool_continuation PASS, structured_outputs PASS. Четыре HTTP-запроса, ноль повторов, без fallback. Небольшая strict schema проверяет возможность API, а не качество судьи или генератора.

11. **Bounded live functional smoke.** Все пять наблюдений PASS: реальный LLM сообщил 50 BYN без employees; настоящий Runtime исполнил check_slots локального календаря (4 слота); модель получила этот результат и продолжила разговор; сработал серверный immediate handoff; реальный unsupported request не выполнил fake tool и не создал запись. tool_round_trip=true. Runtime не изменён: первый read-tool ответ остаётся быстрым серверным текстом, а LLM continuation проверено настоящим следующим пользовательским ходом с сохранённым tool result. Этот серверный шаблон не выдаётся за ответ модели. Injected fake provider output в live suite отсутствует. Полный booking/readiness не запускался.

12. **Реальные запросы.** Всего 8 из общего жёсткого лимита 12: preflight 4 + functional 4. Pricing 1, check_slots 1, continuation 1, server handoff 0, unsupported 1. Повторов 0. CLI прекращает functional suite при первом provider exception, включая 429, и не ищет удачный ответ повторными прогонами. Каждое наблюдение сохраняет provider/model/operation/request_count/retry_count. Секреты не печатались.

13. **Fallback model.** Не использовалась, не добавлена и автоматически не выбирается. Модель и production Runtime prompts не переписывались. Ролевые model IDs фиксируются на время cloud run.

14. **Локальные тесты.** Исходно: 247 passed / 12 opt-in skipped. Итоговый полный прогон: 274 passed / 12 skipped. Добавлено 27 тестов: pricing без employees, пустой каталог/FAQ, неверные цены/валюта, knowledge dependencies, plan scope, нормализация и редактирование ошибок, exact request encoding, единственный retry, nonretryable ошибки, bounded preflight/fail-fast, диагностический Runtime round trip и остановка на 429. Старые safety/confirmation/provenance и critical defect + provider error регрессии проходят. После усиления диагностических evidence дополнительно 27 новых тестов снова прошли. Пропущенные opt-in тесты не объявлены live-успехом: live evidence получено отдельно CLI.

15. **Browser smoke.** Пройден реальный UI-путь: форма Builder → review требований → сохранение → Evaluation. Временная база, deterministic providers, без email. Price Test: 12/12 PASS, employees 0/0. Nova Beauty: 18/18 PASS, services 2/2, employees 2/2; разные назначенные сотрудники, будни/суббота, near closing и closed time. Оба локальных scoped READY явно помечены как test provider, не качество Groq. Infrastructure показывает NOT_REQUIRED и ноль облачных запросов локально. Снимки: proof/iteration3-2-pricing.png и proof/iteration3-2-nova.png. Smoke-агенты не записаны в рабочую базу. Навык computer-use использован для проверки в отдельной временной среде, без изменения рабочих бизнес-данных.

16. **Статика и запуск.** python -m compileall -q по проекту с исключением data/venv/cache: exit 0. node --check static/app.js, static/builder.js, static/evaluation.js: каждый exit 0. Рабочий сервер запущен на http://127.0.0.1:8000; /api/health сообщает status=ok. Существующий .env не изменён. В UI добавлен только компактный Infrastructure block; redesign не выполнялся.

17. **Docker.** NOT TESTED: команда docker недоступна на этом компьютере. Docker не устанавливался, production deployment не выполнялся.

18. **Ограничения.** Неизвестную ошибку 400 из 3.1 нельзя ретроспективно объяснить без её тела; текущий live run не получил 400. Классификация/retry проверены SDK-shaped fault fixtures, а не выдуманным live 400. Smoke — одно bounded наблюдение, не гарантия стабильности, полный booking, live readiness или проверка качества речи. Structured preflight использует небольшую репрезентативную схему. Другие model IDs намеренно блокируются до проверки capabilities. Synthetic readiness остаётся scoped. Существующие Builder/validation всё ещё требуют обычную валидную конфигурацию расписания, хотя pricing evaluation не зависит от сотрудников/booking facts. Runtime и Builder не перестраивались.

19. **Переход к Iteration 4.** Критерии A–F выполнены, включая настоящий Groq local-tool round trip и preflight, и функционального Runtime path. Архив и доказательства готовы к независимому аудиту. Только после аудита и явного указания пользователя можно начинать Iteration 4. Shadow Mode, Progressive Autonomy, telephony/SIP/MTS/Twilio, CRM/calendar, RAG, auth/billing, multi-agent/prompt rewriting и production deployment не начаты.

## Воспроизведение без вывода секретов

Из корня проекта с существующим .env:

~~~powershell
python -m pytest -q
python -m compileall -q agents builder evaluation providers services tools tests app.py storage.py requirement_contract.py
node --check static/app.js
node --check static/builder.js
node --check static/evaluation.js
python -m evaluation.provider_diagnostics --functional --output proof/provider-functional.json
~~~

Последняя команда — opt-in и расходует максимум 12 provider requests вместе с preflight/retries.
Использует synthetic data/изолированную SQLite, не является readiness benchmark и не отправляет email.
Для одного preflight уберите --functional. JSON содержит счётчики, булевы evidence и safe категории,
не полный текст провайдера, reasoning или запросы.

Доказательства:
- proof/iteration3-2-live.json — общий bounded результат.
- proof/iteration3-2-preflight.json — отдельный preflight из того же запуска, без новых запросов.
- proof/iteration3-2-functional.json — отдельный functional из того же запуска.
- proof/iteration3-2-pricing.png / proof/iteration3-2-nova.png — локальная UI-проверка, не cloud scores.

## Проверка совместимости

Проверено 28.09.2026 по первичной документации Groq, независимо подтверждено adapter tests/live probes.
Для выбранной модели допустимы reasoning_effort=low, max_completion_tokens и tool_choice=auto. [Groq API Reference](https://console.groq.com/docs/api-reference)
GPT-OSS поддерживает local tool use, но не parallel tool use; сохранены parallel_tool_calls=false и JSON tool messages с matching tool_call_id. [Tool Use Overview](https://console.groq.com/docs/tool-use/overview)
GPT-OSS 20B/120B поддерживают strict JSON schema; формат запрашивается отдельно от tools. [Structured Outputs](https://console.groq.com/docs/structured-outputs)
Failed tool generation может дать HTTP 400 с failed_generation и отличается от invalid request parameters. [Local Tool Calling](https://console.groq.com/docs/tool-use/local-tool-calling)
reasoning_format для GPT-OSS не добавлялся; reasoning поля не используются в сохранённых результатах. [Reasoning](https://console.groq.com/docs/reasoning)

## Сохранение scope

SHA256 не изменились относительно 3.1:
- agents/runtime.py: 1F286BE13C597D0F2CE21522B4FFC1898F008035BCBB7FA91519EDB1BF82C8AD
- agents/factory.py: CE6E44CF0E8969B1C8C019A58FE89B822C635CC6F0B65C0AA38B2F36A7295511

Synced sources/, ключи и существующие бизнес-записи не редактировались.
Полный ZIP содержит исходники, requirements/.env.example/README, regression tests, отчёты и safe proof artifacts.
.env/.env.txt, SQLite/data, venv/cache/logs и старые ZIP исключены; список содержимого архива проверяется.
