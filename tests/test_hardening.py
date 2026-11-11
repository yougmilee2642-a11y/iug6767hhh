import inspect
import json
from datetime import date, timedelta
from types import SimpleNamespace as NS
import pytest
from fastapi.testclient import TestClient
import app as app_module
import storage
from agents.models import AgentField, AgentConfig
from agents.runtime import AgentRuntime, new_interaction
from agents.fields import collect_user
from agents.validation import validate_agent, InvalidAgentConfig
from agents.factory import create_runtime
from agents.prompts import build_system_prompt
from prompts import load_agent
from providers.base import ConversationMessage, ToolSpec, ToolCall, ModelReply
from providers.groq import GroqProvider
from tools.registry import default_registry, ToolRegistry, ToolDefinition
from tools.base import BusinessTool, ToolResult
from tools.booking import booking_tools
from tools.handoff import handoff_tool
from services.booking_service import BookingService
from services.business_hours import parse_schedule, local_instant
from zoneinfo import ZoneInfo


class MockLLMProvider:
    def __init__(self, *replies):
        self.replies = iter(replies)
        self.messages = []
    def complete(self, messages, tools):
        assert all(isinstance(m, ConversationMessage) for m in messages)
        assert all(isinstance(t, ToolSpec) for t in tools)
        self.messages.append(messages)
        return next(self.replies)


def tool_call(name, args):
    return ModelReply(tool_calls=[ToolCall(name, name, args)])


def day():
    return (date.today() + timedelta(days=2)).isoformat()


def args():
    return {"customer_name": "Лёша", "phone": "+375291234567", "service": "маникюр",
            "datetime": day() + "T18:30:00+03:00", "employee": "Анна"}


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "db.sqlite")
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    storage.initialize_db()
    monkeypatch.setattr(app_module, "send_application_email", lambda *_: False)
    return load_agent(), TestClient(app_module.app)


def runtime_state(config, extra=None, text="Меня зовут Лёша. Мой телефон +375291234567"):
    config = config.model_copy(deep=True)
    if extra:
        config.fields.append(extra)
    service = BookingService(config.business)
    runtime = AgentRuntime(config, MockLLMProvider(), [*booking_tools(service, config.fields), handoff_tool()])
    state = new_interaction(config)
    state["transcript"].append({"role": "user", "content": text})
    runtime.dispatch(ToolCall("slots", "check_slots", {"service": "маникюр", "date": day()}), state)
    return runtime, state, service


def allergy():
    return AgentField(id="allergy", label="Аллергия", question="Есть ли аллергия?",
        evidence_patterns=[r"у меня аллергия на\s+(?P<value>[^.!?;]+)"])


def prepare(runtime, state, values):
    result, answer = runtime.dispatch(ToolCall("prepare", "create_booking", values), state)
    runtime.respond(state, answer)
    return result, answer


def test_01_invented_dynamic_field_rejected(environment):
    runtime, state, service = runtime_state(environment[0], allergy())
    result, answer = prepare(runtime, state, {**args(), "additional_fields": {"allergy": "нет"}})
    assert result["field_id"] == "allergy"
    assert "allergy" not in state["collected_fields"] and state["pending_action"] is None
    assert service.repository.for_date(day()) == [] and answer == allergy().question


def test_02_explicit_dynamic_declaration_accepted(environment):
    runtime, state, service = runtime_state(environment[0], allergy(),
        "Меня зовут Лёша. Мой телефон +375291234567. У меня аллергия на латекс.")
    result, _ = prepare(runtime, state, {**args(), "additional_fields": {"allergy": "латекс"}})
    assert result["confirmation_required"]
    item = state["collected_fields"]["allergy"]
    assert item["value"] == "латекс" and item["source"] == "user" and not item["confirmed"]
    runtime.turn(state, "да")
    saved = service.repository.for_date(day())[0]["structured_data"]
    assert saved["values"]["allergy"] == "латекс" and saved["collected_fields"]["allergy"]["confirmed"]


def test_03_master_is_not_customer_name(environment):
    runtime, state, service = runtime_state(environment[0], text="Хочу к мастеру Анне. Мой телефон +375291234567")
    result, _ = prepare(runtime, state, {**args(), "customer_name": "Анна"})
    assert result["field_id"] == "customer_name" and "customer_name" not in state["collected_fields"]
    assert service.repository.for_date(day()) == []


