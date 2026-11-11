"""Disposable UI smoke environment. Real HTTP/UI, deterministic model, no outbound email.
Run: python tests/browser_smoke_server.py (localhost:8001). Stop with Ctrl+C.
"""
import sys
import os
import tempfile
from pathlib import Path
from datetime import date, datetime, timedelta
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['TELEGRAM_ENABLED'] = 'false'
os.environ['CALLWISE_OWNER_PASSWORD'] = ''
import storage
from providers.base import ModelReply, ToolCall
from test_builder import MockBuilder, draft


class RoleAwareSmokeBuilder(MockBuilder):
    def generate(self, business, errors):
        value = draft()
        if not business.employees:
            value.update(scenarios=['pricing'],tools=[])
        value['role_name'] = business.desired_role
        value['agent_name'] = f"AI-сотрудник {business.business_name}"
        return value


class MorningClock(datetime):
    @classmethod
    def now(cls, tz=None):
        current = super().now(tz)
        return current.replace(hour=9, minute=0, second=0, microsecond=0)


class SmokeProvider:
    def complete(self, messages, tools):
        if not tools:
            from evaluation_doubles import DeterministicAgent
            return DeterministicAgent().complete(messages,tools)
        latest = next(m.text for m in reversed(messages) if m.role == "user")
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        schema = next(t.parameters for t in tools if t.name == "create_booking")
        generated = "enum" in schema["properties"]["service"]
        service = schema["properties"]["service"]["enum"][0] if generated else "маникюр"
        employee = schema["properties"]["employee"]["enum"][0] if generated else "Анна"
        if "маникюр" in latest.casefold() or "консультац" in latest.casefold() or "можно сегодня" in latest.casefold():
            short_window = '16:30' in latest
            call = ToolCall("slots", "check_slots", {"service": service,
                "date": date.today().isoformat() if short_window else tomorrow,
                "preferred_time": "16:30" if short_window else "18:00"})
        else:
            offered = [slot for message in messages if message.role == 'tool' for slot in (message.result or {}).get('slots', [])]
            chosen = next((s for s in offered if s['datetime'][11:16] in latest), offered[0] if offered else None)
            call = ToolCall("proposal", "create_booking", {"customer_name": "Тест", "phone": "+375290000000",
                "service": service, "datetime": chosen['datetime'] if chosen else tomorrow + "T18:30:00+03:00",
                "employee": chosen['employee'] if chosen else employee,
                "additional_fields": {} if generated else {"allergy": "латекс"}})
        return ModelReply(tool_calls=[call])


if __name__ == "__main__":
    import uvicorn
    with tempfile.TemporaryDirectory(prefix="callwise-browser-") as directory:
        storage.DATA_DIR = Path(directory)
        storage.DB_PATH = storage.DATA_DIR / "test.sqlite"
        import app
        storage.initialize_db()  # app may already be imported by shared test fixtures.
        config = storage.get_config()
        config["notification_email"] = ""
        config["custom_questions"] = [{"id": "allergy", "label": "Аллергия", "question": "Есть ли аллергия?", "required": True}]
        storage.save_config(config)
        app.get_provider = SmokeProvider
        app.get_builder_provider = RoleAwareSmokeBuilder
        from evaluation.service import EvaluationService
        from evaluation_doubles import components
        app.get_evaluation_service = lambda: EvaluationService(components_factory=components)
        import services.booking_service as calendar
        calendar.datetime = MorningClock  # Only isolated smoke; today 16:30 must not already be past at night.
        app.send_application_email = lambda *_: False
        uvicorn.run(app.app, host="127.0.0.1", port=8001)
