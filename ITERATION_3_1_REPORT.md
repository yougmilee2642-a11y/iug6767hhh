# Callwise — Iteration 3.1 / Evaluation Integrity + Coverage Hardening

Дата проверки: 28 сентября 2026. Работа выполнена в существующем проекте после Iteration 3.
Iteration 4 не начиналась. Телефония, production calendar/CRM, auth, billing, Shadow Mode и autonomy не добавлены.

## 1. Canonical RequirementContract

`requirement_contract.py`: закрытый типизированный договор requirements-1 с raw_tasks, entries
(task_index, source_text, requirement_id, polarity), source и confirmed. Каталог:
booking/pricing/faq/opening_hours/human_handoff/unsupported. Инструменты, capabilities, поля и
сценарии берутся из доверенного Builder catalog/registry, не из ответа модели.
Evaluation использует сохранённые entries; не классифицирует tasks повторно на каждом прогоне.
desired_role остаётся отдельным критическим identity-контрактом из BusinessInput.

## 2. Отрицания

Resolver разбивает задачи на простые фразы и распознаёт не/без/not/no; pricing подавляет
дублирующий generic FAQ, handoff — generic questions. «Не записывать клиентов, только отвечать
по ценам» → booking forbidden, pricing required. «Возвраты денег не нужны» и «CRM не подключать»
→ unsupported not_requested, не блокируют READY. «Передавать сложные вопросы человеку» →
required handoff, «Не передавать человеку» → forbidden. Это консервативный словарный resolver,
не универсальный semantic NLP. Сложные конструкции необходимо исправлять в review.

## 3. Пользовательское подтверждение

В существующем четырёхшаговом Builder, без нового wizard: на шаге услуг первый клик
«Сформировать черновик» показывает понятные типы/полярности каждой задачи. Пользователь
может изменить оба значения, затем «Подтвердить требования и сформировать». В конечном
preview договор показан вместе с AgentConfig. Save подтверждает обе части; сервер выставляет
confirmed=true. Review-token связывает config + contract, изменения делают старый token недействительным.
Старый API-формат без contract совместим: inference при intake, подтверждение при сохранении preview.
Конфликт required/forbidden для одной категории отклоняется до облачного Builder call.

## 4. Сохранение snapshot

Договор и неизменённый исходный BusinessInput хранятся в JSON builder_candidates;
агент ссылается на candidate_id и возвращает contract рядом с config. Каждый evaluation run
содержит requirement_contract и contract_hash, business/config snapshots и hashes.
Изменение любой из этих частей делает старый отчёт OUTDATED. Изменение raw tasks без нового
review отклоняется; evaluation не создаёт новую интерпретацию молча.
Generated legacy agent без contract получает legacy_inferred ровно один раз с предупреждением;
без подтверждения его успешный результат ограничивается LIMITED. Старые historical reports
не переписываются и показывают предупреждение об отсутствии сохранённого scope.

## 5. Защита language variants

LanguageVariant содержит только template_id/paraphrase_template. Генератор выбирает дословно
один из доверенных шаблонов с {service}/{date}/{time}; сервер подставляет canonical context.
Allowlist фиксирует не только факты, но и intent/polarity: вставка «не», возврата денег, другого
сотрудника, literal service/time, произвольного opening или format traversal отклоняется.
«Стрижка 10:00» вместо канонического «Маникюр 18:00» не попадает в Simulation и не создаёт
ложный FAIL агента. Максимум один repair. Цена, assertions, инструменты, expected state и setup
по-прежнему не доступны генератору для изменения. Разнообразие языка намеренно ограничено.

## 6. EvaluationPlan

`evaluation/plan.py` создаёт и сохраняет plan до исполнения: mode/seed, policy, выбранные
service/employee IDs и имена, расписание, полный trusted case context, desired_axes,
excluded_scenarios, optional_variants, request budget и оценки количества вызовов.
История читает этот snapshot, не пересэмплирует его. Новые service-case IDs используют
стабильные catalog IDs; отдельные employee/profile/boundary cases имеют уникальные суффиксы.

## 7. Выбор services/employees/schedules

Каталог ≤8 услуг / сотрудников — полный; больший — seeded sample до 5 для каждой сущности.
Pricing/booking покрывают каждую выбранную услугу, если соответствующая задача обязательна.
Проверяются доступные сотрудники и разные рабочие профили расписания, включая отличающийся
weekend, когда он есть. Добавлены обычная запись, последний подходящий слот near closing,
занятый слот и закрытый день; при работе семь дней используется outside-hours.
Непокрываемый сотрудник или отсутствующий case при cap остаётся явно непроверенным.

## 8. Достаточность coverage

