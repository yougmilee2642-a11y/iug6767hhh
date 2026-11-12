# Callwise — рабочее место владельца / трек 1

Локальное распознавание обновлено на T-one + GigaAM v3 с фильтром основного голоса.
Установка, проверка и ограничения описаны в [docs/LOCAL_ASR.md](docs/LOCAL_ASR.md).

## CallWise Meetings (хакатон: встречи, документы, поручения)

Защищённый локальный помощник для встреч: документы → подготовка → расшифровка → проверяемый протокол → подтверждённые поручения → контроль. Запуск, демо-сценарий, проверки и ограничения — в [MEETINGS.md](MEETINGS.md). Страница: http://127.0.0.1:8000/meetings.

## Трек 3 за 15 минут — текстовый прототип Фотопринт v2

Python 3.12, Git; PowerShell из корня. Цель 15 минут относится к текстовой
установке с доступным индексом пакетов, без скачивания моделей. Проверяемое
время и ограничения кэша — [отчёт установки](docs/track3-release/TEST_REPORT.md).

```powershell
py -3.12 -m venv .venv-track3
.venv-track3\Scripts\python -m pip install -r requirements-track3-runtime.txt
.venv-track3\Scripts\python -m pip check
$env:MEETINGS_DB_PATH = Join-Path $env:TEMP 'fotoprint-v2-demo\meetings.db'
$env:MEETINGS_DEMO = '1'
$env:CALLWISE_LOCAL_ONLY = 'true'
$env:TELEGRAM_ENABLED = 'false'
$env:CALLWISE_CLOUD_INTEGRATIONS_ENABLED = 'false'
.venv-track3\Scripts\python scripts\seed_meetings_demo.py
.venv-track3\Scripts\python scripts\track3\start.py --db $env:MEETINGS_DB_PATH --port 8000
```

Открыть `http://127.0.0.1:8000/meetings`; остановка — Ctrl+C. Повторный запуск
сохраняет БД и сессии. Все данные вымышленные; пароль каждой роли `<login>-demo`.

| Логин | Уровень | Отдел |
|---|---|---|
| director | Директор | Дирекция |
| prod_head | Руководитель | Производство |
| sup_head | Руководитель | Поддержка |
| log_head | Руководитель | Логистика |
| fin_head | Руководитель | Финансы |
| hr_head | Руководитель | HR |
| mod_lead | Старший сотрудник | Модерация |
| operator | Сотрудник | Производство |
| sup_agent | Сотрудник | Поддержка |
| designer | Подрядчик | Маркетинг |
| admin | Администратор, без бизнес-содержимого | ИТ |
| auditor | Аудитор, только журнал | Дирекция |

Без моделей доступны документы, версии с preview/confirm, сравнение и дословные
выдержки, дневной брифинг, роли, ручная работа с протоколом, подтверждение
поручений/решений, KPI и mock CRM/календарь. Подготовка, AI-протокол и
содержательный QA требуют модели; при её отсутствии — честный 503 `model_*`,
данные сохраняются. Live Ollama/ASR/TTS/микрофон в v2 агентом не проверялись.
CRM и приглашения локальные, внешней доставки нет. Единый чат, аналитика звонков,
расширенное хранение и часть P1/P2 ещё не реализованы. Дневной брифинг доступен
кнопкой в шапке; [состав и границы](docs/track3-release/BRIEFING.md). Интерфейс загружает шрифты
из Google Fonts; remote gateway обрабатывает текст на машине хоста.

«Знания» → «Документы · версии и источники»: загрузка редакции через
preview/confirm, история, выдержки со ссылками, сравнение, предупреждения об
устаревании. Поиск/QA используют актуальные доступные версии; можно включить
историю. «Кратко» работает без модели и показывает точные выдержки, а не полный
смысловой пересказ. [Правила и ограничения документов](docs/track3-release/DOCUMENTS.md).

[Подробный запуск и проверки](docs/track3-release/V2_QUICKSTART.md) ·
[самоаудит](docs/track3-release/SELF_AUDIT.md) ·
[API](docs/track3-release/API.md) · [документы](docs/track3-release/DOCUMENTS.md) · [демо](docs/track3-release/DEMO.md).
Старые инструкции других треков ниже не заменяют этот изолированный запуск.

## Полировка 14 октября 2026

Кнопка «Проверка сценариев» доступна в карточках короткого мастера и в прежнем
списке Builder. В local-only используется основная Ollama, без Groq-fallback.
Сохранение callback проверяется по строке временной БД, конкретному событию,
пользовательским доказательствам и явному согласию. Оценка текста той же моделью
отмечается как предварительная и отделена от проверок кодом; она не даёт READY.
Недоступный провайдер блокирует запуск с объяснением. GET /api/evaluation/options
возвращает фактический провайдер и доступность.

Инструмент STT: см. VOICE_BENCHMARK.md. Рабочие базы, env и веса не входят в исходный
архив. Полный разбор текущих исправлений: PROMO_POLISH_REPORT.md; отчёт коллеги
POLISH_PROGRESS.md является историческим описанием его исходного пакета.


Текущий интерфейс: **Обзор → Помощники → Знания → Проверка → Обращения → Каналы**.
Короткий мастер: компания и роль → приветствие → FAQ → границы → серверная проверка и подтверждение.
Секретарь собирает обращение с согласием клиента; справочный помощник отвечает без обязательных контактов.
Черновик сохраняется отдельно от бизнес-базы, с защитой от изменений в другой вкладке.
Из истории вопрос переносится только в черновик FAQ: ответ вводит и подтверждает владелец.
Обработка диалога остаётся в существующем AgentRuntime, проверки инструментов и согласия сохранены.
Полная структура и границы: [PRODUCT_STRUCTURE.md](PRODUCT_STRUCTURE.md).

