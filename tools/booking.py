from tools.base import BusinessTool, ToolResult, ToolInputError
from services.booking_service import BookingService
from services.business_hours import minutes, potential_clocks, schedule_availability, validate_schedule
import math
import re


def validate_booking_dependencies(config):
    errors = []
    knowledge = config.business.knowledge
    services = knowledge.get("services")
    if not isinstance(services, list) or not services:
        return ["Booking capability требует непустой каталог services"]
    names = set()
    for service in services:
        try:
            if not isinstance(service["name"], str) or not service["name"].strip() or service["name"].strip().casefold() in names:
                raise ValueError()
            names.add(service["name"].strip().casefold())
            if type(service["duration_minutes"]) is not int or not 1 <= service["duration_minutes"] <= 1440:
                raise ValueError()
            if not isinstance(service["employees"], list) or not service["employees"] or not all(isinstance(e, str) and e.strip() for e in service["employees"]):
                raise ValueError()
            if type(service["price"]) not in (int, float) or not math.isfinite(service["price"]) or service["price"] < 0 or not service.get("currency"):
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            errors.append("Каталог требует name, price/currency, duration_minutes и employees")
    if any(isinstance(s, dict) and "id" in s for s in services):
        employees = knowledge.get("employees", [])
        try:
            ids = [s["id"] for s in services]
            employee_ids = [e["id"] for e in employees]
            employee_names = [e["name"].strip().casefold() for e in employees]
            if not employee_ids or len(set(ids)) != len(ids) or len(set(employee_ids)) != len(employee_ids) or len(set(employee_names)) != len(employee_names):
                raise ValueError()
            if any(not re.fullmatch(r"[a-z][a-z0-9_]*", value) for value in ids + employee_ids):
                raise ValueError()
            if any(set(s["employees"]) - set(employee_ids) for s in services):
                raise ValueError()
        except (ValueError, KeyError, TypeError, AttributeError):
            errors.append("Generated каталог требует уникальные stable service/employee IDs и корректные ссылки сотрудников")
    try:
        if schedule_availability(knowledge):
            validate_schedule(config.business.schedule)
            for service in services:
                if not isinstance(service, dict):
                    continue
                duration = service.get("duration_minutes")
                if type(duration) is int and 1 <= duration <= 1440 and not any(
                        potential_clocks(config.business.schedule, day, duration) for day in range(7)):
                    errors.append(f"Для услуги «{service.get('name', '?')}» нет ни одного потенциального рабочего слота: длительность превышает рабочие окна или бизнес закрыт.")
            clocks = []
        else:
            clocks = knowledge["slot_times"]
            if not isinstance(clocks, list) or not clocks:
                raise ValueError()
        for clock in [*clocks, *knowledge.get("occupied_times", [])]:
            minutes(clock)
    except (ValueError, KeyError, TypeError):
        errors.append("Booking capability требует корректное расписание или legacy slot_times HH:MM")
    import storage
    if not storage.database_path().is_file():
        errors.append("SQLiteBookingRepository не инициализирован")
    else:
        try:
            with storage.connect() as db:
                db.execute("SELECT structured_data FROM bookings LIMIT 0")
        except Exception:
            errors.append("SQLiteBookingRepository недоступен или требует миграции")
    return errors


