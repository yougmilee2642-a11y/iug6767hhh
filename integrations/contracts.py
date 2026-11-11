from typing import Protocol


class IntegrationError(ValueError):
    """Safe message only; never expose HTTP bodies, credentials or webhook URLs."""
    def __init__(self, code, uncertain=False):
        self.code = code
        self.uncertain = uncertain
        super().__init__({
            'disabled': 'Облачные интеграции отключены. Запись во внешний календарь не выполнена.',
            'config': 'Подключение календаря/CRM не настроено. Обратитесь к владельцу бизнеса.',
            'unavailable': 'Календарь/CRM недоступны. Нельзя подтвердить результат операции.',
            'conflict': 'Время занято или запись изменена. Нужна проверка менеджером.',
            'busy': 'Запись уже обрабатывается. Проверьте её статус чуть позже.',
            'consent': 'Обработка остановлена клиентом. Новая передача в календарь/CRM запрещена.',
            'uncertain': 'Результат записи требует проверки. Не создавайте вторую запись.',
        }.get(code, 'Ошибка интеграции. Нужна проверка менеджером.'))


class CalendarAdapter(Protocol):
    def busy(self, calendar_ids: list[str], start: str, end: str) -> dict[str, list[dict]]: ...
    def get(self, calendar_id: str, event_id: str) -> dict | None: ...
    def insert(self, calendar_id: str, event: dict) -> dict: ...


class CRMAdapter(Protocol):
    def find(self, booking_id: str) -> str | None: ...
    def create(self, booking: dict) -> str: ...