Концепт в стиле МТС: `/static/mts-shell/index.html#home`. Его кабинет ведёт в тот же рабочий интерфейс;
старые браузерные черновики переносятся явно через мастер, без автоматической публикации.
Проверки в отдельной временной базе: `python scripts/check_source.py`.
Для полировки интерфейса без моделей: `python scripts/ui_qa_server.py` (порт 8014, имитация ответов).
Новые блокировки сериализуют один разговор, сохраняя ограниченную параллельность разных разговоров.
«Реплики клиента · цитаты» отделены от подтверждённых полей и не являются смысловым AI-резюме.

Текущая копия настроена на полностью локальный тест с **Qwen2.5‑3B + Whisper Small + Silero**.
Запуск: `start-local.ps1`. Инструкции и ограничения: [LOCAL_SETUP.md](LOCAL_SETUP.md).
Для второго разработчика: [TEAM_DEVELOPMENT.md](TEAM_DEVELOPMENT.md).
Автоматический разговор в оболочке МТС и перенос речевых моделей на CUDA: [docs/GPU_VOICE.md](docs/GPU_VOICE.md). Установка считается завершённой только после проверки фактических устройств и GPU-прогона, не по наличию настройки.
Доработка сценариев после питча: [docs/BOOKING_ENGINE.md](docs/BOOKING_ENGINE.md).
Описание Groq/Telegram ниже относится к прежнему облачному режиму; в этой локальной конфигурации они отключены.

Добавлен «Быстрый старт»: помощник владельца бизнеса без каталога услуг, сотрудников и календаря.
Компания → факты/FAQ → проверка → подтверждение → веб-тест → сохранённое обращение и расшифровка.
Это локальный прототип, **не телефонный пилот**. Добавлены Telegram-бот, регистрация и очередь
уведомлений для помощников «Быстрого старта». Телефонии нет; «перевод в чат» МТС ещё нужно уточнить.
Предусмотрен пароль одного владельца. Без пароля кабинет доступен только на localhost;
изоляции нескольких бизнес-владельцев пока нет. Используйте синтетические данные клиентов.
Инструкция нового блока: [Telegram и регистрация](TELEGRAM_SETUP.md).
Результаты и оставшиеся задачи: [отчёт первого блока](TRACK1_SPRINT_REPORT.md).

## Быстрый старт трека 1

После запуска откройте «Быстрый старт», укажите компанию и известные факты. Приветствие необязательно.
Нажмите «Проверить настройки», прочитайте предпросмотр и только затем «Подтвердить и сохранить».
Мастер не обращается к модели; в текущем режиме сам диалог обрабатывает локальный Ollama.
Откройте веб-тест и выберите голосовой разговор или «Начать веб-чат без микрофона».
Помощник собирает имя, телефон и причину обращения, просит согласие и сохраняет подтверждённое обращение.
Посмотреть разговор можно в «Обращениях». В «Агентах» доступно редактирование настроек:
изменения действуют только для новых разговоров. Существующие разговоры сохраняют снимок конфигурации.
Часы работы не выдумываются; неизвестное расписание не означает выходные всю неделю.
«Кратко» — сборка проверенных полей, **не смысловое AI-резюме**.
В разделе «Telegram» можно подтвердить получателя и включить доставку новых обращений.
Статус отправки виден в «Обращениях»; сохранение и доставка — разные результаты.

Проверка без внешней модели: `python -m pytest -q`.
Изолированный браузерный стенд: `python tests/browser_track1_server.py` (порт 8013, временная база, модель имитируется).
Необязательная проверка реального Groq: `python tests/live_track1_smoke.py`.
Она отправляет только синтетические текстовые данные и допускает не более 6 HTTP-попыток,
не отправляет email и не изменяет рабочую базу. Бесплатный лимит зависит от аккаунта.

## Предыдущие итерации

Существующий FastAPI/HTML/CSS/JS MVP с универсальным ядром:
AgentConfig → AgentRuntime → LLMProvider → tool calls → Business Tools.

Iteration 2 добавляет конструктор AI-сотрудников к прежнему Runtime, не меняя стек.
Iteration 3 добавляет анализ исходных требований, сценарии, изолированную симуляцию и readiness.
Текущий аудит: [Iteration 3](ITERATION_3_REPORT.md). История:
[Iteration 2.1](ITERATION_2_1_REPORT.md), [Iteration 2](ITERATION_2_REPORT.md), [Iteration 1.1](ITERATION_1_1_REPORT.md).

Русское демо: AI-администратор вымышленного салона «Линия» в Минске.
Цены в BYN, мастера, длительность и расписание **тестовые**, не реальные услуги.
18:00 недоступно; после 18:00 предлагаются 18:30 и 19:30, с учётом сохранённых записей.

## Запуск

Из каталога проекта:

~~~powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env  # Только при первом запуске; не перезаписывайте существующий .env
python -m uvicorn app:app --reload --host 127.0.0.1 --port 8000
~~~

Заполните GROQ_API_KEY в .env. Откройте http://127.0.0.1:8000.
Также сохранён start.ps1. Микрофон доступен на localhost или HTTPS.
Кнопка запуска включает микрофон; текстовое сообщение само начинает разговор без микрофона.
Остановка записи после 1050 мс тишины после речи; максимального таймера фразы нет.
Для API сохраняется ограничение файла 25 МБ.

## Окружение

- GROQ_API_KEY — только серверный ключ.
- GROQ_MODEL=openai/gpt-oss-20b — модель с local tool calling.
- BUILDER_MODEL=openai/gpt-oss-20b — отдельная конфигурируемая модель structured generation.
- SCENARIO_MODEL / SIMULATOR_MODEL / JUDGE_MODEL — отдельные модели генератора, клиента и судьи; по умолчанию openai/gpt-oss-20b.
- SIMULATOR_PROVIDER=scripted — публичный детерминированный клиент без дополнительных API-запросов;
  значение groq включает отдельного облачного User Simulator.
- GROQ_STT_MODEL=whisper-large-v3 — существующее распознавание (можно whisper-large-v3-turbo).
- TTS_VOICE=ru-RU-SvetlanaNeural, TTS_RATE=+12% — русская Edge neural-озвучка; можно ru-RU-DmitryNeural.
  Старый польский голос автоматически заменяется русским для этого демо.
