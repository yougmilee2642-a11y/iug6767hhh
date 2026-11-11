# Callwise — Iteration 2 / Agent Builder

Дата проверки: 27 сентября 2026. Изменения внесены в существующий autofix-receptionist.
Исторический beauty demo и пользовательские .env/данные сохранены. Новое приложение не создавалось.

## 1. Что реализовано

Отдельный Builder, ограничения промежуточного черновика, доверенные шаблоны, human preview,
SQLite-хранилище агентов, раздельные API генерации/проверки/сохранения/активации, selector и русский wizard.
Путь Nova Beauty проходит без ручного редактирования AgentConfig. agents/runtime.py не изменён.

## 2. BusinessInput

Обычные понятия бизнеса: название, сфера, описание, город, сайт-метаданные, timezone, недельные часы,
услуги с ценой/валютой/длительностью/сотрудниками, роль, задачи, заметки, предпочтения эскалации.
Проверяются типы/границы, timezone, интервалы и неизвестные ключи. Пользователь не вводит JSON в новом UI.
Сайт не загружается; все сотрудники формы доступны каждой услуге. API допускает отдельный список на услугу.

## 3. BuilderDraft

Отдельная Pydantic-модель, не AgentConfig: имя/роль/summary, сценарии, инструменты, дополнительные поля,
тип поля, вопрос/label/required/варианты choice, ограниченный стиль, причины эскалации и неподдерживаемые задачи.
Нет regex, capabilities, SQL, source types, JSON paths, реализаций tools или provider-native конфигурации.

## 4. Provider

