> Track 3 text setup and release status are appended below; the original gateway/voice guide is retained.

# Callwise: команда, нейросеть на одном компьютере

Исходный код и веса моделей — разные вещи. Код общий (GitHub), а нейросеть (Ollama)
работает только на компьютере хоста (Лёши). Коллеги подключаются к ней через
**LLM-шлюз с ключом**, и Ollama им ставить не нужно.

```
 компьютер коллеги                          компьютер хоста
 CallWise (свой код, своя ветка)            start-gateway.ps1
   OLLAMA_BASE_URL + OLLAMA_API_KEY  ──▶  шлюз :11500 (проверка ключа) ──▶ Ollama 127.0.0.1:11434
              (Tailscale / HTTPS-туннель)
```

## Хост: открыть нейросеть

1. Установить [Tailscale](https://tailscale.com/download), войти и пригласить коллег
   в свою сеть (tailnet): admin console → Users → Invite.
2. Запустить:
   ```powershell
   .\start-gateway.ps1
   ```
   Скрипт поднимет Ollama (только на 127.0.0.1), запустит шлюз на Tailscale-адресе
   и напечатает три строки для `.env` коллег: `OLLAMA_BASE_URL`, `OLLAMA_API_KEY`,
   `OLLAMA_MODEL`. Передайте их **лично** (мессенджер), а не через GitHub.
3. При первом запуске Windows спросит про брандмауэр для `python.exe`: разрешите
   доступ для частных сетей.
4. Окно держать открытым, компьютер должен быть включён и не уходить в сон.

Другие режимы:

| Команда | Когда |
|---|---|
| `.\start-gateway.ps1` | **Рекомендуется.** Tailscale: постоянный адрес, шифрование, ничего не торчит в интернет |
| `.\start-gateway.ps1 -Mode cloudflare` | У коллег не ставится вообще ничего. Нужен `cloudflared` у хоста; адрес `*.trycloudflare.com` меняется при каждом перезапуске |
| `.\start-gateway.ps1 -Mode lan` | Все в одной сети/офисе. Трафик не шифруется, поэтому клиент CallWise его не примет без HTTPS (только для своих экспериментов) |
| `.\start-gateway.ps1 -NewKey` | Выпустить новый ключ, например если старый утёк. Старый сразу перестаёт работать |

Ключ хранится в `secrets/llm_gateway.token` (папка в `.gitignore`).

## Коллега: подключиться

1. `git clone`, создать `.venv`, `pip install -r requirements-local.txt`.
2. Установить Tailscale и принять приглашение хоста (в режиме cloudflare не нужно).
3. Скопировать `.env.local.example` → `.env` и вписать строки, присланные хостом:
   ```
   OLLAMA_BASE_URL=http://100.x.y.z:11500
   OLLAMA_API_KEY=...
   OLLAMA_MODEL=qwen2.5:3b
   ```
4. `.\start-local.ps1`: увидев удалённый адрес, скрипт не ищет локальную Ollama,
   проверяет доступность шлюза и запускает CallWise.

Ollama у коллеги не нужна. **Речь** (распознавание T-one + GigaAM и озвучка Silero)
пока работает локально у каждого: для голосового режима веса речи нужны в `models/`.
Текстовые функции (встречи, протоколы, задачи, чат) работают только со шлюзом.

## Безопасность

- Ollama слушает только `127.0.0.1`; наружу открыт лишь шлюз.
- Шлюз требует `Authorization: Bearer <ключ>` (256 бит, сравнение за постоянное время)
  и пропускает только инференс и чтение (`/api/chat`, `/api/generate`, `/api/embed`,
  `/api/show`, `/api/tags`, `/api/version`, `/api/ps`). Скачивание, удаление и создание
  моделей, а также `:cloud`-модели запрещены.
- Клиент (`providers/ollama.py`) отправляет данные на нелокальный адрес только при
  заданном `OLLAMA_API_KEY` и только по HTTPS или в сеть Tailscale (100.64.0.0/10,
  `*.ts.net`). Обычный HTTP через интернет или LAN отклоняется.
- Тексты встреч и звонков коллег обрабатываются на компьютере хоста. Через Tailscale
  они остаются в вашей частной сети; в режиме cloudflare проходят через Cloudflare.
  Используйте синтетические данные.

## Производительность

Одна видеокарта на всех: при одновременных запросах они встают в очередь
(`OLLAMA_NUM_PARALLEL=2`, одна модель в памяти). На 8 ГБ VRAM, где параллельно работают
речь и LLM хоста, 2–3 активных пользователя — разумный предел.

## Общий код

Приватный Git-репозиторий и отдельные ветки. В git не попадают `.env`, `models/`,
`downloads/`, `.venv/`, `secrets/`, рабочая `data/`. Не коммитить токены Telegram,
почты, ключ шлюза, пароли и реальные разговоры. Нельзя синхронизировать живую SQLite-базу
через облачную папку.

Официальные источники:

- https://docs.ollama.com/faq — адрес сервера и хранение весов.
- https://docs.ollama.com/api/authentication — локальный API Ollama без аутентификации.
- https://tailscale.com/kb/1017/install — установка Tailscale.
- https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/ — быстрые туннели.


# Track 3 — совместная разработка

База cb2614b86f3b83636e670c83a0afb8f4c9d6c3c3. У каждого отдельная копия/ветка.
Владение, полный пакет выпуска и критерии: docs/track3-team/README.md.
CONTRACT в этой директории — проект для согласования: оригинал отсутствовал на remote.
Редактор общего контракта после согласования — Codex 3.

| Поставка | PR | Ответственный |
|---|---|---|
| Core/миграции/роли/календарь | [#2](https://github.com/yougmilee2642-a11y/iug6767hhh/pull/2) | Claude |
| Knowledge/overview | [#1](https://github.com/yougmilee2642-a11y/iug6767hhh/pull/1) | Codex 2 |
| UI | [#3](https://github.com/yougmilee2642-a11y/iug6767hhh/pull/3) | Codex 1 |
| Release/evaluation | codex/track3-release, PR пока не создан | Codex 3 |
| Integration | codex/track3-integration, PR пока не создан | Codex 3 |

Интеграция: core → knowledge → UI → release, затем новые owner-hardening коммиты
обычным merge, без rebase уже слитой истории. main не переписывается и не менялся.
Интеграционные ошибки чужой логики отправлять автору с запросом/ответом, SHA,
ожидаемым поведением и командой воспроизведения. Только Claude меняет общую схему
и регистрацию зависимых импортов. Поддержка gateway использует общую endpoint policy,
не отдельную ослабленную копию. start-gateway.ps1 не трогать: пользовательская правка.

Исходные три PR прочитаны через GitHub, пути проверены по diff и API. В них нет
app.py/providers/ASR/старых requirements/start-gateway.ps1; backend textutil включён
как helper проверки модели из PR Claude. Codex 3 не редактировал эти файлы вручную.
Новые зависимости — только requirements-track3*.txt.

Команды и тестовый запуск: docs/track3-release/RUNBOOK.md. Все release-smoke БД
временные; destructive smoke по data/ запрещён. CI CPU на интеграционной ветке и PR;
live-модель только отдельной явной командой после согласования GPU-окна. Независимый
повтор установки и окно GPU пока не согласованы: task в codex3 handoff, не выполненные
действия. Passed/failed/not run разделены в docs/track3-release/STATUS.md.