- AGENT_CONFIG_PATH=configs/beauty_salon.json — внешняя конфигурация агента.
- PUBLIC_ORIGIN=http://127.0.0.1:8000 — адрес для превью.
- BUSINESS_EMAIL, SMTP_HOST, SMTP_PORT=587, SMTP_USER, SMTP_PASSWORD, SMTP_FROM — существующие SMTP-уведомления.
  Email бизнеса можно задать в форме. Пароль/ключ не выдаются через health.

Бесплатный лимит Groq зависит от аккаунта и может исчерпаться: отсутствие оплаты не означает отсутствие лимитов.
Edge TTS — внешний сетевой сервис, не офлайн-синтезатор; при недоступности можно продолжить текстом.
Телефония и платный TTS не подключены.

## Устройство проекта

- agents/models.py — отдельные сериализуемые BusinessContext, Role, AgentConfig, поля, сценарии, политики инструментов.
- agents/prompts.py — сборка identity, business, tools, scenarios, safety/escalation, conversation style.
- agents/runtime.py — универсальное состояние, allowlist инструментов, обработка tool results, подтверждение и завершение.
  В нём нет отраслевых веток или полей автомобиля/салона.
- agents/fields.py — schema-driven evidence, collected_fields и универсальное резюме действия.
- agents/validation.py — структурированный semantic validation; agents/factory.py — безопасная сборка runtime.
- tools/registry.py — доверенные реализации, capabilities/dependencies, read_only/confirmation/risk.
- services/business_hours.py — расписание и IANA timezone/DST; services/notifications.py — SMTP-уведомления.
- providers/base.py — контракт LLMProvider и нейтральные ответы/вызовы; providers/groq.py — диалоговый Groq-адаптер.
- providers/builder.py — отдельный BuilderProvider и Groq structured-output адаптер.
- builder/ — BusinessInput, BuilderDraft, trusted presets/catalog/mapping, preview, service и API.
- services/agent_repository.py — SQLite candidates/agents; services/agent_service.py — загрузка/активация.
- providers/language.py — русская нормализация продиктованных цифр и строгая проверка согласия.
- tools/base.py — контракт инструментов; tools/booking.py — запись; tools/handoff.py — запрос сотрудника.
- services/booking_service.py — тестовое расписание и заменяемый BookingRepository.
  SQLiteBookingRepository сохраняет реальные локальные записи, блокирует повторное/пересекающееся время одного мастера.
- configs/beauty_salon.json — внешнее определение роли, сценариев, услуг, мастеров и tools.
- prompts.py — загрузка AgentConfig и наложение существующей формы BusinessConfig.
- app.py — прежние web/STT/TTS/config/history/email endpoints и сборка зависимостей.
- storage.py — прежняя SQLite, новые обращения, отдельные bookings/escalations.
- static/ — прежний интерфейс с русской адаптацией, без redesign.

Прежняя форма демо-бизнеса сохраняется отдельно от AgentConfig. При выборе исходного демо загружается JSON
и применяются настройки бизнеса из SQLite; снимок итогового AgentConfig сохраняется в разговоре.
Изменения формы влияют на новые разговоры, не меняют уже показанное предложение в текущем.
Роль, сценарии, tools, базовые fields редактируются в JSON. Каталог services в форме — JSON-массив
с name, price, currency, duration_minutes, employees. Дополнительные обязательные поля
собираются по конкретному вопросу из схемы или декларации с evidence_patterns и проверяются сервером перед подготовкой записи.

Другую роль/набор инструментов можно передать тому же AgentRuntime: тест с библиотекарем
и reserve_book проверяет это без новой реализации ядра. Регистрация бизнес-инструментов
находится в ToolRegistry, а не в app.py/runtime. Новые агенты создаются отдельным Builder, без изменения Runtime.

## Создание первого AI-сотрудника

1. Откройте «Агенты» → «Создать AI-сотрудника».
2. Введите компанию, сферу, город, timezone и недельные часы. Например Nova Beauty, салон, Минск,
   Europe/Minsk, Пн–Пт 09:00–20:00, Сб 10:00–18:00, Вс выходной.
3. Укажите роль (например Администратор или Менеджер по продажам) и задачи: услуги/цены, запись, перевод человеку.
4. Сначала задайте общий каталог сотрудников — Анна и Мария, каждый с новой строки.
   Добавьте услуги обычными строками формы: Маникюр — 50 BYN — 60 минут; Стрижка — 40 BYN — 45 минут.
   У каждой услуги отметьте сотрудников из общего каталога; пустой выбор означает всех.
5. Нажмите «Сформировать черновик». Проверьте способности, вопросы, часы, каталог и предупреждения.
   JSON скрыт в необязательном техническом раскрытии и не редактируется.
6. Нажмите «Создать и активировать агента». Только это действие сохраняет агента и вызывает отдельную активацию.
7. Выберите его в «Демо» через selector и начните обычный голосовой или текстовый разговор.

BusinessInput → BuilderProvider → BuilderDraft → trusted mapper → AgentConfig → semantic validator
→ human preview → save → activate → существующий AgentFactory/AgentRuntime.

### Контракты и границы Builder

- BusinessInput: структурированные часы/услуги/сотрудники, описание, сайт-метаданные, роль, задачи, заметки и причины эскалации.
  Сайт не загружается и не скрапится. Пользователь не пишет prompts, schemas, regex или JSON paths.
- BuilderDraft: имя/роль/summary, выбор сценариев/инструментов, дополнительных полей, стиля и причин эскалации,
  unsupported requirements. Он не является AgentConfig и запрещает неизвестные ключи.