Минимальный BuilderProvider contract отделён от диалогового LLMProvider. Реализация — Groq JSON Schema
с strict=true, default openai/gpt-oss-20b; модель задаётся BUILDER_MODEL. Для gpt-oss reasoning_effort=low.
Результат проходит Pydantic и semantic validator. Markdown не парсится.
Документация проверена по [Structured Outputs](https://console.groq.com/docs/structured-outputs)
и [OpenAI Compatibility](https://console.groq.com/docs/openai).

## 5. Преобразование в AgentConfig

builder/mapping.py нормализует пользовательский каталог, вычисляет ID, берёт сценарии из Scenario Catalog,
tools/capabilities/confirmation из Registry, поля/evidence из presets и принудительную handoff policy.
Knowledge создаётся из BusinessInput, не из придуманных моделью цен, часов или сотрудников.
Допустимы максимум исходная генерация и один repair после невалидного draft/config. Provider failure останавливает процесс.

## 6. Field presets

person_name, phone, email, free_text, number, address, choice. Sources, normalization, evidence strategy,
requires_confirmation и validation — серверные. Booking автоматически получает core fields;
имя/телефон требуют user evidence, услуга/время/сотрудник — результат check_slots.
Дополнительные вопросы работают через прежний generic collection/provenance механизм.

## 7. Граница regex/code

Неизвестные поля draft запрещены. Выход модели считается недоверенным. Все выражения — константы
серверных presets либо безопасно экранированные варианты choice. Текстовые вопросы/названия — данные,
не исполняемые инструкции. Нет eval/exec, generated imports, SQL, Python, migration или tool implementation.
Неизвестный tool не создаётся автоматически. Review digest не заменяет авторизацию: это локальный prototype.

## 8. Stable IDs

Сервер использует NFKC, casefold, нормализацию пробелов и SHA-256 prefix, а не идентификатор модели.
IDs lowercase и deterministic; employee ID включает namespace бизнеса. Новые tool schemas принимают enum ID.
В confirmation, tool reply и карточках показываются display names; данные/provenance сохраняют ID.
Дубликаты названий объединяются с warning при одинаковых данных, конфликтующие услуги отвергаются.
Validator дополнительно проверяет уникальность ID и employee references. Переименование при новой генерации меняет ID.

## 9. Human handoff invariant

Mapper всегда устанавливает immediate для human_handoff. Semantic validator отвергает disabled при этой capability.
«Я не хочу разговаривать с ботом. Дайте человека.» обрабатывается старым Runtime до обращения к LLM.
Причины инициативы AI закрыты: complaint, unsupported_scenario, tool_failure; последняя требует фактических повторных ошибок.
Это сохранение запроса и контекста, не реальное телефонное соединение.

## 10. Хранение

В существующую SQLite добавляются agents и builder_candidates. Candidate сохраняет BusinessInput, validation,
preview, результат, число попыток и review digest. Невалидный candidate не становится агентом.
После review agents содержит полный сериализуемый AgentConfig, source=builder, timestamps и status=valid.
Исходный beauty JSON не переписывается; legacy demo синхронизируется только с отдельной source=demo записью.
Повторное сохранение одного candidate idempotent. Новые диалоги хранят snapshot выбранного config.

## 11. Activation

POST agents сохраняет только прошедший проверку candidate с совпадающим digest preview.
Отдельный POST activate повторно проверяет сохранённый config и устанавливает active.
UI вызывает эти операции только после кнопки «Создать и активировать агента». Генерация не активирует агента.
Неактивный или невалидный config не допускается к новому разговору. Несколько агентов могут быть active одновременно.

## 12. Интеграция Runtime

AgentService.resolve загружает выбранный saved config; AgentFactory проверяет его и разрешает tools через Registry.
Дальше работает прежний AgentRuntime, прежние /chat, /transcribe, /speech, confirmation и история.
Builder не знает Runtime internals, Runtime не импортирует Builder. Код агента не генерируется.
При смене selector нужно завершить текущий разговор. Выбранный ID запоминается в браузере.

## 13. Количество тестов

В коллекции 134 теста: 130 локальных и 4 opt-in реальных сценария Groq/TTS.
Все прежние 88 сохранены; добавлено 46 (44 локальных, 2 внешних).
У двух arbitrary-tool fixtures убраны унаследованные booking/handoff capabilities, отсутствующие у их адаптеров;
сами проверки не удалялись и assertions не ослаблялись.

## 14. Результаты

Финальный локальный запуск: 130 passed, 4 skipped. Пропуски — отключённые по умолчанию внешние тесты.
JavaScript syntax checks и Python compileall проходят.
Реальный Builder Nova Beauty: valid с первой попытки; save/activate, старый Runtime, check_slots,
server confirmation, persisted booking/conversation и immediate handoff прошли отдельный запуск.
Реальные legacy booking/handoff и TTS→STT также прошли. Generated-agent TTS→STT прошёл после исправления STT hint.
Не заявляется зелёный непрерывный общий live-прогон: при повторных облачных запросах возникал RateLimitError.
Квота не обходилась; такие сбои теперь показывают понятную ошибку и сохраняют данные.
[Groq rate limits](https://console.groq.com/docs/rate-limits) применяются к организации; точные значения зависят от аккаунта.

## 15. Browser smoke

Пройден вручную через browser computer-use на изолированном localhost:8001:
обычная форма Nova Beauty → часы → роль/задачи → две услуги и сотрудники → validation/preview
→ явная Create → active в списке → selector → обычный текстовый разговор → check_slots
→ имя/телефон → confirmation → create_booking → сохранённая история.
Второй разговор с явным запросом человека завершился немедленно. Проверено восстановление формы после reload.
Использованы MockBuilder/MockRuntime и временная SQLite; SMTP отключён. Это UI smoke, не второй live-Groq прогон.
Проверка выявила и помогла исправить подписи предупреждений/причин эскалации.
Скриншот с синтетическим клиентом: [ITERATION_2_BROWSER_SMOKE.png](ITERATION_2_BROWSER_SMOKE.png).

## 16. Voice status

Новые агенты используют тот же микрофон/STT/LLM/TTS путь, не отдельный чат.
Реальный generated-agent тест синтезирует русскую фразу через существующий Edge TTS и отправляет MP3
в Groq STT с interaction_id созданного агента; ответ распознан, правильный agent snapshot подтверждён.
Во время этой проверки обнаружен Groq 400 при передаче большого hint с полным каталогом/IDs.
Hint заменён на display names и последний вопрос, консервативно ограничен 224 UTF-8 байтами.
После этого реальный тест прошёл. [Groq STT](https://console.groq.com/docs/speech-to-text) ограничивает prompt 224 токенами.
Физический микрофон пользователя, его уровень шума и browser permissions в этой итерации не проверялись.
Silence detector 1050 мс и отсутствие восьмисекундного таймера сохранены.

## 17. Docker status

Dockerfile обновлён: добавлен COPY builder; новые provider/service/static модули попадают в образ существующими COPY.
Команда Docker в текущем окружении не найдена, поэтому build/run контейнера НЕ проверены. Это не считается успешным Docker smoke.
Секреты и существующая data не включаются в образ. Новые тяжёлые библиотеки не добавлялись.

## 18. Что осталось mock

Календарь — локальный тестовый BookingService с реальными SQLite-записями и проверкой пересечений.
Внешний календарь/салон/телефон не подключены. Handoff — persisted request, не соединение.
В browser smoke модель заменена детерминированным ответом; облачный Builder и Runtime проверены отдельно.
Реальная отправка SMTP не выполнялась. Legacy demo email остаётся рабочим прежним путём;
generated-agent email пока отключён, чтобы данные нового бизнеса не ушли на старый BUSINESS_EMAIL.

## 19. Известные ограничения

Русский demo, ограниченный Scenario Catalog, фиксированные тестовые slot_times, отсутствие редактора/удаления
созданных агентов и внешних интеграций. UI — одно окно в день; API — несколько. Воскресенье Nova закрыто,
суббота заканчивается в 18:00: после закрытия booking должен быть отказан, не придуман.
Качество выбора вопросов/порядка инструментов может меняться у LLM: validator не оценивает качество диалога.
Free Groq quota ограничивает частоту live-прогонов; не обещается отсутствие задержек или безлимитность.
Нет auth, billing, multi-tenant isolation, production deployment, phone/SIP, CRM, refunds, scraping/RAG.
Unsupported требования видны в preview и не создают fake tools. Credentials остаются только в .env на сервере.

## 20. Готовность к Iteration 3

Основа готова: обычный BusinessInput превращается в валидный сохранённый config, исполняемый старым Runtime.
Это подтверждает техническую исполнимость, не production readiness и не качество всех возможных разговоров.
Следующий отдельный этап — Scenario Generator, Simulation, Evaluation, Readiness; сейчас они не реализованы.
