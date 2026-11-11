# Callwise — Iteration 2.1 / Builder Hardening

Проверено 27 сентября 2026. Точечные изменения в существующем проекте после Iteration 2.
AgentRuntime и AgentFactory не изменялись. Iteration 3, телефония и новые интеграции не реализованы.
Пользовательские .env, данные и исходное demo не удалены и не переписаны.

## 1. Где был administrator hardcode

builder/mapping.py создавал Role(id="administrator"), фиксированное описание «Администратор…»
и greeting «Я AI-администратор…», независимо от draft.role_name. Все три места исправлены.
Существующий legacy beauty demo остаётся администратором, как и раньше. Надпись пустого диалога
теперь использует выбранную generated роль, а не identity legacy demo.

## 2. Генерация role.id

Сервер вызывает stable_id(draft.role_name, "role"): NFKC, casefold, нормализация пробелов/ё,
опциональный ASCII фрагмент и 12 hex символов SHA-256. ID lowercase и deterministic;
LLM не может передать технический role_id. Для «Менеджер по продажам» получается role_db712e914895.
role.name и description называют ту же роль. Dynamic role не добавляет недоступные capabilities.

## 3. Greeting

Нейтральная безопасная формулировка: «Здравствуйте! Я виртуальный сотрудник Nova Beauty.
Моя роль — Менеджер по продажам. Чем могу помочь?» Не используется автоматическое склонение
или угадывание должности. Имя роли берётся из проверенного BuilderDraft.role_name.
Уже сохранённые role/greeting не мигрируются автоматически; для новой identity нужен новый агент.

## 4. Генерация mock slots

Новые generated configs содержат availability_mode=schedule_30m вместо фиксированного slot_times.
services/business_hours.py: potential_clocks строит старты по окнам запрашиваемого дня недели,
начиная с открытия и затем через 30 минут. Например 16:00–17:00 / 30 минут → 16:00, 16:30.
08:00–17:00 не зависит от старого массива 10:00/12:00/15:00/18:30/19:30.
Старые generated catalogs с service IDs также переходят на расчёт из schedule без перезаписи БД.
Legacy display-name demo сохраняет явно настроенный slot_times и occupied_times.

## 5. Duration

Последний старт ограничен closing - duration_minutes, услуга должна целиком поместиться в одном окне.
60 минут при закрытии в 17:00 → 16:00, но не 16:30. Несколько окон API обрабатываются отдельно;
начало не обязано совпадать с :00/:30 — окно 09:10 начинается с 09:10. End=24:00 поддерживается.
Runtime фильтрует прошлые моменты, неоднозначные/несуществующие DST моменты и повторно проверяет within_hours.

## 6. Existing bookings

Сохранена repository.for_date и фильтрация пересечений по employee ID и длительности.
Занятость одного сотрудника не блокирует другого. Старты другого дня не блокируются.
Перед подтверждённым сохранением validate_proposal повторно вызывает check_slots, а SQLite repository
в транзакции BEGIN IMMEDIATE отвергает пересечения и сохраняет прежнюю idempotency по interaction_id.
Booking не создаётся до серверного подтверждения.

## 7. Booking readiness

Выбран validation error, не warning. validate_booking_dependencies проверяет для каждой услуги
хотя бы один потенциальный старт во всех семи днях через тот же potential_clocks.
120 минут при всех окнах 16:00–17:00 или закрытая неделя дают понятную ошибку с названием услуги.
Она появляется в preview до save/activate. Это проверка длительности относительно рабочих окон,
не production readiness score, не проверка свободного места сегодня и не оценка диалога.

## 8. Employee catalog

BusinessInput.employees — единственный source of truth. ServiceInput.employees — subset ссылок
по display name, пустой список означает весь общий каталог. Услуги не создают implicit employees.
NFKC/casefold/пробелы/ё объединяют «Анна», «анна», « Анна » в одну entity с warning.
Неизвестный сотрудник даёт ошибку: услуга + имя + отсутствие в каталоге. Контракт описан в моделях и README.
UI сначала показывает общий каталог, затем чекбоксы сотрудников каждой услуги. Ссылки сохраняются при reload.
Если выбранного сотрудника удалили из каталога, ссылка остаётся видимой как отсутствующая и требует исправления.

## 9. Service references

Generated knowledge.services[].employees хранит stable employee IDs. Display names остаются в
knowledge.employees[{id,name}], отображаются в tool replies, confirmation, карточках и STT подсказке.
В browser acceptance Консультация ссылается только на ID Анны; Стрижка — только на ID Марии.
Это дополнительно проверено чтением сохранённого AgentConfig через API. Tool schemas используют ID enum.

## 10. Один ToolRegistry

