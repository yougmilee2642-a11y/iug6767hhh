# Callwise — Iteration 1.1 / Runtime Hardening

Дата проверки: 27 сентября 2026. Изменён существующий проект, не создано новое приложение.

## 1. Что изменено

Добавлены schema-driven provenance, field collection bindings, универсальное подтверждение,
ToolRegistry, semantic validation, IANA timezone/рабочие окна, раздельные escalation policies,
нейтральный контракт сообщений и generic UI. Сохранены FastAPI, Groq, STT/TTS, SQLite и SMTP.

## 2. Закрытые проблемы

- `additional_fields` не становятся фактами только потому, что переданы LLM.
- Имя мастера не доказывает имя клиента; substring check удалён из booking service.
- Подтверждение включает динамические данные, цену/валюту/длительность, а не фиксированный список полей.
- Write action связан с последним показанным предложением и отдельным однозначным согласием.
- Конфигурация не может отключить обязательное подтверждение write tool.
- Неизвестные tools, неправильный escalation tool, зависимости, sources, ссылки, timezone/часы отклоняются до диалога.
- Runtime и app.py не выбирают отраслевые инструменты по названию; это делает registry/factory.
- Время бизнеса и закрытие в 21:00 больше не зашиты в Python.
- Явная просьба о человеке немедленно прерывает сценарий, включая ожидание подтверждения.
- Runtime не хранит Groq/OpenAI-native tool-call JSON.
- Карточка завершённого действия показывает сохранённый action_result; история использует подписи из снимка конфигурации.

## 3. Созданные файлы

`agents/fields.py`, `agents/validation.py`, `agents/factory.py`, `tools/registry.py`,
`services/business_hours.py`, `services/notifications.py`, `tests/test_hardening.py`,
`tests/browser_smoke_server.py`, этот отчёт.

## 4. Изменённые файлы

`app.py`, `storage.py`, `prompts.py`, `agents/models.py`, `agents/runtime.py`, `agents/prompts.py`,
`providers/base.py`, `providers/groq.py`, `providers/language.py`, `tools/base.py`, `tools/booking.py`,
`tools/handoff.py`, `services/booking_service.py`, `configs/beauty_salon.json`, `static/app.js`,
`static/index.html`, `requirements.txt`, `README.md`, `tests/test_runtime.py`, `tests/test_live.py`.

Секретные .env не изменялись. Старые таблицы/заявки не удалялись. Redesign не проводился.

## 5. Field provenance

`collected_fields[field_id]` содержит value, source, evidence, confirmed. Поле описывает data_kind,
allowed_sources, required, requires_confirmation, normalization, value_pattern и evidence mapping.

User value принимается из явной декларации с именованной группой value, формы `Label: value`
или ответа на конкретный серверный question. Сначала разбирается декларация, затем буквальный ответ:
«Меня зовут Алексей» после вопроса об имени не приводит к повторному запросу имени.
Evidence привязан к индексу пользовательской реплики и перепроверяется по серверному transcript.
Сообщения ассистента и подставленный моделью provenance не служат доказательством.

Business values сверяются с результатами tool по разрешённому result_schema path либо с business knowledge.
Для пользовательских полей источники tool/business запрещены; trusted write contract дополнительно защищает
пользовательские параметры действия. Цена/длительность вычисляются доверенным booking adapter из каталога,
а не из предложенной моделью цены. `action_provenance` описывает все значения предложения, включая системные.

Если поле неизвестно, сервер задаёт вопрос; booking ещё не создаётся. Перед выполнением проверяются digest
предложения, последняя реплика ассистента и следующая однозначная реплика согласия. Флаг confirmed в вызове
не разрешает действие. Неоднозначное согласие отменяет старое предложение. Проверенные значения и evidence
сохраняются в JSON, без колонок на каждое новое поле.

Источники system/derived предусмотрены логической моделью, но произвольные вычислители не добавлены:
обязательное поле без доверенного producer отклоняется validator, а не принимается от LLM.

## 6. ToolRegistry