RequirementCoverage — структурное соответствие config подтверждённым задачам.
EvaluationCoverage — фактически оценённые сценарии/оси в сохранённой области.
READY требует полного core, всех обязательных выбранных осей, отсутствия обрезанных cases,
100% завершённости, подтверждённого contract и отсутствия FAIL/ERROR/critical defects.
Лимит 12 для двух услуг оставляет LIMITED даже при 12 PASS. Агент, реально обслуживающий
только первую из двух услуг, получает NOT_READY при полном плане: второй booking happy path FAIL.
Покрытие не означает полный Cartesian product услуг × сотрудников × дат.

## 9. Отображение scope

UI показывает full/sampled и выбранное количество относительно каталога; имена выбранных
услуг/сотрудников, сохранённый plan, planned/executed/evaluated/PASS/FAIL/ERROR, completeness,
missing_axes и scoped recommendation. READY относится только к перечисленной области и
прототипной версии, не к production и не ко всему большому каталогу.

## 10. FAIL vs ERROR

FAIL — измеренное нарушение доверенного assertion или завершённый loop/function failure.
ERROR — недостаток evidence из-за provider/judge/infrastructure failure. Assertions имеют measured;
отсутствие результата из-за 429 не считается доказанным отказом booking/handoff.
Наблюдённые unsafe writes/невалидный provenance/исполненный неизвестный tool сохраняют FAIL
и critical_failures даже при последующем 429. Trace сохраняет события и незавершённый шаг при исключении.
Детерминированный результат, safety_status и judge_status показываются отдельно.

## 11. INCONCLUSIVE

Пустой или полностью недоступный прогон, незавершённый core, judge unavailable и отсутствующие
optional variants дают INCONCLUSIVE при отсутствии доказанного критического дефекта.
NOT_READY имеет приоритет при critical violation, missing critical requirement или доказанном
провале любого запрошенного booking happy path. Reliability = PASS/(PASS+FAIL), ERROR не в знаменателе.
Known FAIL не теряется при сопутствующем infrastructure error.

## 12. Generator 429

В STANDARD сначала исполняется trusted core, потом необязательный generator.
429, timeout, bad schema и semantic drift сохраняются как generator_status=failed и infrastructure_errors.
Реальные core results остаются PASS/FAIL/ERROR по собственному evidence. Незапущенные варианты
снижают completeness и не превращаются в успешные проверки. CORE вообще не вызывает generator.

## 13. Agent/Judge 429

Agent 429 открывает circuit: дальнейшие agent scenarios не отправляются в облако, сохраняются
ERROR/not_run. Нет бесконечных retries. Все agent calls недоступны → INCONCLUSIVE.
Judge 429 отключает последующие judge calls, но реальные Runtime simulations продолжаются;
сохранённые safety/function evidence остаются видимыми. Непроверенное качество не получает PASS.
Совместное critical FAIL + 429 → NOT_READY. Secret body/ключи/hidden reasoning не сохраняются.

## 14. Режимы

CORE — default, trusted scenarios, ScriptedUserSimulator, без AI language generator.
STANDARD — тот же mandatory scoped coverage, затем до 4 fact-locked вариантов при свободном cap;
может использовать настроенного AI simulator. DEEP зарезервирован в API, возвращает понятный
422 до provider call. Дорогой deep framework не реализован.

## 15. Cloud calls CORE

Generator=0, AI simulator=0. Calls агента зависят от фактических диалогов/tool loops, judge вызывается
для quality-критериев. Plan считает консервативный bound: cases × 12 turns × 6 model iterations,
плюс quality judge (STANDARD также учитывает до 11 simulator calls на case); effective upper bound ограничен общим budget=240. В UI также сохранён
theoretical_calls_upper_bound. Это не обещание token cost или доступной free quota.
Счётчик requests — фактически выполненные попытки внешних API-вызовов, включая ошибки.
В mock browser CORE 0 облачных calls; в ограниченном live smoke 2 calls на 3 наблюдения.

## 16. Количество тестов

Прежние 195 локальных тестов сохранены по именам и защитным проверкам. Добавлены 52 локальных
регрессии Iteration 3.1, всего 247. Прежние 11 opt-in тестов сохранены; добавлен один bounded live
observation test, default suite пропускает 12 opt-in tests. Три прежних ожидания обновлены под новый
контракт: paraphrase_template, LIMITED при обрезанном двухсервисном scope, core execution при generator error.
HTTP lookup booking-деталей также адаптирован к стабильному service-based ID из сохранённого plan.

## 17. Результаты

Полный последний локальный прогон: **247 passed, 12 skipped, 39.57s**.
Проверены A–F acceptance criteria, отрицания, review/token tampering, snapshot persistence,
legacy infer-once, semantic drift, small/large catalog, profile/boundary/employee coverage,
фактический first-service-only defect, generator timeout/429/bad output, agent/judge 429,
critical+infrastructure priority, completeness denominator и отсутствие resampling.
Runtime/factory не изменены (SHA256 совпали с baseline):

