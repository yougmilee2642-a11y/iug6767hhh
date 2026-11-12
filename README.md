# Фокус

Веб-приложение с AI-помощниками для бизнеса: обработка обращений, работа с документами, подготовка встреч, протоколы и контроль поручений. Сервер — FastAPI и SQLite, интерфейс — HTML, CSS и JavaScript без отдельной сборки.

Проект находится на стадии прототипа. Демонстрационные компании, пользователи и показатели вымышлены.

## Возможности

- **Встречи** (`/meetings`): документы и их версии, поиск с источниками, подготовка встреч, расшифровки, проверяемые протоколы, поручения, календарь, отчёты и ассистент. Доступ проверяется на сервере с учётом роли.
- **Кабинет** (`/`): настройка помощников, текстовые и голосовые диалоги, обращения и проверка сценариев.
- **Интеграции**: Telegram, SMTP, Google Calendar и Bitrix24. Внешняя доставка требует отдельных настроек и явно включается.
- **Локальные модели**: Ollama для текста, T-one и GigaAM для распознавания, Silero для синтеза речи. Голосовые зависимости и веса устанавливаются отдельно.

Изменения поручений и другие действия ассистента проходят предпросмотр и подтверждение. Подключённой телефонной линии нет.

## Быстрый старт: встречи без голосовых моделей

Нужны Python 3.11–3.12 и Git. Команды для PowerShell из корня проекта:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-track3-runtime.txt
.venv/Scripts/python.exe -m pip check

$env:MEETINGS_DB_PATH = Join-Path $PWD 'demo-db/meetings.db'
$env:MEETINGS_DEMO = '1'
.venv/Scripts/python.exe scripts/seed_meetings_demo.py --db $env:MEETINGS_DB_PATH
.venv/Scripts/python.exe scripts/track3/start.py --db $env:MEETINGS_DB_PATH --port 8000
```

Откройте [Фокус](http://127.0.0.1:8000/meetings). Для демонстрации доступны:

| Роль | Логин | Пароль |
| --- | --- | --- |
| Директор | `director` | `director-demo` |
| Руководитель производства | `prod_head` | `prod_head-demo` |
| Дизайнер | `designer` | `designer-demo` |
| Администратор | `admin` | `admin-demo` |
| Аудитор | `auditor` | `auditor-demo` |

Запуск создаёт изолированную демо-базу, отдельную базу кабинета и ключ сессии в `demo-db/`. Эта папка не попадает в Git. Повторный запуск использует те же данные; повторное заполнение не создаёт дублей. Остановка — `Ctrl+C`.

На macOS/Linux используйте `.venv/bin/python` и абсолютный путь к демо-базе:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-track3-runtime.txt
export MEETINGS_DB_PATH="$PWD/demo-db/meetings.db"
export MEETINGS_DEMO=1
.venv/bin/python scripts/seed_meetings_demo.py --db "$MEETINGS_DB_PATH"
.venv/bin/python scripts/track3/start.py --db "$MEETINGS_DB_PATH" --port 8000
```

Без модели доступны документы, роли, сохранённые данные, ручная работа с протоколом и поручениями, тестовый календарь и отчёты. Генерация протокола, подготовка и ответы модели требуют Ollama. При недоступной модели сервер возвращает `503 model_unavailable`, сохраняя исходные данные.

## Подключение модели и полный кабинет

Для локального текстового режима установите Ollama и загрузите модель:

```sh
ollama pull qwen3:4b-instruct
```

В `.env` либо в окружении процесса задайте `OLLAMA_BASE_URL=http://127.0.0.1:11434`, `OLLAMA_MODEL=qwen3:4b-instruct` для кабинета и `MEETINGS_MODEL=qwen3:4b-instruct` для встреч. Пример `.env.local.example` предназначен для локального режима, `.env.example` — для облачного режима с Groq. Создавайте `.env` из примера только при первой настройке. Существующий файл содержит ваши настройки и секреты.

Обычный запуск кабинета после установки `requirements.txt`:

