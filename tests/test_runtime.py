import inspect
from datetime import date, timedelta
import pytest
import storage
from agents.models import AgentConfig
from agents.runtime import AgentRuntime, new_interaction
from agents.prompts import build_system_prompt
from prompts import load_agent
from providers.base import ModelReply, ToolCall
from providers.groq import GroqProvider
from tools.base import BusinessTool, ToolResult
from tools.booking import booking_tools
from tools.handoff import handoff_tool
from services.booking_service import BookingService


class MockProvider:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.requests = []
    def complete(self, messages, tools):
        self.requests.append((messages, tools))
        return next(self.responses)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    storage.initialize_db()
    config = load_agent()
    state = new_interaction(config)
    service = BookingService(config.business)
    return config, state, service, [*booking_tools(service, config.fields), handoff_tool()]


def call(name, args):
    return ModelReply(tool_calls=[ToolCall(name + "-1", name, args)])


def tomorrow():
    return (date.today() + timedelta(days=1)).isoformat()


def proposal():
    return {"customer_name": "Лёша", "phone": "+375291234567", "service": "маникюр",
            "datetime": tomorrow() + "T18:30:00+03:00", "employee": "Анна"}


def prepared(setup):
    config, state, service, tools = setup
    provider = MockProvider(call("check_slots", {"service": "маникюр", "date": tomorrow(), "preferred_time": "18:00"}),
                            call("create_booking", proposal()))
    runtime = AgentRuntime(config, provider, tools)
    runtime.turn(state, "Хочу завтра после шести на маникюр")
    response = runtime.turn(state, "На 18:30. Меня зовут Лёша. Мой телефон +375291234567")
    return runtime, state, service, response


def test_agent_config_validates_and_roundtrips(setup):
    config = setup[0]
    assert AgentConfig.model_validate_json(config.model_dump_json()) == config
    assert config.language == "ru"
    duplicate = config.model_dump()
    duplicate["fields"].append(duplicate["fields"][0])
    with pytest.raises(ValueError):
        AgentConfig.model_validate(duplicate)


def test_prompt_uses_config_business_and_role(setup):
    config = setup[0].model_copy(deep=True)
    config.business.name = "Библиотека"
    config.role.name = "библиотекарь"
    prompt = build_system_prompt(config)
    assert "Библиотека" in prompt and "библиотекарь" in prompt


def test_runtime_handles_arbitrary_config_and_tool(setup):
    config, state, _, _ = setup
    data = config.model_dump()
    data.update(id="library", name="Библиотекарь", fields=[], scenarios=[], tools=[{"name": "reserve_book"}], escalation={"explicit_request_patterns": [], "explicit_human_request": "disabled"})
    # This arbitrary-tool fixture has no handoff adapter/capability.
    data["business"]["capabilities"] = []
    data["role"]["required_capabilities"] = []
    config = AgentConfig.model_validate(data)
    state = new_interaction(config)
    tool = BusinessTool("reserve_book", "Запрос книги", {"type": "object", "properties": {}},
                        lambda args, context: ToolResult({"structured_data": {"book": "Алгоритмы"}}, "completed", "Книга отложена."))
    provider = MockProvider(call("reserve_book", {}))
    reply = AgentRuntime(config, provider, [tool]).turn(state, "Отложите книгу")
    assert reply["complete"] and state["structured_data"]["book"] == "Алгоритмы"
    source = inspect.getsource(AgentRuntime)
    assert "beauty" not in source and "car" not in source and "BookingService" not in source


def test_check_slots_returns_only_available_times(setup):
    result = setup[2].check_slots("маникюр", tomorrow(), "18:00")
    assert {s["datetime"][11:16] for s in result["slots"]} == {"18:30", "19:30"}


def test_booking_is_prepared_but_not_created_before_confirmation(setup):
    _, state, service, reply = prepared(setup)
    assert reply["status"] == "awaiting_confirmation"
    assert service.repository.for_date(tomorrow()) == []
    assert state["tool_events"][0]["name"] == "check_slots"
    assert state["tool_events"][-1]["result"]["confirmation_required"]


def test_explicit_confirmation_persists_booking(setup):
    runtime, state, service, _ = prepared(setup)
    reply = runtime.turn(state, "Да, подтверждаю")
    assert reply["complete"] and reply["status"] == "completed"
    bookings = service.repository.for_date(tomorrow())
    assert len(bookings) == 1 and bookings[0]["customer_name"] == "Лёша"
    assert state["tool_events"][-1]["confirmed"]
    runtime.turn(state, "да")
    assert len(service.repository.for_date(tomorrow())) == 1
    storage.save_interaction(state)
    assert storage.get_interaction(state["id"])["structured_data"]["booking_id"] == bookings[0]["id"]


@pytest.mark.parametrize("text", ["да, но на 19:30", "нет", "не подтверждаю", "давайте завтра", "я сказал да раньше"])
def test_ambiguous_confirmation_does_not_execute(setup, text):
    runtime, state, service, _ = prepared(setup)
    runtime.provider = MockProvider(ModelReply("Уточним время. Когда удобно?"))
    runtime.turn(state, text)
    assert service.repository.for_date(tomorrow()) == []