- Structured output: Groq `response_format=json_schema`, `strict=true`; затем Pydantic и semantic validation.
  Отдельный provider contract позволяет заменить адаптер без изменения Runtime.
  Механизм проверен по [Groq Structured Outputs](https://console.groq.com/docs/structured-outputs)
  и [OpenAI Compatibility](https://console.groq.com/docs/openai). Доступность/лимиты определяет аккаунт Groq.
- Field presets: person_name, phone, email, free_text, number, address, choice. Sources, нормализация,
  evidence и validation задаются сервером. Варианты choice экранируются сервером, не являются regex модели.
- Scenario Catalog: booking, faq, pricing, opening_hours, human_handoff. Это фиксированные шаблоны, не workflow DSL.
- Tools: check_slots, create_booking, transfer_to_human — только зарегистрированные реализации.
  Capabilities вычисляются сервером из Registry. Неизвестный tool делает черновик невалидным.
- Имя/телефон booking — user evidence; service/datetime/employee — доказательства результата check_slots.
  Цены/длительность — бизнес-каталог. Изменение данных требует серверного подтверждения.
- Regex/code/SQL/source paths/capabilities не входят в BuilderDraft. Текстовые значения остаются данными;
  они никогда не выполняются. Автоматического создания tools и migrations нет.
- Stable IDs: серверный NFKC + casefold + нормализация пробелов + SHA-256 prefix; ID lowercase и deterministic.
  Сотрудники дополнительно получают namespace бизнеса, чтобы независимые локальные календари не конфликтовали.
  Дубликаты display names объединяются с предупреждением при одинаковых данных; конфликт цены/длительности/сотрудников — ошибка.
  Переименование сущности при новой генерации меняет ID: редактор с сохранением identity ещё не реализован.
- У generated agents только `business.schedule` — canonical часы; `opening_hours` пустой, preview выводится из schedule.
- При human_handoff явный запрос человека принудительно immediate; отключение отвергается validator'ом.
  Инициатива AI: complaint, unsupported_scenario, tool_failure; последняя требует реальных повторных ошибок.
- Максимум два результата модели: исходный и один repair после ошибки черновика/semantic validation.
  Сетевой/provider failure останавливает генерацию. BusinessInput сохраняется в SQLite candidate и форме браузера.
  Секреты/тела API/BusinessInput не логируются. Logs содержат только lifecycle, IDs, outcome.

### Хранение и API

В существующей SQLite добавляются `agents` (id/name/status/config_json/created_at/updated_at/source/candidate_id)
и `builder_candidates` (входные данные, результат, validation, preview, attempts, review digest).
Созданный кандидат ещё не агент. После review сохраняется `valid`; отдельный activate переводит в `active`.
Невалидные результаты остаются candidates и никогда не попадают в Runtime. Исходный JSON демо не переписывается.
Активных агентов может быть несколько; клиент выбирает одного. Новый разговор сохраняет snapshot его конфигурации.
При изменении selector текущий разговор не переключается: сначала нужно закончить его.

- POST `/api/builder/generate` — BusinessInput, возвращает candidate/preview/validation.
- POST `/api/builder/validate` — candidate_id, повторная read-only semantic validation.
- POST `/api/agents` — candidate_id + review_token (digest показанного config), сохраняет проверенного агента.
- GET `/api/agents`, GET `/api/agents/{id}` — список/детали.
- POST `/api/agents/{id}/activate` — повторная проверка и activation.
- POST `/api/conversations` — optional agent_id; без него прежнее демо.

Это локальный single-user prototype без auth. Review digest защищает от случайно устаревшего preview,
но не заменяет авторизацию. API, SQLite, frontend нельзя публиковать в production как есть.
Legacy email-настройки относятся только к исходному демо. У generated agents email-отправка пока отключена,
чтобы их обращения не ушли на старый BUSINESS_EMAIL. Conversation/booking/handoff сохраняются локально.

### Ограничения Iteration 2

Русский язык, существующие STT и Edge TTS; нет отдельного Builder chat/voice adapter.
STT-подсказка содержит только display names и последний вопрос, без ID и полного knowledge JSON.
Она консервативно ограничена 224 UTF-8 байтами, чтобы не превышать 224 byte-BPE токена Whisper;
ограничение prompt описано в [Groq Speech to Text](https://console.groq.com/docs/speech-to-text).
Нет генератора произвольных бизнес-действий, внешних календарей, CRM, платежей/возвратов, scraping/RAG,
auth/billing/telephony или production deployment. Оценка качества/readiness добавлена в Iteration 3, см. ниже.
Для неподдерживаемых требований выводится warning; отсутствие fake tool не означает поддержку задачи.
Нет редактора/удаления созданных агентов. UI поддерживает одно рабочее окно в день, API — несколько.
Generated mock availability строится из рабочих окон с шагом 30 минут от начала каждого окна;
duration, timezone и сохранённые bookings учитываются. Исходное legacy demo сохраняет свои slot_times.
В субботу после 18:00 у Nova Beauty слотов нет, в воскресенье закрыто: агент не должен обещать запись.

### Builder hardening — Iteration 2.1

- В Iteration 2.1 role.name бралось из BuilderDraft.role_name. В Iteration 3 это исправлено:
  canonical role.name берётся из BusinessInput.desired_role; draft не может её переопределить.
  Description и greeting называют ту же каноническую роль.
  role.id вычисляет сервер: `stable_id(role_name, "role")` (NFKC/casefold/пробелы/SHA-256), не LLM.
  Регистр и лишние пробелы не меняют ID. Greeting нейтральный: «Я виртуальный сотрудник [бизнес].
  Моя роль — [роль]». Это не обещает автоматически новую capability: доступные действия всё ещё задаёт Registry.
- `availability_mode=schedule_30m` у новых generated configs; часы строятся по запрашиваемому дню,
  а не по общему фиксированному массиву. Старт — начало окна, затем +30 минут; услуга должна целиком поместиться.
  Старые сохранённые generated catalogs с service IDs тоже используют расписание, без миграции пользовательской БД.
  Legacy demo без IDs по-прежнему использует slot_times. Закрытые дни, прошлые даты/время, DST и локальные overlaps
  исключаются; перед сохранением доступность проверяется повторно, SQLite защищает от пересечений.
- Для каждой услуги booking dependency validator проверяет, существует ли хотя бы один потенциальный старт
  в недельном расписании с учётом длительности. Если нет — validation error до save/activate.
  Это статическая проверка рабочего окна, не обещание свободного места сегодня и не оценка качества разговора.
- `BusinessInput.employees` — единственный источник сотрудников. `ServiceInput.employees` — subset ссылок по
  display names, пустой список — весь каталог. Mapping нормализует имена, объединяет дубликаты и сохраняет
  stable employee IDs в services; display names остаются в общем knowledge.employees.
  Неизвестное имя даёт ошибку с названием услуги/сотрудника, implicit employee не создаётся.
  UI отражает этот контракт чекбоксами; удаление выбранного сотрудника из общего каталога требует исправить ссылку.
- Один AgentBuilder хранит один ToolRegistry; GroqBuilderProvider.bind_registry получает именно этот instance.
  Schema, рекламируемые tools/capabilities, mapper и validator используют его. Сценарии с отсутствующими
  required tools не рекламируются. Регистрация сама по себе не добавляет инструмент в доверенный Scenario Catalog.
  Standalone provider/strict_schema без аргумента допускают default registry; внутри pipeline новый default не создаётся.
  Провайдеры без schema/catalog (например deterministic mock) по-прежнему могут реализовать только generate.
- Ограничения: не реальный календарь сотрудников, нет праздников/capacity/внешнего календаря; роль меняет identity,
  но не создаёт неизвестные действия. Старые сохранённые role/greeting не переписываются автоматически.
  Названия сотрудников — identity inputs; переименование меняет ID. Один локальный процесс без auth/tenant isolation.

См. [отчёт Iteration 2.1](ITERATION_2_1_REPORT.md) с точными результатами проверок и архивом.

## Действия и защита

1. check_slots(service, date, preferred_time?, employee?) возвращает только свободные тестовые слоты.
2. create_booking(customer_name, phone, service, datetime, employee?, additional_fields?)
   сначала проверяет слот из check_slots и подготавливает точное предложение.
   На этом шаге записи в bookings нет. Сервер показывает все сохраняемые значения, включая динамические поля, цену и длительность.
   Только отдельное однозначное «да»/«подтверждаю» выполняет ранее подготовленное действие.
   «Да, но на другое время» не подтверждает старый слот. Доступность повторно проверяется при сохранении.
3. transfer_to_human(reason, summary, reason_type?) сохраняет reason/type, agent_id, серверное summary, известные данные/provenance, transcript и timestamp
   в escalations. Автоматический сценарий завершается без реального соединения.
   Явная просьба об операторе обрабатывается немедленно, без LLM-задержки и лишних вопросов.
   Выбор мастера не считается запросом перевода.

## Конфигурационные контракты Iteration 1.1

`business.timezone` — IANA имя (например Europe/Minsk), `business.schedule` — дни 0–6 (понедельник=0)
со списками окон `{"start":"08:00","end":"17:00"}`; пустой список означает закрытый день.
Окна не пересекаются и не переходят через полночь. Для 24/7 каждый день: 00:00–24:00.
`opening_hours` — согласованное представление: ежедневное HH:MM–HH:MM, 24/7 или JSON расписания.
В форме задаются opening_hours/timezone; расписание вычисляется при загрузке. Python менять не нужно.
Неоднозначные/несуществующие часы при DST не предлагаются автоматически.

`business.capabilities` — лёгкий список, например booking/human_handoff.
`role.required_capabilities`, `scenarios.required_tools/required_fields/required_capabilities`
задают проверяемые ссылки. Свободный текст не доказывает совместимость — validator возвращает предупреждение.

Для каждого `fields[]`: id, label, question, required, data_kind (user/business), allowed_sources,
requires_confirmation, normalization (text/digits/email), value_pattern, evidence_patterns,
tool_paths/business_paths. По умолчанию поле пользовательское, допустимый источник — user.
Неизвестное динамическое поле не требует нового HTML или колонки SQLite.

Пример обязательного пользовательского поля:

~~~json
{"id":"allergy","label":"Аллергия","question":"Есть ли аллергия?","required":true,
 "evidence_patterns":["у меня аллергия на\\s+(?P<value>[^.!?;]+)"]}
~~~

Без evidence_patterns поле безопасно собирается ответом на точный question; `Аллергия: латекс`
также считается декларацией. Для business полей нужны разрешённые tool_paths (проверяются против result_schema)
или существующие business_paths. Поля системного/вычисленного происхождения нельзя просто приписать LLM:
обязательное поле без доверенного producer признаётся invalid. Системные значения из доверенной подготовки
действия имеют отдельный action_provenance.

Provenance включает field_id, value, source, evidence и confirmed. User evidence перепроверяется по серверному
transcript, не по словам ассистента. Сохранение требует отдельного согласия на последнюю показанную версию:
digest + привязка к реплике подтверждения. Само `confirmed=True` ничего не разрешает.
Политика write tools не ослабляется `requires_confirmation:false` в generated config.

Escalation: explicit_human_request=immediate/disabled; agent_initiated — словарь reason_type→allowed/disabled.
Демо разрешает unsupported_scenario и tool_failure; последний требует двух фактических ошибок.
Причина клиента: explicit_user_request. Confidence engine не добавлен.

Runtime хранит нейтральные ConversationMessage/ToolCall/ToolSpec. Groq-native JSON формируется только в адаптере.
Старые незавершённые диалоги v1 нельзя продолжать: начните новый; история остаётся доступной.

Успех записи/передачи показывается только по результату инструмента.
Отмена разговора сохраняет stopped, не создаёт booking. События инструментов сохраняются в tool_events.

## API и миграция

- GET /, /api/health, /api/config, /api/agent, /api/applications.
- POST /api/agent/validate — AgentConfig → valid/errors/warnings, без сохранения и запуска Builder.
- PUT /api/config — существующая форма, теперь русский BusinessConfig.
- POST /api/conversations → interaction_id + greeting.
- POST /api/chat с interaction_id, text, request_id → text, complete, status, interaction.
  request_id предотвращает повторную обработку последней реплики при повторе запроса.
- POST /api/transcribe — file, context, interaction_id; русский STT с контекстом агента.
- POST /api/speech — text, audio/mpeg.
- POST /api/application с interaction_id — завершить/сохранить текущее обращение;
  больше не вызывает отдельный LLM для извлечения автомобильной заявки.

data/autofix.db сохранён на прежнем месте. Старые business_config и applications не удаляются:
новое демо использует callwise_config; email перенесён из старых настроек.
Исторические автомобильные заявки доступны в «Обращениях» с отметкой архива.
Новые conversations не требуют car/problem. Booking хранится отдельно.
Все реплики и tool events сохраняются сервером; браузер не является источником доверенной истории.
Ошибка email не отменяет сохранённый результат; UI показывает её отдельно.
Миграция добавляет bookings.structured_data JSON и escalations.reason_type/agent_id; существующие строки сохраняются.
Динамические значения, evidence и подтверждения лежат в JSON, а не в отдельных колонках.

## Проверка

~~~powershell
python -m pytest -q
node --check static/app.js
node --check static/builder.js
node --check static/evaluation.js
~~~

Локальные тесты без сети: конфигурация/язык, динамические инструкции, arbitrary agent/tool,
подмена провайдера, tool results, слот, подтверждение/отказ/изменение,
сохранение/повторные запросы/конкурирующие слоты, handoff, наследуемая история,
STT/TTS контракты, русские ошибки, secrets health, отсутствие таймера записи.
Дополнительно tests/test_builder.py: ограничения BuilderDraft, presets, IDs/дубликаты, расписание,
один repair, ошибки провайдера/квоты, review/save/activate, существующий Runtime и booking/handoff.
Внешние тесты запускайте раздельно при ограничениях free plan: общий запуск может исчерпать квоту токенов.

Реальные Groq и TTS, без email и с отдельной временной БД:

~~~powershell
$env:CALLWISE_LIVE_TESTS = "1"
python -m pytest tests/test_live.py -q -s
~~~

Для полного прогона с реальными сервисами: CALLWISE_LIVE_TESTS=1, затем python -m pytest -q.
Для изолированной проверки интерфейса: `python tests/browser_smoke_server.py`, открыть http://127.0.0.1:8001.
Этот вспомогательный сервер использует MockLLMProvider/временную SQLite, отключает отправку email,
но оставляет реальную web-логику и endpoint озвучки. Не используйте его вместо обычного запуска.

Ручная проверка:
начать → «Хочу завтра после шести записаться на маникюр» → «На 18:30»
→ имя → телефон → «Да, подтверждаю».
Ожидаются tool_events check_slots, подготовка create_booking, затем подтверждённый create_booking,
карточка «Запись создана», запись в bookings и обращение в истории.
В новом разговоре: «Соедините меня с человеком».
Ожидаются escalation, сохранённый контекст и честное сообщение о зафиксированном запросе.

## Docker и ограничения

~~~powershell
docker build -t callwise .
docker run --env-file .env -p 8000:8000 -v callwise-data:/app/data callwise
~~~

Docker включает новые модули и JSON, не включает .env или существующие клиентские данные.
Один процесс приложения, локальное демо, без авторизации. Не публикуйте кабинет открыто.
Синхронные LLM/SMTP запросы и конечный список тестовых времён — не production calendar.
Часовой пояс и рабочие часы меняются в конфигурации; поддерживается IANA/DST.
Контекст разговора пока не сжимается; free-plan quota и сетевые сервисы остаются ограничениями.
Известные декларации/ответы сохраняются в collected_fields; свободная речь без проверяемого mapping остаётся в transcript.
Полноценный речевой barge-in/full-duplex, телефония, CRM, auth и billing не входят в итерацию.

Scenario Generator → Simulation → Evaluation → Readiness реализованы в Iteration 3.
Semantic validation остаётся отдельной технической проверкой; readiness не является production-сертификацией.
Реальный календарь — отдельный адаптер BookingRepository, без изменения AgentRuntime.

## Проверка агента — Iteration 3.1

Создайте агента через «Агенты → Создать AI-сотрудника», проверьте и сохраните.
На карточке нажмите «Проверить агента», затем «Запустить проверку».
По умолчанию CORE с лимитом до 20 сценариев; допустимый лимит 12–40. Обновление страницы восстанавливает историю,
но не запускает новый прогон. Legacy демо без исходного BusinessInput оцениваться этим механизмом не может.

До Builder нажмите «Сформировать черновик»: появится review требований. Исправьте тип / полярность,
затем «Подтвердить требования и сформировать». Сохранение preview подтверждает договор вместе с конфигурацией.
RequirementContract содержит raw_tasks, entries (task_index/source_text/known ID/polarity), version/source/confirmed.
Каталог закрыт: booking, pricing, faq, opening_hours, human_handoff, unsupported. Polarity: required / forbidden / not_requested / unknown.
Отрицания распознаются при intake, не при каждом evaluation. «Не записывать» блокирует booking tools;
«CRM не подключать» / «Возвраты денег не нужны» не становятся обязательными интеграциями.
Это ограниченный словарный resolver, не универсальный NLP: пользовательский review обязателен в UI.
Evaluation сравнивает конфигурацию с сохранённым договором и desired_role, а не с решениями Builder.
Договор сохраняется в JSON builder_candidates и возвращается рядом с agent; confirmed устанавливает сервер при save.
Review-token связывает конфигурацию и договор. Legacy generated agents получают legacy_inferred один раз,
предупреждение и максимум LIMITED без подтверждения. Legacy demo без BusinessInput не оценивается.
Если требовалась запись, но booking отсутствует, идеальный FAQ не даст READY.
Coverage: COVERED / PARTIALLY_COVERED / MISSING / UNSUPPORTED. Неизвестные задачи не считаются поддержанными.
Роль, каталог услуг/цен/длительности, required fields, tools, capabilities и immediate handoff сверяются сервером.

12 обязательных шаблонов: identity, явный handoff, запись с подтверждением, неоднозначное согласие,
несообщённый телефон, выдуманное поле, занятый слот, отсутствующий refund tool, два сбоя календаря,
неизвестная информация, отказ от старого предложения, цена. Генератор Groq может менять только
выбирать paraphrase_template из закрытой allowlist разрешённых шаблонов.
{service}/{date}/{time} рендерятся сервером из canonical context. Произвольные opening, literal service/time,
изменение намерения, отрицания или дополнительных фактов отвергаются (один repair максимум).
Assertions, tools, backend и expected state задаются сервером.
Для malicious model-output probes три/несколько ответов провайдера намеренно подменяются доверенной
тестовой нагрузкой; защиту выполняет тот же настоящий AgentRuntime. Эти probes не доказывают качество LLM.

Каждый сценарий использует временную SQLite через context-local storage; рабочие bookings/interactions/escalations
не изменяются. Сохраняется только evaluation-отчёт с синтетическим диалогом, инструментами и provenance.
Непроверенные custom backends в симуляции не исполняются. Результат детали содержит только публичный диалог,
tool trace, assertions и структурированный JudgeResult, без chain-of-thought.

EvaluationPlan сохраняется до любого provider call: seed/mode, выбранные IDs/имена, trusted cases,
coverage policy, omitted axes/cases и верхняя оценка запросов. Каталоги ≤8 проверяются полностью;
большие — seeded sample до 5 услуг/сотрудников. Для каждой выбранной услуги создаётся booking / price
проверка, если задача запрошена; покрываются доступные сотрудники, разные графики, near closing,
занятый слот и закрытый день (или outside hours для 7-дневного бизнеса).
Лимит count может обрезать набор: это явно отражается в missing_axes/excluded_scenarios и запрещает READY.
Coverage не означает Cartesian-product всех услуг × сотрудников × дней.
Четыре независимых показателя: структурное покрытие требований, успешность сценариев,
корректность инструментов, безопасность/передача человеку. PASS / FAIL / ERROR различаются.
Отдельный EvaluationCoverage показывает planned/executed/evaluated/PASS/FAIL/ERROR/completion, scope и missing axes.
Успешность = PASS / (PASS + FAIL); ERROR исключён, а не замаскирован как провал. Safety evidence и quality judge
отображаются отдельно. READY требует полного обязательного набора без FAIL/ERROR, достаточного scope,
подтверждённых требований, покрытия всех требований, отсутствия критических
нарушений и safety=100%; нижние пороги reliability/tool correctness — 95%.
Некритические ошибки → LIMITED; отсутствующая критическая задача, unsafe write/данные/handoff,
доказанный провал любого booking happy path или reliability ниже 60% → NOT_READY.
Ошибки / пустой прогон / недостаточно завершённых обязательных проверок → INCONCLUSIVE, если не доказан
critical defect. Провал safety не исчезает при одновременной ошибке judge или другом 429.
READY действует только в сохранённом scope, не сертифицирует весь бизнес или production.
Агент автоматически не деактивируется и не исправляется.

Конфигурация, исходный BusinessInput и RequirementContract сохраняются с SHA-256. При их изменении отчёт получает OUTDATED,
исторический READY нельзя считать текущим. Для нового прогона нужен отдельный клик пользователя.
В SQLite добавлены evaluation_runs, evaluation_scenarios, evaluation_results; прежние таблицы не заменены.

API:

- POST /api/builder/requirements — BusinessInput; локальный contract/review, без облачного запроса.
- POST /api/builder/generate — BusinessInput + optional requirement_contract; старый формат совместим.
- POST /api/evaluations — agent_id, count, seed, mode; 202 и фоновый прогон.
- GET /api/agents/{agent_id}/evaluations — история.
- GET /api/evaluations/{run_id} — прогресс и отчёт.
- GET /api/evaluations/{run_id}/scenarios/{scenario_id} — полный trace.

Один evaluation job на процесс; повторное нажатие не создаёт второй одновременный job.
После перезапуска незавершённый job помечается WorkerInterrupted, а не продолжается автоматически.
Лимиты: 12 пользовательских реплик на сценарий, один repair генератора,
240 API-запросов на прогон, timeout отдельного запроса 20 секунд, без транспортных retries.
Agent 429 останавливает последующие agent calls: остаток получает ERROR / not_run, итог обычно INCONCLUSIVE.
Judge 429 отключает последующий cloud judge, но safety/function simulations продолжаются.
Generator запускается только после trusted core в STANDARD; 429/timeout/bad output сохраняются как
generator_status=failed / infrastructure_errors, не делают core ERROR. Непроверенные варианты понижают completeness.
CORE не вызывает generator или AI simulator; агент / judge по-прежнему могут использовать облако.
STANDARD добавляет до 4 fact-locked вариантов, если count оставляет место после обязательного покрытия.
DEEP зарезервирован в API, но возвращает 422 до запуска; дорогая реализация отсутствует.
Request budget 240 — жёсткий предел, не гарантия достаточной квоты free plan. Сохраняются requests used,
theoretical_calls_upper_bound и max_calls_estimate (с учётом budget); это не оценка token cost.
Наличие ключа в health не означает наличие свободной квоты.

Opt-in облачные проверки (отдельно от обычных локальных тестов):

Ограниченная наблюдательная проверка 3.1 (до 3 сценариев / 12 запросов, stop при 429):

~~~powershell
$env:CALLWISE_INTEGRITY_LIVE = "1"
python -m pytest tests/test_integrity_live.py -q -s
~~~

PASS этого теста подтверждает bounded execution / честный неполный verdict, а не успешность всех live-сценариев.

~~~powershell
$env:CALLWISE_EVAL_LIVE_TESTS = "1"
python -m pytest tests/test_evaluation_live.py -q -s
~~~

Речевой regression:

~~~powershell
$env:CALLWISE_LIVE_TESTS = "1"
python -m pytest tests/test_live.py -q -s -k speech
~~~

UI smoke на отдельной временной БД: python tests/browser_smoke_server.py, http://127.0.0.1:8001.
Его evaluation providers — тестовые doubles; интерфейс явно предупреждает об этом.
tests/browser_failure_case.py позволяет воспроизвести LIMITED/FAIL с намеренно неверной ценой,
но принимает только существующий disposable callwise-browser-*/test.sqlite, не рабочую базу.

Ограничения: классификация требований словарная, не полный semantic NLP; тестируется сохранённый scope
и закрытые перефразировки, а не все возможные формулировки. Большой каталог проверяется выборочно.
Структурное покрытие расписания/FAQ не равно полному языковому benchmark этих функций.
Сохранённый seed воспроизводит шаблоны, но не гарантирует одинаковые ответы удалённого LLM.
Судья может ошибаться; safety gates не зависят от его мнения. Без ответившего судьи quality-сценарии получают ERROR.
Docker build/run и cloud success должны проверяться отдельно — результаты текущего запуска в отчёте.
Независимый аудит: ITERATION_3_2_REPORT.md. Полный безопасный ZIP: ./build-archive.ps1 (без .env/data/cache).

### Iteration 3.2: контексты, инфраструктура и bounded diagnostics

Pricing использует service_context: услуга, цена, валюта, длительность. Сотрудник/дата/слот
появляются только в booking_context. Pricing-only бизнес с Консультацией 50 BYN и employees=[]
создаётся и проходит локальную оценку. Для обязательного pricing нужен непустой каталог с
валидными price/currency. Generic FAQ без этих фактов не является покрытием цен;
честный отказ без данных не выполняет требование «отвечать по ценам».

Cloud evaluation сначала выполняет harmless provider preflight: текст, local function call,
результат локального инструмента → ответ модели, strict JSON schema. Он не использует
BusinessInput/историю клиентов и не является readiness. FAIL останавливает запуск сценариев:
ERROR / INCONCLUSIVE (если нет независимо доказанного дефекта). Локальные doubles не блокируются.
Проверенные capabilities ограничены openai/gpt-oss-20b и openai/gpt-oss-120b; неизвестный model ID
не используется в cloud evaluation до проверки/расширения доверенного списка. Автоматического fallback нет.

ProviderError хранит только provider/model/operation/status/category/retryable/safe_reason и
allowlisted признаки. Нет raw provider body, request, headers, ключей, reasoning или attempted arguments.
Произвольный текст failed_generation.reason не сохраняется: он преобразуется в безопасный фиксированный код.
Транспортные retries выключены. Только доказанный tool_generation_failed получает максимум один
повтор тех же messages/tools с temperature=0. Он виден в metadata и расходует общий бюджет.
Unsupported parameter, schema/config, authentication, model mismatch, arbitrary 400 и 429 не повторяются.

Отдельная локальная диагностика (не вызывает Builder LLM, не записывает в рабочую БД, не отправляет email):

~~~powershell
python -m evaluation.provider_diagnostics --output proof/provider-preflight.json
python -m evaluation.provider_diagnostics --functional --output proof/provider-functional.json
~~~

Первый вариант: preflight максимум 6 HTTP attempts. Второй: preflight и functional suite вместе
максимум 12 HTTP attempts, включая единственный разрешённый retry; при первом provider error suite
останавливается. Functional: настоящая цена, check_slots, продолжение после tool result, серверный
handoff, реальный unsupported request без injected probe. Полный booking и live readiness не требуются.
Обычный Runtime быстро отвечает на первый read-tool результат серверным текстом; continuation в smoke
проверяется настоящим следующим пользовательским ходом с сохранённым реальным tool result.
В отчёте сохраняются счётчики/булевы evidence и allowlisted tool names, не полные запросы/ответы модели.

Локальные проверки: python -m pytest -q; python -m compileall -q agents builder evaluation providers services tools tests app.py.
JS: node --check static/app.js; node --check static/builder.js; node --check static/evaluation.js.
Текущий safe live результат: proof/iteration3-2-live.json (8 запросов: 4 preflight + 4 functional).
Прошлую неизвестную ошибку HTTP 400 нельзя ретроспективно классифицировать без её тела;
новые ошибки классифицируются безопасно. Никакой замены модели или переписывания Runtime prompt не сделано.

Документация провайдера:

Подключение записи к Google Calendar и Bitrix24: [docs/CRM_CALENDAR.md](docs/CRM_CALENDAR.md).
Защиты разговора и все названные клиентские риски: [docs/CUSTOMER_RISKS.md](docs/CUSTOMER_RISKS.md).
Новые разговоры запрашивают выбор до микрофона; очередь ручных запросов: `/static/safety.html`.
Кабинет подключений: `/static/integrations.html`. Внешние операции выключены по умолчанию;
аккаунты бизнеса и реальный smoke-test обязательны. Локальный демо-календарь сохранён.
[Local tool calling](https://console.groq.com/docs/tool-use/local-tool-calling),
[Speech to text](https://console.groq.com/docs/speech-to-text).


## Track 3 — meetings release

[Text-only setup, isolated Photoprint seed and shutdown](docs/track3-release/RUNBOOK.md)
uses the existing application without speech weights. [Status and acceptance evidence](docs/track3-release/STATUS.md),
[frozen model evaluation](docs/track3-release/EVALUATION.md), [architecture](docs/track3-release/ARCHITECTURE.md),
[API](docs/MEETINGS_API.md), [data removal](docs/track3-release/RETENTION.md),
[licenses](docs/track3-release/LICENSES.md), and [5–7 minute demo](docs/track3-release/DEMO.md).
Release readiness is blocked until the outstanding live-model, independent reproduction
and review gates pass; historical MVP model results are not current release evidence.


### Фокус · Фотопринт v2 (разработка)

Изолированный текстовый запуск, демо-роли и проверки: [V2_QUICKSTART.md](docs/track3-release/V2_QUICKSTART.md).
Текущее состояние и непройденные критерии: [журнал v2](docs/track3-handoffs/agent-v2.md).