```powershell
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Этот запуск использует рабочие базы в `data/`. Для демонстраций и проверок используйте изолированный запуск выше. Если задан пароль владельца, он защищает кабинет и доступ к встречам дополнительно к учётной записи участника.

Голосовой режим требует дополнительных пакетов, весов и подходящего оборудования: [локальная установка](docs/LOCAL_SETUP.md), [распознавание речи](docs/LOCAL_ASR.md), [текстовая модель](docs/LOCAL_LLM.md). Микрофон в браузере доступен на localhost или через HTTPS.

## Настройки и данные

| Настройка | Назначение |
| --- | --- |
| `AI_PROVIDER` | `ollama` для локального текста, `groq` для облачного |
| `OLLAMA_BASE_URL`, `OLLAMA_MODEL` | Адрес Ollama или шлюза и имя модели |
| `MEETINGS_MODEL` | Модель встреч; задаётся отдельно от модели кабинета |
| `MEETINGS_DB_PATH` | Путь к базе встреч |
| `MEETINGS_SECRET` | Секрет подписи сессий встреч; изолированный запуск сохраняет его рядом с базой |
| `MEETINGS_DEMO=1` | Переключение ролей в демонстрационном наборе |
| `PUBLIC_ORIGIN` | Внешний адрес приложения |
| `TELEGRAM_ENABLED`, `TELEGRAM_BOT_TOKEN` | Включение и токен Telegram-бота |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` | Настройки отправки почты |

Полные примеры настроек находятся в `.env.example` и `.env.local.example`. Некоторые технические ключи окружения, базы и интеграций сохраняют прежние имена для совместимости с существующими установками.

Рабочие базы и аудио находятся в `data/`, веса — в `models/`, секреты — в `.env` и `secrets/`. Они исключены из Git. Для удалённого доступа нужны HTTPS, пароль владельца и собственные учётные записи; демонстрационные пароли для этого не подходят. Локальный режим отключает внешние интеграции. Адрес удалённого Ollama-шлюза означает обработку текста на машине этого шлюза.

## Проверки

Тестовые зависимости отделены от текстового окружения. Node.js 22 нужен для проверок JavaScript, сборка интерфейса не требуется.

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-track3-v2-test.txt
.venv/Scripts/python.exe scripts/track3/check.py -q tests --ignore=tests/ui_track3
node --test tests/*.cjs static/mts-shell/tests/*.mjs
.venv/Scripts/python.exe scripts/track3/v2_http_smoke.py --output "$env:TEMP/focus-http.json"
```

Проверки используют временные базы и дублёры внешних сервисов. Они не подтверждают качество реальной модели или микрофона. Для браузерных проверок:

```powershell
.venv/Scripts/python.exe -m playwright install chromium
.venv/Scripts/python.exe scripts/track3/v2_ui_check.py --output "$env:TEMP/focus-ui.json" --artifacts "$env:TEMP/focus-ui"
```

Логи, скриншоты и результаты проверок сохраняйте вне исходников. CI публикует результаты как временные артефакты.

## Структура

| Путь | Содержимое |
| --- | --- |
| `app.py`, `storage.py` | Приложение и хранилище кабинета |
| `meetings/` | Встречи, документы, роли, календарь, поручения и отчёты |
| `agents/`, `builder/`, `evaluation/` | Диалоговое ядро, конструктор и проверка помощников |
| `providers/`, `services/`, `tools/` | Модели, речь, прикладные сервисы и инструменты |
| `integrations/`, `track1/` | Интеграции, обращения и Telegram API |
| `static/` | Интерфейс, локальный шрифт и логотип |
| `configs/` | Демонстрационные конфигурации и примеры интеграций |
| `demo/`, `evaluation/track3/` | Воспроизводимые демо-данные и контрольные наборы тестов |
| `scripts/`, `tests/` | Установка, обслуживание и проверки |
| `docs/` | Инструкции и техническая документация |

## Документация

- [Запуск и сценарии встреч](docs/track3-release/V2_QUICKSTART.md)
- [Архитектура](docs/track3-release/ARCHITECTURE.md) и [API](docs/track3-release/API.md)
- [Документы и версии](docs/track3-release/DOCUMENTS.md), [поиск](docs/track3-release/SEARCH.md), [календарь](docs/track3-release/CALENDAR.md)
- [Хранение данных](docs/track3-release/DATA_POLICY.md) и [доставка уведомлений](docs/track3-release/DELIVERY.md)
- [Telegram](docs/TELEGRAM_SETUP.md), [CRM и Google Calendar](docs/CRM_CALENDAR.md)
- [Лицензии зависимостей, моделей и шрифта](docs/track3-release/LICENSES.md)

`build-archive.ps1` и `build-archive.sh` создают ZIP текущего коммита из файлов Git. Незакоммиченные изменения, локальные данные и содержимое подмодулей в архив не включаются.
