# Фактические зависимости, модели и заимствования

Проверено 11.11.2026. **Код и веса учитываются отдельно.** Список относится к
реально импортируемому стеку и installer-файлам репозитория, а не к ресерчу.
Текстовые веса не поставляются в git; речевые модели текстовый запуск не скачивает.
Полный перечень установленных Python-дистрибутивов, версий, URL их проектов,
заявленных лицензий и SHA-256 license/notice файлов: reports/environment.json.
Источник — METADATA и файлы самих установленных дистрибутивов, не догадки по имени.
requirements-track3-lock.txt фиксирует прямые и транзитивные версии.

## Основной текстовый код / инструменты

| Компонент | Проверенная версия | Фактический источник лицензии |
|---|---|---|
| FastAPI | 0.115.12 | MIT, classifier и license файла установленного пакета; [PyPI](https://pypi.org/project/fastapi/0.115.12/) |
| Pydantic | 2.11.4 | METADATA/license в environment.json; [PyPI](https://pypi.org/project/pydantic/2.11.4/) |
| Uvicorn | 0.34.2 | METADATA/license; [PyPI](https://pypi.org/project/uvicorn/0.34.2/) |
| HTTPX | 0.28.1 | BSD-3-Clause в METADATA; [PyPI](https://pypi.org/project/httpx/0.28.1/) |
| OpenAI SDK | 1.78.1 | Apache-2.0 в METADATA; импорт старого приложения, не inference provider текстовых meetings |
| edge-tts | 7.0.2 | LGPLv3 classifier; импорт старого приложения, текстовый путь его не вызывает |
| NumPy | 2.2.5 | BSD classifier; включает собственный bundled notice — не сводить всё содержимое wheel к одному имени лицензии |
| pypdf | 5.4.0 | BSD classifier и package license; резервный PDF reader |
| PyMuPDF | 1.25.5 | **AGPL 3.0 или Artifex Commercial License**, явно указано в установленной METADATA |
| pytest | 8.3.5 | MIT METADATA; только тесты |
| Playwright Python | 1.52.0 | Apache-2.0 License-Expression; только тесты |
| Остальные, включая Starlette/httpcore/pydantic-core/google-auth/requests | Точные версии в lock | Каждая отдельная запись environment.json; license files и upstream URLs доступны для проверки |

PyMuPDF добавлен для **уже существующего** block-preserving PDF parser, чтобы
сохранить тесты «Орбиты» без правки чужой логики. Двойное лицензирование подтверждено
также [официальной документацией](https://pymupdf.readthedocs.io/en/latest/about.html)
и package metadata. Решение о подходящем лицензировании продукта ещё не принято;
не утверждаем совместимость будущей закрытой поставки автоматически. Альтернатива
требует согласованной правки PDF parser его владельцем; текущий pypdf fallback
в исходном тесте возвращал один fragment вместо ожидаемых трёх.

Ollama runtime: [код MIT](https://github.com/ollama/ollama/blob/main/LICENSE).
Установленная версия здесь **не наблюдалась**, model/version фиксируются только
при доступном /api/version. Python stdlib/SQLite используют системные поставки;
Python 3.12.14 и платформа записаны в environment.json. JS использует браузерные
API и существующие модули репозитория, нового frontend framework нет. Chromium
не распространяется этим PR; его notices входят в установку браузера тестирования.

## Веса и существующий голосовой путь

| Объект | Версия / фактическая привязка в коде | Источник / результат проверки |
|---|---|---|
| Qwen2.5 7B Instruct, Ollama qwen2.5:7b | Настроенный default, точный установленный digest неизвестен | [официальная Ollama-карточка](https://ollama.com/library/qwen2.5:7b) и [официальные GGUF weights LICENSE](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF/blob/main/LICENSE): Apache-2.0; карточка 4.7 GB Q4_K_M. Не распространять этот вывод на другие размеры Qwen |
| GigaAM **код** | submodule/requirement 7447938d791c4f3e643386ee22c33777004293a5 | [LICENSE на этом commit](https://github.com/salute-developers/GigaAM/blob/7447938d791c4f3e643386ee22c33777004293a5/LICENSE): MIT, прочитан через GitHub API |
| GigaAM **веса** | v3_rnnt.ckpt, URL CDN и expected MD5 0fd2c9a1ff66abd8d32a3a07f7592815 в scripts/install_dual_asr.py | [официальная model card GigaAM-v3](https://huggingface.co/ai-sage/GigaAM-v3/blob/main/README.md) явно указывает MIT, включая rnnt; README закреплённого исходного проекта подтверждает семейство v3. Идентичность конкретного CDN-бинарника и его SHA-256 здесь не проверялись |
| T-one **код** | submodule 3c5b6c015038173840e62cea99e10cdb1c759116 | [LICENSE на commit](https://github.com/voicekit-team/T-one/blob/3c5b6c015038173840e62cea99e10cdb1c759116/LICENSE): Apache-2.0, прочитан через GitHub API |
| T-one **веса** | HF revision 106f3b0b32a9e107eb613312e4ebc61ff3d53926/model.onnx | [официальная model card на revision](https://huggingface.co/t-tech/T-one/blob/106f3b0b32a9e107eb613312e4ebc61ff3d53926/README.md) указывает apache-2.0; bytes/digest не измерены здесь |
| Silero TTS **веса** | models/silero/v5_ru.pt, URL models.silero.ai в installer | [models.yml на e382298](https://github.com/snakers4/silero-models/blob/e382298387332f2bf461fe6eadfde99104611b0c/models.yml) связывает v5_ru с тем же URL. [LICENSE](https://github.com/snakers4/silero-models/blob/e382298387332f2bf461fe6eadfde99104611b0c/LICENSE) озаглавлен Attribution-NonCommercial-ShareAlike 4.0 International; README исключает из общей лицензии только base cis-tts (MIT). Badge сокращает название иначе; точные условия коммерческой поставки требуют решения владельца. Это не MIT по умолчанию |
| Silero VAD / sherpa-onnx / ONNXRuntime / torch / torchaudio | Старые requirements-local*.txt, torch/torchaudio 2.11.0+cu128; sherpa-onnx 1.13.8; onnxruntime 1.23.2 | Только существующий опциональный voice stack; в текстовом окружении не установлены. Фактические wheel notices и версии отдельно проверить при голосовой поставке; старые requirements не менялись |
| WeSpeaker **веса** | wespeaker_en_voxceleb_resnet34_LM.onnx из sherpa release | [код WeSpeaker](https://github.com/wenet-e2e/wespeaker) имеет Apache-2.0, но это не доказывает условия конкретного release-asset и обучающих данных; точный бинарник/notice не проверены |
| pyannote segmentation **веса** | sherpa-onnx-pyannote-segmentation-3-0.tar.bz2, model.onnx из архива | [официальная исходная model card](https://huggingface.co/pyannote/segmentation-3.0): MIT. [официальная sherpa-документация](https://k2-fsa.github.io/sherpa/onnx/speaker-diarization/models.html) связывает этот точный release asset с исходной моделью. LICENSE внутри фактически прочитанного архива — MIT; archive/notice SHA-256 и bytes записаны в reports/pyannote-notice.json. Runtime-модель не устанавливалась |

Все фактические URL voice-assets читаются в scripts/install_dual_asr.py; runtime
проверяет файлы в models/, а installer пишет dual-asr-manifest.json с SHA-256/bytes.
Этого манифеста в текущем текстовом окружении нет. Не подменять его предполагаемыми
хешами. Состояние проверки голосовых лицензий — **не завершено**, это риск выпуска,
даже если текстовый сценарий технически проходит без этих весов.

## Заимствования

Существующие файлы проекта сохранены; чужие продуктовые изменения включены
только merge их веток (точные SHA/пути в отчёте интеграции). Новый seed и evaluator
написаны для этого выпуска, синтетический корпус не заимствует реальные документы
или фотографии. Новых моделей/алгоритмов из стороннего ресерча не добавляли.
В репозитории не найден общий LICENSE собственного продукта: права его поставки
не устанавливаются этим документом. Источники лицензий не заменяют решение владельца
о конкретной форме распространения; неизвестные условия явно оставлены неизвестными.


Дополнительная проверка Silero закреплена на upstream commit
`e382298387332f2bf461fe6eadfde99104611b0c`: README blob
`8bb4ccae1d285a5b32bc5b3648a0a027d112a2dc`, LICENSE blob
`cbe5ad1670406e4402217edfb82d2c56af7e8631`, models.yml blob
`79159440c2a7ea2e5ef962489cbcdddc14624cdc`. Совпадение названия и URL v5_ru
проверено отдельно от лицензии кода. Сопровождающему передано
[замечание с воспроизведением](https://github.com/yougmilee2642-a11y/iug6767hhh/pull/4#issuecomment-6797897713).
Текстовый сценарий этих весов не использует. Подтверждённые ограничения не означают,
что решение о лицензировании всей коммерческой голосовой поставки уже принято.


## Шрифты нового UI «Фокус»

Авторский rebrand `1ea0a5a` (в main `0e99e32`) реально подключает Jost400/500/600
через Google Fonts CSS в static/meetings.html. [Upstream OFL.txt](https://github.com/google/fonts/blob/c30b221beb0c1da59d563feb91ec8656a1fa972a/ofl/jost/OFL.txt)
проверен на google/fonts commit `c30b221beb0c1da59d563feb91ec8656a1fa972a`,
license blob `85b6b99d12470b54d8cbc919bc45102d99f23437`: SIL Open Font License1.1.
Это привязка источника лицензии, не идентификация текущего CDN binary: HTML CDN URL
не закрепляет binary hash/version. При self-host нужно сохранить notice/лицензию
проверенного конкретного файла; Codex3 шрифты не скачивал в поставку и UI не менял.

Futura PT упомянут в CSS font-family; поставляемый бинарник и право его распространения
не подтверждены. Одно CSS-имя не означает, что эти веса/файлы включены в репозиторий,
и лицензия Jost на Futura PT не переносится. Внешний font fetch и автономный fallback
переданы владельцу UI; это реальные assets нового интерфейса, не технологии ресерча.

Фактический browser CI зафиксировал Google Fonts CSS и два Jost CDN URL с `/v20/`;
reports/focus-font-requests.json. Версия пути наблюдалась, но не закреплена HTML;
SHA конкретных WOFF2 и их embedded notices в этом аудите не проверены.


## Окружение CPU-регрессии v2 (E0)

Для полного существующего pytest добавлены только CPU-библиотеки: PyAV16.1.0,
SciPy1.15.3, SoundFile0.13.1 и зависимости cffi2.1.1/pycparser3.12. Модели не
устанавливались/не запускались: ToneStream-тест использует scripted Model, decode
проверяет синтетический WAV. Версии, METADATA, ссылки на upstream/PyPI и SHA256
notice-файлов записаны в reports/v2-e0-dependencies.json. PyAV объявляет BSD-3-Clause,
SoundFile — BSD3, SciPy включает bundled notices, cffi — MIT-0, pycparser — BSD3.
Лицензии FFmpeg/libsndfile в binary wheels нельзя выводить из лицензии Python wrapper;
их отдельная проверка остаётся в реестре ограничений поставки.