def booking_tools(service: BookingService, fields=()):
    def check(arguments, context):
        data = service.check_slots(arguments["service"], arguments["date"], arguments.get("preferred_time"), arguments.get("employee"))
        data["intent"] = "Запись на услугу"
        data["structured_data"] = {"service": arguments["service"], "date": arguments["date"]}
        clocks = sorted({slot["datetime"][11:16] for slot in data["slots"]})
        employees = sorted({service.display_employee(slot["employee"]) for slot in data["slots"]})
        visible=', '.join(clocks[:4])+('; есть и другое время' if len(clocks)>4 else '')
        text = (f"На {arguments['date']} доступны {visible}. Мастера: {', '.join(employees)}. Какое время выбираете?"
                if clocks else "На эту дату подходящих свободных слотов нет. Какую другую дату проверим?")
        if any(e["name"] == "check_slots" and e["arguments"] == arguments and "slots" in e["result"] for e in context.tool_events):
            text = ""
            data["instruction"] = "Эти слоты уже предлагались. Учти выбор клиента; уточни только одно недостающее поле. Не повторяй предложение времени."
        return ToolResult(data, text=text)

    def prepare(arguments, context):
        values = service.validate_proposal(arguments, context)
        extras = arguments.get("additional_fields", {})
        for field in fields:
            if field.id not in values:
                value = extras.get(field.id)
                if value is not None:
                    values[field.id] = value
        item = service.service(values["service"])
        values.update(price=item["price"], currency=item["currency"], duration_minutes=item["duration_minutes"])
        provenance = {key: {"source": "business_config", "evidence": {"service": item["name"], "property": key}}
                      for key in ("price", "currency", "duration_minutes")}
        return ToolResult(values, provenance=provenance)

    def create(arguments, context):
        result = service.create_booking(arguments, context)
        saved = result["structured_data"]["values"]
        if not service.demo:
            from integrations.booking import public_booking
            confirmed = result['calendar_status'] == 'confirmed'
            text = (f"Запись подтверждена календарём: {service.service(result['service'])['name']}, {result['datetime'][:10]} в {result['datetime'][11:16]}, мастер {service.display_employee(result['employee'])}."
                    if confirmed else "Календарь не подтвердил запись. Менеджеру нужно проверить её статус; не создавайте повторную запись.")
            if confirmed and result['crm_status'] not in ('synced', 'not_configured'):
                text += ' Передача записи в CRM пока не подтверждена.'
            return ToolResult({'booking': {**public_booking(result), 'structured_data': result['structured_data']},
                               'structured_data': saved, 'action_result': saved if confirmed else {},
                               'intent': 'Запись на услугу'}, status='completed' if confirmed else 'escalated', text=text)
        return ToolResult({"booking": result, "structured_data": saved, "action_result": saved, "intent": "Запись на услугу"},
                          status="completed", text=f"Запись создана в тестовом календаре: {service.service(result['service'])['name']}, {result['datetime'][:10]} в {result['datetime'][11:16]}, мастер {service.display_employee(result['employee'])}.")

    result = [
        BusinessTool("check_slots", "Проверить тестовое расписание. Возвращает только доступные слоты. preferred_time — нижняя граница HH:MM.",
            {"type": "object", "properties": {"service": {"type": "string"}, "date": {"type": "string", "description": "YYYY-MM-DD"}, "preferred_time": {"type": "string"}, "employee": {"type": "string"}}, "required": ["service", "date"], "additionalProperties": False}, check,
            required_capabilities=("booking",), result_schema={"type": "object", "properties": {
                "slots": {"type": "array", "items": {"type": "object", "properties": {
                    key: {"type": "string"} for key in ("service", "datetime", "employee")}}},
                "duration_minutes": {"type": "integer"}, "demo": {"type": "boolean"}}}),
        BusinessTool("create_booking", "Подготовить запись на проверенный слот. Сервер запросит подтверждение и только после него сохранит запись.",
            {"type": "object", "properties": {
                **{key: {"type": "string"} for key in ["customer_name", "phone", "service", "datetime", "employee"]},
                "price": {"type": "number", "title": "Цена"}, "currency": {"type": "string", "title": "Валюта"},
                "duration_minutes": {"type": "integer", "title": "Длительность, минут"},
                "additional_fields": {"type": "object", "properties": {f.id: {"type": "string", "description": f.label} for f in fields if f.id not in {"customer_name", "phone", "service", "datetime", "employee"}}, "additionalProperties": False}
            }, "required": ["customer_name", "phone", "service", "datetime"], "additionalProperties": False}, create, prepare, True,
            read_only=False, requires_confirmation=True, risk_level="high", required_capabilities=("booking",),
            action_fields=("customer_name", "phone", "service", "datetime", "employee"),
            source_constraints={"customer_name": ("user",), "phone": ("user",)},
            action_label="создать запись в тестовом календаре")
    ]
    if not service.demo:
        result[0].description = 'Проверить расписание подключённого календаря бизнеса. При недоступности не предлагать вымышленные слоты.'
        result[1].action_label = 'создать запись в календаре бизнеса и передать её в CRM, если CRM подключена'
    # Generated catalog identities are opaque, not display names. Legacy demo stays compatible.
    ids = [s["id"] for s in service.knowledge.get("services", []) if "id" in s]
    employees = [e["id"] for e in service.knowledge.get("employees", []) if isinstance(e, dict)]
    if ids:
        for tool in result:
            tool.parameters["properties"]["service"]["enum"] = ids
            tool.parameters["properties"]["service"]["description"] = "ID услуги из business.knowledge.services; не название"
            if employees:
                tool.parameters["properties"]["employee"]["enum"] = employees
    return result
