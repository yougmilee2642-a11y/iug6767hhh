"""Configuration-driven weekly business hours; keys 0..6 are Mon..Sun."""
import json
import re
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def parse_schedule(value):
    if isinstance(value, dict):
        return value
    text = value.strip()
    if text == "24/7":
        return {str(day): [{"start": "00:00", "end": "24:00"}] for day in range(7)}
    if text.startswith("{"):
        return json.loads(text)
    # Compatibility with the previous daily-hours form; no invented closing-time default.
    match = re.fullmatch(r"(?:Ежедневно\s+)?(\d{2}:\d{2})\s*[–—-]\s*(\d{2}:\d{2})(?:,.*)?", text, re.I)
    if not match:
        raise ValueError("Часы работы: нужен JSON по дням 0–6 или 24/7.")
    return {str(day): [{"start": match[1], "end": match[2]}] for day in range(7)}


def minutes(clock, allow_end=False):
    if allow_end and clock == "24:00":
        return 1440
    if not re.fullmatch(r"\d{2}:\d{2}", clock):
        raise ValueError("Время должно быть HH:MM")
    parsed = time.fromisoformat(clock)
    return parsed.hour * 60 + parsed.minute


def validate_schedule(schedule):
    if not schedule:
        raise ValueError("Укажите расписание по дням 0–6; [] означает выходной.")
    for day, windows in schedule.items():
        if day not in {str(n) for n in range(7)} or not isinstance(windows, list):
            raise ValueError("Дни расписания: строки от 0 до 6")
        previous_end = -1
        for window in windows:
            if set(window) != {"start", "end"}:
                raise ValueError("Интервал должен содержать start/end")
            start, end = minutes(window["start"]), minutes(window["end"], True)
            if not start < end or start < previous_end:
                raise ValueError("Интервалы должны быть отсортированы, не пересекаться и иметь start < end")
            previous_end = end


def local_instant(day, clock, zone: ZoneInfo):
    naive = datetime.fromisoformat(f"{day}T{clock}:00")
    values = []
    for fold in (0, 1):
        aware = naive.replace(tzinfo=zone, fold=fold)
        back = aware.astimezone(timezone.utc).astimezone(zone)
        if back.replace(tzinfo=None) == naive and aware.utcoffset() not in [v.utcoffset() for v in values]:
            values.append(aware)
    # Do not silently choose one of two DST instants or book a nonexistent local time.
    return values[0] if len(values) == 1 else None


def potential_clocks(schedule, weekday, duration_minutes, step_minutes=30):
    """Prototype starts anchored at each opening; duration must fit one whole window."""
    clocks = set()
    for window in schedule.get(str(weekday), []):
        opening = minutes(window["start"])
        closing = minutes(window["end"], True)
        for start in range(opening, closing - duration_minutes + 1, step_minutes):
            clocks.add(f"{start // 60:02d}:{start % 60:02d}")
    return sorted(clocks)


def schedule_availability(knowledge):
    # Compatibility: saved Iteration 2 generated catalogs also use schedule slots,
    # while legacy display-name catalogs retain their explicitly configured times.
    services = knowledge.get("services", [])
    return knowledge.get("availability_mode") == "schedule_30m" or (
        bool(services) and all(isinstance(s, dict) and "id" in s for s in services))


def within_hours(start, duration_minutes, schedule, zone):
    local = start.astimezone(zone)
    end = (start.astimezone(timezone.utc) + timedelta(minutes=duration_minutes)).astimezone(zone)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    for window in schedule.get(str(local.weekday()), []):
        opening = midnight + timedelta(minutes=minutes(window["start"]))
        closing = midnight + timedelta(minutes=minutes(window["end"], True))
        if opening <= local and end <= closing and local < end:
            return True
    return False
