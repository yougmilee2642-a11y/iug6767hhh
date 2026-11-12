# Локальная установка

Текстовый запуск без голосовых моделей описан в [README](../README.md). Ниже — полный локальный голосовой профиль для Windows. Нужны Python 3.11, Ollama и NVIDIA GPU для настроек CUDA по умолчанию.

## Установка

Выполните из корня проекта:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-local-gpu.txt
.venv/Scripts/python.exe -m pip install -r requirements-local.txt
.venv/Scripts/python.exe -m pip check
.venv/Scripts/python.exe scripts/install-local-models.py
ollama pull qwen3:4b-instruct
```

Загрузка моделей требует интернета и места на диске. Приложение само не скачивает отсутствующие веса.

Если `.env` ещё нет, скопируйте `.env.local.example` в `.env`. Укажите:

```dotenv
AI_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3:4b-instruct
MEETINGS_MODEL=qwen3:4b-instruct
LOCAL_STT_ENGINE=tone_gigaam
LOCAL_STT_DEVICE=cuda
LOCAL_TTS_DEVICE=cuda
```

Остальные настройки локального режима сохраните из примера. Для CPU задайте `LOCAL_STT_DEVICE=cpu` и `LOCAL_TTS_DEVICE=cpu`; скорость зависит от оборудования. При явном выборе CUDA недоступность GPU возвращается как ошибка, без скрытого переключения на CPU.

## Запуск и проверка

```powershell
./start-local.ps1
```

Откройте [кабинет](http://127.0.0.1:8000/) или [встречи](http://127.0.0.1:8000/meetings). `start-local.ps1` использует существующую `.venv`, включает локальный режим и при необходимости запускает Ollama в фоне. Остановка — `Ctrl+C`.

```powershell
.venv/Scripts/python.exe scripts/check-speech-gpu.py
.venv/Scripts/python.exe scripts/check-local-llm.py --model qwen3:4b-instruct
.venv/Scripts/python.exe scripts/smoke-local.py
```

Эти команды обращаются к настоящим моделям и могут занимать время. Проверка готовности сервера доступна по `/api/health`. Успешный текстовый тест не подтверждает работу микрофона и фильтра голоса.

## Хранение и удалённая модель

- `models/` содержит веса распознавания и синтеза; Ollama использует собственное хранилище.
- `data/` содержит рабочие базы и локальные результаты проверок.
- `.env` и `secrets/` содержат настройки и секреты. Не включайте их в коммиты и архивы.
- Для изолированной демонстрации встреч используйте отдельную `demo-db/` по инструкции README.

Если текстовая модель работает на другом компьютере, задайте адрес шлюза в `OLLAMA_BASE_URL` и ключ в `OLLAMA_API_KEY`. `start-gateway.ps1` запускается на машине с Ollama, `start-local.ps1` — на клиенте. Передавайте ключ лично; текст отправляется на машину шлюза. Настройка шлюза не устанавливает голосовые модели на клиенте.

Подробнее: [локальная модель](LOCAL_LLM.md), [распознавание и фильтр голоса](LOCAL_ASR.md), [GPU](GPU_VOICE.md).