@pytest.mark.parametrize("text", ["Переведите меня на оператора.", "Я хочу поговорить с человеком.", "Соедините меня с человеком.", "Оператор"])
def test_explicit_handoff_does_not_call_model(setup, text):
    config, state, _, tools = setup
    provider = MockProvider()
    reply = AgentRuntime(config, provider, tools).turn(state, text)
    assert reply["status"] == "escalated" and reply["complete"]
    assert "реального соединения" in reply["text"]
    assert provider.requests == []
    with storage.connect() as db:
        row = db.execute("SELECT * FROM escalations").fetchone()
    assert row["reason"] and row["summary"] and row["created_at"]
    assert state["escalation"]["customer_data"]["transcript"][-2]["content"] == text


def test_handoff_cancels_pending_booking(setup):
    runtime, state, service, _ = prepared(setup)
    runtime.turn(state, "Соедините с сотрудником")
    assert state["status"] == "escalated" and state["pending_action"] is None
    assert state["escalation"]["customer_data"]["customer_name"] == "Лёша"
    assert service.repository.for_date(tomorrow()) == []


def test_cannot_book_unchecked_or_invented_slot(setup):
    config, state, service, tools = setup
    provider = MockProvider(call("create_booking", proposal()), ModelReply("Сначала проверю время. Какой день?"))
    AgentRuntime(config, provider, tools).turn(state, "Запишите без подтверждения")
    assert "error" in state["tool_events"][0]["result"]
    assert service.repository.for_date(tomorrow()) == []


def test_confirmation_stays_required_even_if_config_disables_it(setup):
    config = setup[0]
    config.tools[1].requires_confirmation = False
    _, state, service, reply = prepared(setup)
    assert reply["status"] == "awaiting_confirmation"
    assert service.repository.for_date(tomorrow()) == []


def test_double_booking_and_overlap_are_rejected(setup):
    runtime, state, service, _ = prepared(setup)
    runtime.turn(state, "да")
    slots = service.check_slots("маникюр", tomorrow(), "18:00", "Анна")["slots"]
    assert all(s["datetime"][11:16] != "18:30" for s in slots)


def test_model_receives_tool_results(setup):
    config, state, _, tools = setup
    provider = MockProvider(call("check_slots", {"service": "маникюр", "date": tomorrow()}), ModelReply("Есть время. Когда удобно?"))
    AgentRuntime(config, provider, tools).turn(state, "Маникюр завтра")
    assert state["llm_history"][-2]["role"] == "tool"
    assert "slots" in state["llm_history"][-2]["result"]
    AgentRuntime(config, provider, tools).turn(state, "Когда удобно?")
    assert any(m.role == "tool" and "slots" in m.result for m in provider.requests[-1][0])


def test_groq_provider_contract_without_network():
    from types import SimpleNamespace as NS
    kwargs = {}
    def create(**options):
        kwargs.update(options)
        return NS(choices=[NS(message=NS(content=None, tool_calls=[NS(id="1", function=NS(name="check_slots", arguments='{"service":"маникюр"}'))]))])
    provider = GroqProvider(NS(chat=NS(completions=NS(create=create))))
    reply = provider.complete([{"role": "user", "content": "Маникюр"}], [{"type": "function"}])
    assert reply.tool_calls[0].name == "check_slots"
    assert kwargs["parallel_tool_calls"] is False


def test_invented_phone_is_rejected(setup):
    config, state, service, tools = setup
    state["transcript"].append({"role": "user", "content": "Меня зовут Лёша"})
    runtime = AgentRuntime(config, MockProvider(), tools)
    runtime.dispatch(ToolCall("slots", "check_slots", {"service": "маникюр", "date": tomorrow()}), state)
    data, _ = runtime.dispatch(ToolCall("invented", "create_booking", proposal()), state)
    assert data["field_id"] == "phone" and "Телефон" in data["error"]
    assert state["pending_action"] is None
    assert service.repository.for_date(tomorrow()) == []


def test_required_extra_field_is_validated_and_preserved(setup):
    from agents.models import AgentField
    config, state, service, _ = setup
    config.fields.append(AgentField(id="allergy", label="Аллергия", question="Есть ли аллергия?"))
    tools = [*booking_tools(service, config.fields), handoff_tool()]
    runtime = AgentRuntime(config, MockProvider(), tools)
    state["transcript"].append({"role": "user", "content": "Меня зовут Лёша. Мой телефон +375291234567"})
    runtime.dispatch(ToolCall("slots", "check_slots", {"service": "маникюр", "date": tomorrow()}), state)
    data, question = runtime.dispatch(ToolCall("proposal", "create_booking", proposal()), state)
    assert "Аллергия" in data["error"]
    runtime.respond(state, question)
    runtime.provider = MockProvider(call("create_booking", {**proposal(), "additional_fields": {"allergy": "нет"}}))
    response = runtime.turn(state, "нет")
    assert response["status"] == "awaiting_confirmation"
    runtime.turn(state, "Да")
    assert state["structured_data"]["allergy"] == "нет"


def test_operator_negation_does_not_handoff(setup):
    config, state, _, tools = setup
    provider = MockProvider(ModelReply("Хорошо. Какая услуга нужна?"))
    reply = AgentRuntime(config, provider, tools).turn(state, "Не нужен оператор, помогите записаться")
    assert reply["status"] == "active"


def test_master_preference_does_not_allow_model_handoff(setup):
    config, state, _, tools = setup
    state["transcript"].append({"role": "user", "content": "Мастер Анна"})
    data, _ = AgentRuntime(config, MockProvider(), tools).dispatch(ToolCall("bad", "transfer_to_human", {"reason": "Выбор мастера", "summary": "Анна"}), state)
    assert "error" in data and state["escalation"] is None
