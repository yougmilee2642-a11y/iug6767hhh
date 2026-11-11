# Текстовый запуск Track 3

Запускать из **codex/track3-integration** (или PR с ней), после слияния всех поставок.
Python 3.12, Node 22 для JS-проверок. Веса речи, PyTorch и GPU для текстового
приложения не нужны. Проверен исходный app.py, изменения в нём не делались.
OpenAI/edge-tts SDK остаются импортными зависимостями основного приложения;
текстовый meetings-путь использует MeetingLLM, внешние AI API не вызываются.

## Установка

```bash
python3.12 -m venv .venv-track3
.venv-track3/bin/python -m pip install -r requirements-track3-lock.txt
.venv-track3/bin/python -m pip check
```

Windows PowerShell: `py -3.12 -m venv .venv-track3`; далее вместо
`.venv-track3/bin/python` использовать `.venv-track3\Scripts\python.exe`.
Lock включает инструменты проверки; более короткий requirements-track3.txt содержит
прямые зависимости текстового приложения. Транзитивные версии для воспроизведения
зафиксированы lock-файлом. Это проверенный срез, а не обещание актуальности версий.

Никакие submodule/ASR-модели для этого пути скачивать не требуется. Если локальная
Ollama ещё не установлена, её надо установить отдельно и **заранее** выполнить
`ollama pull qwen2.5:7b` на машине инференса. Официальная карточка
[qwen2.5:7b](https://ollama.com/library/qwen2.5:7b) указывает приблизительно **4.7 GB**, Q4_K_M;
это не объём RAM/VRAM. Фактические digest/size фиксирует evaluate.py через /api/tags.
Скорость скачивания, загрузка весов и GPU-производительность здесь не измерены.
Запуск за 15 минут не обещается. Замер установки: reports/install.json;
повтор выполнен тем же участником с тёплым pip-кэшем, независимый повтор ещё нужен.

## Env, seed, start

Выбрать **новую абсолютную тестовую БД вне data/**, например
`/tmp/photoprint-demo/meetings.db` или `D:\track3-demo\meetings.db`.
Не направлять smoke на рабочие базы. Seed не имеет reset и не меняет «Орбиту».
Существующая БД без маркера тестового набора отклоняется.

```bash
export MEETINGS_MODEL=qwen2.5:7b
export MEETINGS_CONTEXT=8192
export MEETINGS_TIMEOUT=300
export OLLAMA_BASE_URL=http://127.0.0.1:11434
.venv-track3/bin/python scripts/track3/seed.py --db /tmp/photoprint-demo/meetings.db
.venv-track3/bin/python scripts/track3/start.py --db /tmp/photoprint-demo/meetings.db --port 8000
```

PowerShell env: `$env:MEETINGS_MODEL='qwen2.5:7b'`, аналогично другим значениям.
Открыть [встречи](http://127.0.0.1:8000/meetings).

| Вход | Пароль | Роль и видимость |
|---|---|---|
| irina | irina-demo | manager, 3 контрольные встречи, история задач, свои и общие документы, print+binding KPI |
| petr | petr-demo | reader, только свои/общие документы, отдельный тестовый private KPI; закрытые встречи/смета недоступны |

Имена/пароли исключительно демонстрационные. Публичный доступ к этому процессу
не предусмотрен: bind=127.0.0.1. Если основной owner guard включён через
CALLWISE_OWNER_PASSWORD, его вход сохраняется; это отдельная защита кабинета.

start.py запускает существующий app.py и направляет кабинет в соседний
`meetings.cabinet.db`; секрет сессии — `meetings.session.key` (либо заданный
MEETINGS_SECRET). Перезапуск тем же путём сохраняет cookie и состояние. Не менять
секрет посреди проверки. Побочные файлы регистрируются в `*.track3.json`.
Голосовые кнопки в UI остаются, но без весов распознавание не работает.

## Remote gateway и данные

По умолчанию — loopback. Для разрешённого защищённого gateway задать
OLLAMA_BASE_URL и OLLAMA_API_KEY (как минимум 24 символа по общей endpoint policy).
Не сохранять ключ в git/отчётах. Публичный незашифрованный HTTP блокируется;
поддержаны HTTPS или HTTP поверх разрешённого Tailscale WireGuard.
Не включаются env proxy, redirects и cloud-модели; fallback отсутствует.
Проверка адресов общая — providers.ollama.endpoint(), копии policy нет.

**При remote gateway фрагменты документов/расшифровок обрабатываются на машине
хоста модели. Это не полностью локальная обработка на машине пользователя.**
Cloudflare-туннель добавляет внешнего посредника, через которого проходит трафик.
TLS не устраняет участие этого посредника. Host/gateway и их логи/backup включить
в процедуру удаления. Хранение на сервере модели определяется его оператором;
этим репозиторием оно не контролируется. `start-gateway.ps1` не изменялся.

## Проверки

```bash
.venv-track3/bin/python scripts/track3/check.py -q tests/test_meetings.py tests/test_meeting_voice.py tests/test_meeting_voice_mode.py tests/test_llm_gateway.py tests/test_track3*.py
node --check static/meetings.js
node --check static/meetings/track3.js
node --check static/meetings/protocol.js
node --test tests/*.cjs
.venv-track3/bin/python -m playwright install --with-deps chromium
.venv-track3/bin/python -m unittest discover -s tests/ui_track3 -p 'test_browser.py' -v
.venv-track3/bin/python scripts/track3/http_smoke.py --output /tmp/track3-http.json
git diff --check
```

check.py защищает также import-time БД кабинета старых tests, временные БД удаляются
после завершения. HTTP smoke сам поднимает/останавливает продуктовый сервер,
использует временную БД и ручной протокол, не двойник LLM. Проверка нового качества
модели — только следующий отдельный шаг. CI браузера требует доступных системных
сокетов Chromium; в текущей среде он заблокирован до выполнения сценариев.

## Проверка готовности модели без инференса

```bash
.venv-track3/bin/python scripts/track3/doctor.py --output /tmp/track3-doctor-new.json
```

Выходной .json должен быть новым. doctor читает .env этой копии (явные env имеют
приоритет), проверяет frozen-набор, endpoint policy и только /api/version + /api/tags.
Не создаёт БД, не скачивает модели и не вызывает /api/chat. В отчёте — наличие
настроек, safe error type/HTTP status и этап отказа; токены и raw HTTP exceptions
не сохраняются. metadata_ready не означает согласованное окно GPU.

## Настоящая оценка (отдельное окно)

Сначала согласовать с владельцем GPU окно без других тяжёлых запросов. Флаг ниже
является подтверждением оператора, а не автоматическим резервированием GPU.
Не запускать его до согласования.

```bash
.venv-track3/bin/python scripts/live_meetings_check.py --track3 --exclusive-gpu-window --output /tmp/track3-live.json
```

Перед live-прогоном рабочее дерево должно быть чистым; отчёты хранить вне checkout
либо использовать уже согласованный каталог артефактов. Выходной .json не должен
существовать: каждый прогон сохраняет новое первичное наблюдение.

Gold зафиксирован коммитом `9d1c2dc` до любых вызовов модели. Frozen SHA проверяются
перед оценкой. Не перестраивать gold по выходу модели. Отчёт содержит commit,
модель/Ollama version/digest, параметры, время, corpus SHA, исходные predictions,
цитаты, task recall/precision, ошибки и latency. Exit 0=passed, 1=failed/review,
2=not run, 130=interrupted. Checkpoints сохраняются после каждого контроля и вопроса. Отсутствие сервера — **не проверено**, а не успешный тест.

## Браузер через настоящий HTTP

```bash
.venv-track3/bin/python scripts/track3/ui_http_check.py --output /tmp/track3-ui-new.json --artifacts /tmp/track3-ui-new
```

Оба пути новые. Обёртка запускает фактический http_smoke_server.py Codex 1 и его
http_browser_smoke.py без перехвата browser routes. Временная БД изолирована;
сервер завершается в finally. Проверяется UI/API, включая настоящий calendar 409,
две роли, due_text и 360/768/1440 px. **Модель здесь — явно названный двойник**, что
не является результатом Ollama. Логи, HTTP responses и screenshots сохраняются в
artifacts; CI загружает их с семидневным сроком. Локальное ограничение Chromium
не обходится — полный браузерный прогон выполняет разрешённый GitHub runner.

## Остановка и удаление

В терминале сервера Ctrl+C. Убедиться, что uvicorn завершён, затем dry-run:

```bash
.venv-track3/bin/python scripts/track3/cleanup.py --db /tmp/photoprint-demo/meetings.db
.venv-track3/bin/python scripts/track3/cleanup.py --db /tmp/photoprint-demo/meetings.db --confirm-delete
```

Удаляются только заданная маркированная тестовая БД, её sidecars и зарегистрированные
кабинет/секрет. Отдельный отчёт рядом с БД можно явно включить через
`--artifact /tmp/photoprint-demo/report.json`. Рекурсивного удаления нет;
symlinks/relative paths/default data/ отклоняются даже с флагом подтверждения.
Резервные копии и отчёты в других местах удаляются отдельно по RETENTION.md.
Унаследованный `seed_meetings_demo.py --reset` теперь требует явный маркированный
тестовый --db и --confirm-delete; рабочую data/ не удаляет.