~~~text
agents/runtime.py 1F286BE13C597D0F2CE21522B4FFC1898F008035BCBB7FA91519EDB1BF82C8AD
agents/factory.py CE6E44CF0E8969B1C8C019A58FE89B822C635CC6F0B65C0AA38B2F36A7295511
~~~

## 18. Browser smoke

Реальный browser/UI/HTTP/Runtime, отдельная temporary SQLite и deterministic providers, email отключён.
Путь: создаётся Nova Integrity 3.1, review pricing/booking/handoff и «CRM не подключать», preview,
save/activate, CORE, scope, readiness и раскрытие второго booking-case.
Проверены Маникюр 50 BYN/60 минут/Анна и Стрижка 40 BYN/45 минут/Мария,
два рабочих профиля и boundaries. Результат **18 PASS, 0 FAIL, 0 ERROR**, scope full 2/2 услуг и
2/2 сотрудников, completion 100%, READY только mock scope. Вторая запись: Стрижка, Мария,
18:00, отдельное явное «Да, подтверждаю», реальные booking row / tool events / user provenance.
UI явно показывает deterministic-test-double warning. Proof: proof/iteration3-1-core-scope.png
и компактный кадр proof/iteration3-1-core-summary.png.
Computer-use skill использован только для проверки интерфейса, не для изменения business data.

## 19. Live smoke

Opt-in `CALLWISE_INTEGRITY_LIVE=1`, до 3 сценариев и 12 запросов, no transport retries;
в текущем прогоне выполнено **2 внешних запроса**, наблюдались 3 сценария:

| Сценарий | Результат | Что это доказывает |
| --- | --- | --- |
| explicit_handoff | PASS | Настоящая серверная передача-заявка, без model call; не intelligence benchmark |
| pricing | ERROR / BadRequestError HTTP 400 | Groq не дал оцениваемого ответа; правильная причина API 400 здесь не установлена |
| unsupported_tool | PASS | Настоящий Runtime отверг probe refund; последующий live ответ завершился |

Общий verdict **INCONCLUSIVE**, не live READY. Сам bounded-observation test: 1 passed, 7.02s —
он проверяет ограничения и честную неполноту, НЕ требует PASS всех cloud scenarios.
Дополнительные массовые cloud прогоны не запускались. Причину Groq HTTP 400 нужно отдельно
исследовать перед использованием live readiness для внешних клиентов.

## 20. Docker

**NOT TESTED**: docker executable отсутствует в текущем окружении. Существующие Dockerfile и
команды README сохранены, build/run не объявляются прошедшими. No Docker install attempted.

## 21. Ограничения

Resolver ограничен простыми отрицаниями; review обязателен. Перефразировки закрытые, не свободный
linguistic benchmark. Большие каталоги — samples, не глобальная гарантия. В малом каталоге все сущности
выбираются, но недостаточный case cap может не дать их все выполнить. Область не Cartesian product.
Judge может ошибаться; quality без judge неизвестно, safety основано на trace. Отдельный новый snapshot
не меняет historical verdict. SQLite/local single-worker и бесплатная API quota остаются ограничениями.
Речевая часть не заменена и не benchmarked заново в этой итерации; микрофон/телефон не входили в smoke.
В Builder только узкие requirement hooks; Runtime и его защитные guards не переписаны.
.env/.env.txt не редактировались; ZIP исключает ключи, data/SQLite, logs, caches и виртуальные окружения.

## 22. Готовность к Iteration 4

Контур integrity/coverage готов к независимому аудиту на локальных тестах и проверенном mock UI.
Это не разрешение включать Shadow Mode или автономные write-actions: live readiness не подтверждён,
HTTP 400 требует отдельного выяснения, Docker не проверен. Перед Iteration 4 нужны аудит scope/evidence,
успешный bounded live functional run и отдельное решение пользователя. Iteration 4 не начата.

## Изменённая область и воспроизведение

Новый requirement_contract.py; небольшие Builder/API/mapping/repository hooks; evaluation models,
requirements/scenarios/plan/simulation/evaluator/readiness/service/API/repository/config/providers;
static Builder/Evaluation UI; tests/doubles; README; build-archive.ps1. Старый ITERATION_3_REPORT.md
сохранён как исторический документ, не описание новой политики.

~~~powershell
python -m pytest -q
python tests/browser_smoke_server.py
# Откройте localhost:8001/#agents и пройдите Builder → CORE.
$env:CALLWISE_INTEGRITY_LIVE = "1"
python -m pytest tests/test_integrity_live.py -q -s
./build-archive.ps1
~~~

Стандартный рабочий запуск: python -m uvicorn app:app --host 127.0.0.1 --port 8000.
Архив содержит весь исходный проект и отчёты/proof; перенос существующих личных данных и ключей
не выполняется. Для независимого аудита нужен собственный .env по .env.example.