def test_04_confirmation_includes_dynamic_fields_and_catalog(environment):
    runtime, state, _ = runtime_state(environment[0], allergy(),
        "Меня зовут Лёша. Мой телефон +375291234567. У меня аллергия на латекс.")
    result, answer = prepare(runtime, state, {**args(), "additional_fields": {"allergy": "латекс"}})
    assert "Аллергия: латекс" in answer and "Цена: 50" in answer and "Длительность, минут: 60" in answer
    assert all(str(value) in answer for value in result["proposal"].values())


def test_05_no_consent_no_booking(environment):
    runtime, state, service = runtime_state(environment[0])
    prepare(runtime, state, args())
    runtime.provider = MockLLMProvider(ModelReply("Когда удобно?"))
    runtime.turn(state, "да, но другую дату")
    assert service.repository.for_date(day()) == [] and state["pending_action"] is None


def test_06_read_only_check_needs_no_confirmation(environment):
    runtime, state, _ = runtime_state(environment[0])
    assert state["tool_events"][0]["result"]["slots"] and state["pending_action"] is None
    assert runtime.tools["check_slots"].read_only


@pytest.mark.parametrize("mutation,code", [
    (lambda c: c["tools"].append({"name": "magic_unknown_tool"}), "unknown_tool"),
    (lambda c: c["escalation"].update(tool="unknown_handoff"), "unknown_escalation_tool"),
    (lambda c: c["fields"].append(c["fields"][0]), "schema"),
    (lambda c: c["business"].update(timezone="Mars/Nowhere"), "invalid_timezone"),
    (lambda c: c["business"].update(schedule={"0": [{"start": "18:00", "end": "09:00"}]}), "invalid_hours"),
    (lambda c: c["business"].update(capabilities=["human_handoff"]), "missing_capability"),
    (lambda c: c["scenarios"][0].update(required_fields=["unknown_field"]), "missing_field_reference"),
    (lambda c: c["role"].update(required_capabilities=["payments"]), "missing_capability"),
    (lambda c: c["business"]["knowledge"].update(services=[]), "dependency"),
    (lambda c: c.update(language=""), "schema"),
    (lambda c: c.update(language="pl"), "unsupported_language"),
    (lambda c: c["fields"][2].update(tool_paths={"check_slots": ["slots.*.nonexistent"]}), "unknown_source_path"),
])
def test_07_to_10_invalid_configs_are_structured_and_fail_before_turn(environment, mutation, code):
    candidate = environment[0].model_dump()
    mutation(candidate)
    report = validate_agent(candidate)
    assert not report["valid"] and code in {e["code"] for e in report["errors"]}
    assert all(e["path"] is not None and e["message"] for e in report["errors"])
    response = environment[1].post("/api/agent/validate", json=candidate)
    assert response.status_code == 200 and not response.json()["valid"]
    if code != "schema":
        with pytest.raises(InvalidAgentConfig):
            create_runtime(AgentConfig.model_validate(candidate), MockLLMProvider())


def test_11_config_hours_timezone_change_without_code(environment):
    config = environment[0]
    config.business.opening_hours = "24/7"
    config.business.schedule = parse_schedule("24/7")
    config.business.timezone = "Europe/Warsaw"
    config.business.knowledge["slot_times"] = ["22:00"]
    assert validate_agent(config)["valid"]
    slots = BookingService(config.business).check_slots("маникюр", "2027-07-02")["slots"]
    assert slots and slots[0]["datetime"].endswith("+02:00")
    assert "Europe/Warsaw" in build_system_prompt(config)


def test_12_closes_at_17_and_duration_must_fit(environment):
    config = environment[0]
    config.business.opening_hours = "08:00–17:00"
    config.business.schedule = parse_schedule(config.business.opening_hours)
    config.business.knowledge["slot_times"] = ["16:00", "16:30", "17:00", "18:30"]
    slots = BookingService(config.business).check_slots("маникюр", day())["slots"]
    assert {s["datetime"][11:16] for s in slots} == {"16:00"}


@pytest.mark.parametrize("text", ["Хочу поговорить с человеком.", "человек",
                                  "не хочу говорить с ботом",
                                  "Я не хочу разговаривать с ботом, соедините с человеком."])