AgentBuilder выбирает переданный registry, либо registry provider, либо один default для pipeline.
GroqBuilderProvider.bind_registry получает тот же instance; generate не создаёт новый default.
strict_schema(registry), advertised catalog/capabilities, mapping и validation используют этот источник.
Сценарии с отсутствующими required tools не рекламируются. Системный prompt больше не перечисляет
отсутствующие booking tools вне переданного каталога. Custom registry проверен с отдельной capability.
Только зарегистрированные tools, разрешённые доверенным Scenario Catalog, доступны Builder.
Standalone provider/schema без registry сохраняют default для совместимости. Provider abstraction остаётся
отдельной от Runtime; простой mock без catalog/schema может реализовать только generate.

## 11. Количество тестов

154 теста в коллекции: прежние 134 сохранены, добавлены 19 локальных hardening checks и 1 opt-in live check.
Локально исполняются 149; 5 внешних по умолчанию пропущены.
Новые категории: две роли, нормализованный server role ID, короткое/раннее расписание, duration,
SQLite occupancy/разные сотрудники, невозможная и закрытая неделя, несколько окон/24:00,
совместимость старого generated catalog, subsets/unknown/deduplicated employees и shared/custom/missing registry.
Существующие tests/test_builder.py, test_runtime.py и test_hardening.py не изменялись и не удалялись.

## 12. Результаты

Полный локальный прогон: 149 passed, 5 skipped (9.80 s на финальном полном прогоне перед упаковкой).
node --check static/app.js и static/builder.js, Python compileall проходят.
Прежние lifecycle/save/activate/selector API, generated Nova, Runtime booking, confirmation,
provenance и explicit human handoff входят в зелёный regression suite.
19 новых локальных тестов отдельно: 19 passed. Проверки не обходят semantic validator.

## 13. Browser smoke

Изолированный localhost:8001, временная SQLite, deterministic RoleAwareSmokeBuilder/SmokeProvider,
отправка SMTP отключена. Полная обычная форма без редактирования Python между бизнесами:
Nova Beauty / Менеджер по продажам / 16:00–17:00 / Консультация 30 минут (Анна), Стрижка 45 минут (Мария)
→ preview → save/activate → selector → существующий Runtime → check_slots → 16:30
→ synthetic имя/телефон → server confirmation → completed и сохранённая запись.
Новый разговор с явным запросом человека завершился escalated. Role и subset чекбоксы восстановились после reload.
Computer-use проверка также выявила надпись legacy администратора в пустом generated диалоге; она исправлена.
Для запроса «сегодня в 16:30» только тестовый календарь использует today 09:00: реальное время уже позднее.
Рабочий сервер и live tests не имеют этой подмены: прошедший слот не предлагается.
Скриншоты: [запись 16:30](ITERATION_2_1_BROWSER_SMOKE.png), [роль и human handoff](ITERATION_2_1_ROLE_SMOKE.png).

## 14. Live provider status

Реально выполнены отдельно, на временной SQLite, с отключённым SMTP:

- Sales-role Builder + короткие часы + real Groq Runtime/check_slots → passed (6.25 s), draft valid с первой попытки.
- Прежний real Builder Nova + Runtime booking/confirmation/persistence/handoff → passed (33.66 s), draft attempt 1.
- Generated-agent Edge TTS → Groq STT → passed (5.22 s).
- Legacy Edge TTS → Groq STT → passed в дополнительном прогоне.

Дополнительный real legacy booking/handoff прогон получил 429 RateLimitError после двух ответов;
вместе с legacy voice результат был 1 failed / 1 passed. Полностью зелёный непрерывный live suite НЕ заявляется.
Квота не обходилась и тест не удалялся. Пользователь получает существующую понятную 429 ошибку с сохранением данных.
Физический микрофон не проверялся. Browser smoke использует mock LLM; live Groq проверен отдельно.

## 15. Docker status

Docker command не найден в окружении. Build/run контейнера не проверены; это не считается успешным Docker smoke.
Новых директорий runtime или тяжёлых зависимостей нет; существующий Dockerfile уже включает builder,
providers/services/static. Секреты и пользовательская data исключены из образа и ZIP.

## 16. Ограничения и handoff

Это локальный prototype, не production calendar: нет праздников, индивидуальных смен, capacity, CRM,
auth, tenant isolation, billing, телефонии, RAG, simulation/evaluation/readiness. Динамическое имя роли
не означает реализацию автоматических продаж/возвратов/оплат. UI поддерживает одно окно в день,
API — несколько; шаг 30 минут задан сервером. Старые role/greeting автоматически не меняются.
Generated-agent email остаётся отключённым, чтобы не отправить данные на адрес legacy бизнеса.
Облачная скорость/квота не гарантируются. Изменение имён сущностей при новой генерации меняет stable IDs.
Runtime/Factory сохранены, новая продуктовая итерация не начата.

ZIP содержит полный исходный проект, тесты, .env.example, README, отчёты и скриншоты.
Не содержит .env/.env.txt, пользовательскую SQLite, логи, кэши, venv или старые ZIP.
Для запуска распакованной копии нужен собственный .env по README; рабочий оригинал сохраняет свои настройки/данные.
