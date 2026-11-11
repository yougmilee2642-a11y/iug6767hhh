import os


def local_only():
    return os.getenv('CALLWISE_LOCAL_ONLY','false').lower() == 'true'


def uses_local_ai():
    return local_only() or os.getenv('AI_PROVIDER','groq').lower() == 'ollama'


class LocalAIError(RuntimeError):
    def __init__(self, code='unavailable'):
        self.code=code
        super().__init__({'unavailable':'Локальная модель недоступна. Запустите Ollama и проверьте установку модели.',
                          'timeout':'Локальная модель не ответила вовремя.',
                          'invalid_reply':'Локальная модель вернула некорректный ответ.',
                          'missing_weights':'Локальные веса речи ещё не установлены.',
                          'cuda_unavailable':'CUDA недоступна. Проверьте CUDA-сборку PyTorch, драйвер NVIDIA и настройки устройств.',
                          'no_speech':'В записи не обнаружена речь.',
                          'cloud_disabled':'В локальном режиме внешние AI API отключены.'}.get(code,'Ошибка локального AI.'))