def test_13_explicit_handoff_is_immediate(environment, text):
    runtime = create_runtime(environment[0], MockLLMProvider())
    state = new_interaction(environment[0])
    reply = runtime.turn(state, text)
    assert reply["status"] == "escalated" and runtime.provider.messages == []
    assert state["escalation"]["reason"] == "explicit_user_request"


def test_14_handoff_persists_known_fields_context_agent(environment):
    runtime, state, _ = runtime_state(environment[0])
    prepare(runtime, state, args())
    runtime.turn(state, "Оператор")
    with storage.connect() as db:
        row = dict(db.execute("SELECT * FROM escalations").fetchone())
    assert row["agent_id"] == environment[0].id and row["reason_type"] == "explicit_user_request"
    customer = json.loads(row["customer_data"])
    assert customer["customer_name"] == "Лёша" and customer["collected_fields"]["phone"]["source"] == "user"
    assert row["summary"] and row["created_at"] and customer["transcript"]


def test_15_runtime_neutral_mock_contract(environment):
    provider = MockLLMProvider(tool_call("check_slots", {"service": "маникюр", "date": day()}))
    runtime = create_runtime(environment[0], provider)
    state = new_interaction(environment[0])
    runtime.turn(state, "Маникюр")
    assert provider.messages
    assert all("tool_calls" not in message and "tool_call_id" not in message for message in state["llm_history"])
    source = inspect.getsource(AgentRuntime)
    assert "Groq" not in source and '"function"' not in source


def test_16_groq_adapter_accepts_same_neutral_contract():
    received = {}
    def create(**options):
        received.update(options)
        return NS(choices=[NS(message=NS(content="Ответ", tool_calls=[]))])
    provider = GroqProvider(NS(chat=NS(completions=NS(create=create))))
    messages = [ConversationMessage("assistant", calls=[ToolCall("id", "lookup", {"q": "a"})]),
                ConversationMessage("tool", call_id="id", result={"ok": True})]
    reply = provider.complete(messages, [ToolSpec("lookup", "Lookup", {"type": "object"})])
    assert reply.text == "Ответ" and received["messages"][0]["tool_calls"][0]["function"]["name"] == "lookup"
    assert received["messages"][1]["tool_call_id"] == "id"


def test_arbitrary_write_tool_obeys_metadata_not_its_name(environment):
    config = environment[0].model_copy(deep=True)
    config.fields = [AgentField(id="recipient", label="Получатель", question="Кто получатель?")]
    config.scenarios = []
    config.role.required_capabilities = []
    config.business.capabilities = []  # Generic package tool, no human-handoff adapter.
    config.escalation.explicit_human_request = "disabled"
    config.escalation.agent_initiated = {}
    from agents.models import ToolPolicy
    config.tools = [ToolPolicy(name="send_package", requires_confirmation=False)]
    saved = []
    tool = BusinessTool("send_package", "Доставка", {"type": "object", "properties": {"recipient": {"type": "string"}}, "required": ["recipient"]},
        lambda args, ctx: (saved.append(args) or ToolResult({"action_result": args}, "completed", "Заявка создана.")),
        prepare=lambda args, ctx: ToolResult(dict(args)), read_only=False, risk_level="high", action_fields=("recipient",))
    runtime = AgentRuntime(config, MockLLMProvider(tool_call("send_package", {"recipient": "Лёша"})), [tool])
    state = new_interaction(config)
    assert runtime.turn(state, "Получатель: Лёша")["status"] == "awaiting_confirmation"
    assert saved == []
    assert runtime.turn(state, "да")["status"] == "completed" and saved == [{"recipient": "Лёша"}]


@pytest.mark.parametrize("field", [
    AgentField(id="email", label="Email", question="Какой email?", normalization="email", value_pattern=r"[^\s@]+@[^\s@]+\.[^\s@]+"),
    AgentField(id="address", label="Адрес", question="Какой адрес?"),
    AgentField(id="car_model", label="Автомобиль", question="Какая модель?"),
    AgentField(id="order_number", label="Номер заказа", question="Какой номер заказа?"),
])
def test_arbitrary_fields_collect_via_bound_step(environment, field):
    runtime, state, _ = runtime_state(environment[0], field)
    result, answer = prepare(runtime, state, args())
    assert result["field_id"] == field.id and answer == field.question
    value = "Alex@Example.com" if field.normalization == "email" else "Ответ клиента"
    runtime.provider = MockLLMProvider(tool_call("create_booking", {**args(), "additional_fields": {
        field.id: value.casefold() if field.normalization == "email" else value}}))
    reply = runtime.turn(state, value)
    assert reply["status"] == "awaiting_confirmation"
    assert state["collected_fields"][field.id]["evidence"]["kind"] == "collection_answer"
    assert field.label in reply["text"]


