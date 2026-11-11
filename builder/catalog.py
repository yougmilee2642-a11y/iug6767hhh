from agents.models import Scenario


SCENARIOS = {
    "booking": Scenario(id="booking", description="Запись в тестовый календарь", required_tools=["check_slots", "create_booking"], required_fields=["customer_name", "phone", "service", "datetime", "employee"], required_capabilities=["booking"], steps=[
        "Определи услугу по каталогу, используй ID услуги и сотрудника в инструментах.",
        "Относительную дату вычисляй по текущей дате в timezone бизнеса. Проверь check_slots. Для 'после шести' передавай preferred_time=18:00; после означает нижнюю границу времени. Не придумывай свободное время.",
        "Уточняй по одному недостающему полю. Для записи передай create_booking выбранный проверенный слот, имя и телефон. Сервер запросит подтверждение."]),
    "faq": Scenario(id="faq", description="Ответы по данным бизнеса", steps=["Отвечай только по structured knowledge. Если информации нет, честно сообщи об этом."]),
    "pricing": Scenario(id="pricing", description="Услуги и цены", steps=["Цены, валюта и длительность берутся исключительно из services. Не придумывай скидки."]),
    "opening_hours": Scenario(id="opening_hours", description="Рабочие часы", steps=["Используй только business.schedule и timezone. Пустой день означает выходной."]),
    "human_handoff": Scenario(id="human_handoff", description="Запрос сотрудника", steps=["Явный запрос человека обрабатывает сервер немедленно."], required_tools=["transfer_to_human"], required_capabilities=["human_handoff"]),
}

STYLE_RULES = {"brief": "Отвечай кратко, один вопрос за раз.", "friendly": "Общайся спокойно и доброжелательно, один вопрос за раз.", "formal": "Используй вежливый деловой тон, один вопрос за раз."}

HUMAN_PATTERNS = [r"(?:дайте|позовите|соедините|хочу|нужен|нужна).{0,40}(?:человек(?:а|ом)?|сотрудник|оператор|администратор|менеджер|владел(?:ец|ьц|иц))", r"не хочу.{0,30}(?:бот|робот)", r"^(?:человек|оператор)[.!?\s]*$"]