Registry хранит доверенные factories и metadata: capabilities, dependencies, read_only,
requires_confirmation, risk_level, kind. `resolve_for_agent` возвращает только разрешённые реализации.
Default registry подключает check_slots/create_booking/transfer_to_human. Для другого business tool
нужна регистрация доверенной Python-реализации, не ветка в AgentRuntime или app.py.
Read-only tool выполняется без согласия. Write tool требует prepare + согласие независимо от своего имени.
Escalation tool проверяет отдельную policy. Это не plugin/DI framework.

## 7. Semantic validation

Результат: `{valid, errors:[{path,code,message}], warnings:[...]}`. Pydantic отвечает за структуру и
уникальные IDs; validator — за существующие tools, runnable factories, capabilities/dependencies,
action field contracts, безопасные источники, result/knowledge paths, regex shape, IANA timezone,
рабочие часы, поддерживаемый язык и объявленные зависимости роли/сценариев.

Booking dependency проверяет каталог, длительность/цену, slot_times и доступность мигрированной SQLite.
Проверка вызывается load_agent и factory/runtime. Невалидный агент не начинает conversation (HTTP 422).
`POST /api/agent/validate` возвращает отчёт без сохранения кандидата. Это endpoint валидации, не Builder.
Свободный текст роли/сценариев не может автоматически доказать семантическую совместимость: это явно
отмечается warnings; проверяемые зависимости нужно задавать required_tools/fields/capabilities.

## 8. Timezone/opening hours

Timezone находится в `business.timezone`, demo — Europe/Minsk; в Python используется ZoneInfo/tzdata.
Рабочие окна находятся в `business.schedule`: weekday 0–6, списки start/end.
Существующая форма хранит timezone/opening_hours; ежедневные часы, 24/7 либо JSON переводятся в schedule.
Отображаемые часы и schedule должны согласовываться. Услуга целиком должна помещаться в рабочее окно.
Окна 08:00–17:00 и 24/7 проверены без изменения Python. Europe/Warsaw летом возвращает +02:00.
Неоднозначное/несуществующее местное время при DST не предлагается автоматически.

## 9. Escalation policy

`explicit_human_request: immediate/disabled`; `agent_initiated: {reason_type: allowed/disabled}`.
«оператор», «человек», просьба соединить с сотрудником и отказ говорить с ботом в demo немедленно
создают explicit_user_request без вызова LLM и дополнительных обязательных вопросов.
Отрицание «не нужен оператор» не создаёт handoff. Выбор мастера также не создаёт handoff.

Agent-initiated unsupported_scenario/tool_failure разрешены в demo; tool_failure требует двух реальных
ошибок инструментов. Прочие reason_type отклоняются, если явно не разрешены policy. Confidence engine отсутствует.
Сохраняются reason/type, agent_id, серверное summary, known fields/provenance, transcript и timestamp.
UI честно сообщает о зафиксированном запросе, не о соединении с оператором.

## 10. Provider neutrality

Контракт: ConversationMessage, ToolCall, ModelReply, ToolSpec. JSON состояния сериализует эти нейтральные
объекты; runtime не импортирует Groq client/native message classes. Преобразование в role/content/function/
tool_calls/tool_call_id происходит в GroqProvider. MockLLMProvider использует тот же контракт.
Новый provider должен реализовать complete; runtime менять не нужно. LangChain/LiteLLM не добавлены.

## 11. Количество тестов

88 тестовых случаев: 86 локальных + 2 opt-in live. Все исходные 40 локальных случаев сохранены;
добавлено 46 случаев (с учётом parametrization). Старые fixture/ожидания адаптированы к строгому evidence
и neutral messages; проверки не удалялись. Live booking допускает дополнительный выбор уже проверенного
слота при вариативном порядке вопросов модели, но запрещает подготовку до реального предоставления телефона.

## 12. Проверки и результаты