def test_confirmation_flag_cannot_bypass_consent(environment):
    runtime, state, service = runtime_state(environment[0])
    data, _ = runtime.dispatch(ToolCall("forged", "create_booking", args()), state, confirmed=True)
    assert "error" in data and service.repository.for_date(day()) == []


def test_full_declaration_as_answer_to_collection_question(environment):
    config = environment[0]
    runtime = create_runtime(config, MockLLMProvider(ModelReply("Назовите телефон для связи.")))
    state = new_interaction(config)
    runtime.respond(state, "Как вас зовут?")
    runtime.turn(state, "Меня зовут Алексей.")
    assert state["collected_fields"]["customer_name"]["value"] == "Алексей"


def test_business_config_source_has_provenance(environment):
    config = environment[0]
    config.fields.append(AgentField(id="currency", label="Валюта", question="Валюта?", data_kind="business",
        allowed_sources=["business_config"], business_paths=["services.*.currency"]))
    runtime, state, _ = runtime_state(config)
    prepare(runtime, state, args())
    assert state["collected_fields"]["currency"]["source"] == "business_config"
    assert state["action_provenance"]["price"]["source"] == "business_config"


def test_mutated_proposal_does_not_execute(environment):
    runtime, state, service = runtime_state(environment[0])
    prepare(runtime, state, args())
    state["pending_action"]["arguments"]["phone"] = "+375299999999"
    runtime.provider = MockLLMProvider(ModelReply("Нужно повторно уточнить телефон."))
    runtime.turn(state, "да")
    assert service.repository.for_date(day()) == []


def test_unsafe_sources_and_forged_evidence_rejected(environment):
    config = environment[0].model_copy(deep=True)
    config.fields[0].allowed_sources = ["tool"]
    config.fields[0].tool_paths = {"check_slots": ["slots.*.employee"]}
    assert not validate_agent(config)["valid"]
    runtime, state, _ = runtime_state(environment[0], text="Мастер Анна. Мой телефон +375291234567")
    state["collected_fields"]["customer_name"] = {"field_id": "customer_name", "value": "Анна",
        "source": "user", "confirmed": True, "evidence": {"kind": "declaration", "turn": 1,
        "text": state["transcript"][1]["content"], "pattern": "(?P<value>Анна)"}}
    result, _ = prepare(runtime, state, {**args(), "customer_name": "Анна"})
    assert result["field_id"] == "customer_name"


def test_tool_data_and_catalog_values_need_no_literal_user_utterance(environment):
    runtime, state, _ = runtime_state(environment[0])
    result, _ = prepare(runtime, state, {**args(), "price": 1})
    assert result["proposal"]["price"] == 50
    assert state["collected_fields"]["employee"]["source"] == "tool"


def test_agent_initiated_policy_and_repeated_errors(environment):
    runtime, state, _ = runtime_state(environment[0])
    call = ToolCall("handoff", "transfer_to_human", {"reason": "Не поддерживается", "summary": "Model claim",
                                                   "reason_type": "unsupported_scenario"})
    result, _ = runtime.dispatch(call, state)
    assert result["escalation"]["reason_type"] == "unsupported_scenario"
    assert result["escalation"]["summary"] != "Model claim"
    runtime, state, _ = runtime_state(environment[0])
    runtime.config.escalation.agent_initiated["unsupported_scenario"] = "disabled"
    assert "error" in runtime.dispatch(call, state)[0]
    failure = ToolCall("failure", "transfer_to_human", {"reason": "Tool failure", "summary": "", "reason_type": "tool_failure"})
    assert "error" in runtime.dispatch(failure, state)[0]
    state["tool_events"].extend([{"name": "x", "result": {"error": "failure"}}] * 2)
    assert runtime.dispatch(failure, state)[0]["escalation"]["reason_type"] == "tool_failure"


