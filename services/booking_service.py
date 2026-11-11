"""Shared booking flow; local demo or explicitly bound cloud calendar repository."""
import json
import uuid
from datetime import datetime, date, timedelta, timezone
from typing import Protocol
from zoneinfo import ZoneInfo
import storage
from services.business_hours import local_instant, within_hours, potential_clocks, schedule_availability


class BookingRepository(Protocol):
    def for_date(self, day: str) -> list[dict]: ...
    def create(self, booking: dict) -> dict: ...


class SQLiteBookingRepository:
    @staticmethod
    def decode(row):
        data = dict(row)
        data["structured_data"] = json.loads(data.get("structured_data") or "{}")
        return data

    def for_date(self, day):
        with storage.connect() as db:
            return [self.decode(row) for row in db.execute("SELECT * FROM bookings WHERE substr(datetime,1,10) = ?", (day,))]

    def create(self, booking):
        with storage.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM bookings WHERE interaction_id = ?", (booking["interaction_id"],)).fetchone()
            if existing:
                return self.decode(existing)
            start = datetime.fromisoformat(booking["datetime"])
            end = start + timedelta(minutes=booking["duration_minutes"])
            for row in db.execute("SELECT * FROM bookings WHERE employee = ?", (booking["employee"],)):
                occupied = datetime.fromisoformat(row["datetime"])
                if start < occupied + timedelta(minutes=row["duration_minutes"]) and occupied < end:
                    raise ValueError("Это время уже занято. Проверьте свободные слоты ещё раз.")
            columns = ("id", "interaction_id", "customer_name", "phone", "service", "datetime", "employee",
                       "duration_minutes", "created_at", "structured_data")
            db.execute(f"INSERT INTO bookings ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                       [json.dumps(booking[key], ensure_ascii=False) if key == "structured_data" else booking[key] for key in columns])
        return booking


class BookingService:
    def __init__(self, business, repository: BookingRepository | None = None):
        self.knowledge = business.knowledge
        self.schedule = business.schedule
        self.repository = repository or SQLiteBookingRepository()
        self.demo = getattr(self.repository, 'demo', True)
        self.tz = ZoneInfo(business.timezone)

    def service(self, name):
        aliases = self.knowledge.get('service_aliases', {})
        matched = []
        for service in self.knowledge.get("services", []):
            if service.get("id") == name or service["name"].casefold() == name.casefold():
                return service
            key = service.get('id', service['name'])
            values = aliases.get(key, []) if isinstance(aliases, dict) else []
            if isinstance(values, list) and any(isinstance(value, str) and value.strip().casefold() == name.strip().casefold() for value in values):
                matched.append(service)
        if len(matched) == 1: return matched[0]
        if len(matched) > 1: raise ValueError('Синоним неоднозначен. Уточните конкретную услугу.')
        raise ValueError("Такой услуги нет в тестовом каталоге.")

    def display_employee(self, employee):
        return next((e["name"] for e in self.knowledge.get("employees", []) if isinstance(e, dict) and e["id"] == employee), employee)

    def check_slots(self, service, day, preferred_time=None, employee=None):
        item = self.service(service)
        target = date.fromisoformat(day)
        if target < datetime.now(self.tz).date():
            raise ValueError("Нельзя записаться на прошедшую дату.")
        employees = item["employees"]
        if employee and employee not in employees:
            raise ValueError("Выбранный мастер не оказывает эту услугу.")
        if preferred_time:
            datetime.strptime(preferred_time, "%H:%M")
        bookings = self.repository.for_date(day)
        slots = []
        clocks = (potential_clocks(self.schedule, target.weekday(), item["duration_minutes"])
                  if schedule_availability(self.knowledge) else self.knowledge.get("slot_times", []))
        for clock in clocks:
            if clock in self.knowledge.get("occupied_times", []) or (preferred_time and clock < preferred_time):
                continue
            start = local_instant(day, clock, self.tz)
            if start is None or start <= datetime.now(self.tz) or not within_hours(start, item["duration_minutes"], self.schedule, self.tz):
                continue
            end = start.astimezone(timezone.utc) + timedelta(minutes=item["duration_minutes"])
            for master in ([employee] if employee else employees):
                if any(b["employee"] == master and start < datetime.fromisoformat(b["datetime"]) + timedelta(minutes=b["duration_minutes"]) and datetime.fromisoformat(b["datetime"]) < end for b in bookings):
                    continue
                slots.append({"service": item.get("id", item["name"]), "datetime": start.isoformat(), "employee": master,
                              "service_name": item["name"], "employee_name": self.display_employee(master)})
        return {"slots": slots, "demo": self.demo, "duration_minutes": item["duration_minutes"]}

    def validate_proposal(self, arguments, context):
        raw = datetime.fromisoformat(arguments["datetime"])
        if raw.tzinfo is None:
            raise ValueError("Datetime требует timezone offset из результата check_slots")
        instant = raw.astimezone(self.tz).isoformat()
        item = self.service(arguments["service"])
        canonical_service = item.get("id", item["name"])
        employees = item["employees"]
        master = arguments.get("employee") or employees[0]
        # Only a slot actually returned earlier to this conversation can be booked.
        seen = [slot for event in context.tool_events if event["name"] == "check_slots" for slot in event.get("result", {}).get("slots", [])]
        if not any(s["datetime"] == instant and s["employee"] == master and s["service"] == canonical_service for s in seen):
            raise ValueError("Сначала проверьте доступность выбранного слота через check_slots.")
        current = self.check_slots(arguments["service"], instant[:10], employee=master)["slots"]
        if not any(s["datetime"] == instant for s in current):
            raise ValueError("Слот уже недоступен. Выберите другое время.")
        return {**{key: arguments[key] for key in ("customer_name", "phone")}, "service": canonical_service,
                "datetime": instant, "employee": master}

    def create_booking(self, arguments, context):
        values = self.validate_proposal(arguments, context)
        return self.repository.create({"id": str(uuid.uuid4()), "interaction_id": context.interaction_id,
            **values, "duration_minutes": self.service(values["service"])["duration_minutes"],
            "structured_data": {"values": dict(arguments), "collected_fields": context.collected_fields,
                                "action_provenance": context.action_provenance},
            "created_at": datetime.now(timezone.utc).isoformat()})