- Локальные тесты: PASS, 86 passed; live без явного opt-in пропускаются.
- Реальный Groq booking + отдельное подтверждение + handoff: PASS.
- Реальная русская Edge-озвучка → MP3 → Groq STT: PASS.
- Полный финальный прогон с CALLWISE_LIVE_TESTS=1: **PASS, 88 passed in 79.63s**.
- node --check static/app.js и Python compileall: PASS.
- Реальный перезапуск localhost:8000, GET /: HTTP 200; /api/health: ok; semantic validation текущего агента: valid.
- Browser smoke: PASS — реальный UI/HTTP, MockLLMProvider, отдельная временная SQLite, email выключен.
  Проверены слот, отказ от выдуманной allergy, её отдельный сбор, полное подтверждение, фактическая запись,
  автоматическое завершение, карточка результата и раскрытая история.
- SMTP code: PASS с FakeSMTP (TLS/login/send_message, dynamic label); ошибка email не теряет обращение.
  Реальная отправка письма в этой итерации: NOT TESTED, чтобы не отправлять тестовые обращения бизнесу.
- Browser physical microphone / слышимость динамика / тишина живой речи: NOT TESTED.
  Кнопка запуска проверена, но capture во встроенном браузере не начался; разрешение/устройство не были
  подтверждены автоматизацией. Не выдаём TTS→STT тест за проверку физического микрофона.

Снимок изолированной browser-проверки: [data/hardening-browser.png](data/hardening-browser.png).

## 13. Docker status

**NOT TESTED — Docker недоступен.** Выполнена попытка `docker build -t callwise-runtime-hardening .`;
PowerShell сообщил, что команда docker не установлена/не найдена. Образ не собран и контейнер не запускался.
Dockerfile включает новые modules/configs через существующие COPY директорий; зависимости добавлены
в requirements.txt. Это статическая проверка состава, не доказательство Docker build PASS.

## 14. Что осталось mock

Каталог, мастера, начальная доступность/список времён — тестовые; booking реально сохраняется в локальной SQLite,
но внешний production calendar не подключён. Handoff — запись запроса, не SIP transfer. MockLLMProvider используется
только в тестах/browser smoke; основной сервер работает с Groq. SMTP реальный код, но автоматическая проверка mocked.

## 15. Ограничения

- Только ru для текущих speech/consent adapters; другие языки отклоняются semantic validation.
- Свободные формулировки без schema evidence могут потребовать дополнительного вопроса.
- Валидатор проверяет контракты, не доказывает смысл произвольного текста роли/сценария или regex.
  Evidence patterns должны проверяться при проектировании конфигурации; полная security sandbox для недоверенных
  regex не реализована. Builder должен ограничивать шаблоны/источники, а не выдавать произвольному JSON полномочия.
- Системные producers из произвольного generated config не исполняются; code execution не предусмотрен.
- Один процесс/бизнес, SQLite, общий тестовый календарь, нет multi-tenant изоляции и production calendar/DST disambiguation UI.
- Рабочие окна не пересекаются и не переходят через полночь; для ночного режима нужны два окна в соседних днях.
- Модель может ошибиться в порядке вопросов или выдать невалидный tool call; такой вызов не разрешает write.
  Провайдерские ошибки/лимиты могут дать HTTP 502/503; данные разговора сохраняются. Непрерывная доступность не обещается.
- История без auth: запускать локально, не публиковать кабинет в интернет. Контекст не сжимается;
  request_id защищает повтор последнего успешного запроса, не заменяет полноценный distributed transaction ledger.
- Старые незавершённые v1 conversations не возобновляются без provenance: нужен новый разговор. Архив сохранён.
- Сетевые Groq/Edge/SMTP, физический микрофон и Docker имеют отдельно указанные ограничения проверки.

## 16. Готовность к Agent Builder

Да, для следующей контролируемой итерации Business Input → generated AgentConfig → Semantic Validator → Runtime:
валидация отделена, неизвестные tools/плохие timezone/контракты отклоняются до запуска, а выдуманные LLM user values
не принимаются как факты. Сам Builder, generator, evaluation/readiness engine, телефония, auth и billing не добавлены.

Это не готовый автономный production Builder: генерация должна использовать ограниченные проверенные contracts,
а предупреждения о свободном тексте/regex требуют review. Универсальность не означает доказанное понимание любой
отрасли или безопасность любой сгенерированной инструкции.