def test_dst_ambiguous_and_nonexistent_slots_are_not_offered():
    zone = ZoneInfo("Europe/Warsaw")
    assert local_instant("2027-03-28", "02:30", zone) is None
    assert local_instant("2027-10-31", "02:30", zone) is None
    assert local_instant("2027-07-01", "02:30", zone).utcoffset() == timedelta(hours=2)


def test_migration_is_idempotent_and_keeps_old_rows(environment):
    identifier = storage.save_application({"name": "Старый клиент", "car": "BMW"}, [])
    storage.initialize_db()
    storage.initialize_db()
    assert storage.legacy_list_applications()[0]["id"] == identifier
    with storage.connect() as db:
        columns = {r[1] for r in db.execute("PRAGMA table_info(bookings)")}
    assert "structured_data" in columns and "allergy" not in columns


def test_actual_iteration_one_tables_upgrade_without_data_loss(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "old.sqlite")
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    with storage.connect() as db:
        db.executescript("""CREATE TABLE bookings (id TEXT PRIMARY KEY, interaction_id TEXT UNIQUE,
            customer_name TEXT, phone TEXT, service TEXT, datetime TEXT, employee TEXT,
            duration_minutes INTEGER, created_at TEXT, UNIQUE(datetime, employee));
            CREATE TABLE escalations (interaction_id TEXT PRIMARY KEY, reason TEXT, summary TEXT,
            customer_data TEXT, created_at TEXT);""")
        db.execute("INSERT INTO bookings VALUES (?,?,?,?,?,?,?,?,?)",
            ("old-booking", "old-interaction", "Клиент", "+375290000000", "маникюр",
             "2026-01-01T10:00:00+03:00", "Анна", 60, "2026-01-01"))
        db.execute("INSERT INTO escalations VALUES (?,?,?,?,?)", ("old", "reason", "summary", "{}", "2026-01-01"))
    storage.initialize_db()
    with storage.connect() as db:
        assert db.execute("SELECT customer_name, structured_data FROM bookings").fetchone()[1] == "{}"
        assert db.execute("SELECT reason_type, agent_id FROM escalations").fetchone()[0] == "legacy"


def test_custom_form_cannot_shadow_core_field(environment):
    config = storage.get_config()
    config["custom_questions"] = [{"id": "customer_name", "label": "Мастер", "question": "Какой мастер?"}]
    response = environment[1].put("/api/config", json=config)
    assert response.status_code == 422 and response.json()["detail"]["errors"][0]["code"] == "duplicate_field"


def test_generic_display_uses_snapshot_and_actual_saved_result(environment):
    runtime, state, _ = runtime_state(environment[0], allergy(),
        "Меня зовут Лёша. Мой телефон +375291234567. У меня аллергия на латекс.")
    prepare(runtime, state, {**args(), "additional_fields": {"allergy": "латекс"}})
    runtime.turn(state, "да")
    state["structured_data"]["allergy"] = "изменённый черновик"
    public = storage.public_interaction(state)
    assert {f["label"]: f["value"] for f in public["display_fields"]}["Аллергия"] == "латекс"
    assert "pending_action" not in public


def test_email_smtp_contract_with_dynamic_field(environment, monkeypatch):
    sent = []
    class FakeSMTP:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def starttls(self): pass
        def login(self, *args): pass
        def send_message(self, message): sent.append(message)
    from services.notifications import send_application_email
    monkeypatch.setattr(app_module.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setenv("SMTP_HOST", "example.test")
    config = storage.get_config()
    config["notification_email"] = "business@example.test"
    assert send_application_email({"structured_data": {"allergy": "латекс"},
        "agent_config": {"fields": [{"id": "allergy", "label": "Аллергия"}]}}, config)
    assert "Аллергия: латекс" in sent[0].get_content()


def test_invalid_persisted_agent_cannot_start_conversation(environment, monkeypatch, tmp_path):
    config = environment[0].model_dump()
    config["tools"].append({"name": "unknown_tool"})
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setenv("AGENT_CONFIG_PATH", str(path))
    response = environment[1].post("/api/conversations")
    assert response.status_code == 422
    assert response.json()["detail"]["valid"] is False
