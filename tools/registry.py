"""Small registry of trusted implementations and their contracts (not a plugin framework)."""
from dataclasses import dataclass, field
from typing import Callable
from tools.base import BusinessTool


@dataclass
class ToolDefinition:
    name: str
    factory: Callable
    required_capabilities: tuple[str, ...] = ()
    validate_dependencies: Callable = lambda config: []
    read_only: bool = True
    requires_confirmation: bool = False
    risk_level: str = "low"
    kind: str = "action"


class ToolRegistry:
    def __init__(self):
        self.definitions = {}

    def register(self, definition):
        if definition.name in self.definitions:
            raise ValueError(f"Инструмент уже зарегистрирован: {definition.name}")
        self.definitions[definition.name] = definition
        return self

    def get(self, name):
        if name not in self.definitions:
            raise ValueError(f"Неизвестный инструмент: {name}")
        return self.definitions[name]

    def resolve_for_agent(self, config):
        tools = []
        for policy in config.tools:
            definition = self.get(policy.name)
            errors = definition.validate_dependencies(config)
            if errors:
                raise ValueError("; ".join(errors))
            tool = definition.factory(config)
            if not isinstance(tool, BusinessTool) or tool.name != policy.name:
                raise ValueError(f"Неверная реализация инструмента: {policy.name}")
            tool.read_only = definition.read_only
            tool.requires_confirmation = definition.requires_confirmation
            tool.risk_level = definition.risk_level
            tool.kind = definition.kind
            tool.required_capabilities = definition.required_capabilities
            tools.append(tool)
        return tools

    @classmethod
    def from_tools(cls, tools):
        registry = cls()
        for tool in tools:
            registry.register(ToolDefinition(tool.name, lambda config, t=tool: t,
                tool.required_capabilities, read_only=tool.read_only,
                requires_confirmation=tool.requires_confirmation or tool.always_requires_confirmation,
                risk_level=tool.risk_level, kind=tool.kind))
        return registry


def default_registry():
    from tools.callback import callback_tool, validate_callback_dependencies
    from tools.booking import booking_tools, validate_booking_dependencies
    from tools.handoff import handoff_tool
    from services.booking_service import BookingService
    from integrations.booking import repository_for
    registry = ToolRegistry()
    for index, name in enumerate(("check_slots", "create_booking")):
        registry.register(ToolDefinition(name,
            lambda config, i=index: booking_tools(BookingService(config.business, repository_for(config)), config.fields)[i],
            ("booking",), validate_booking_dependencies, read_only=index == 0,
            requires_confirmation=index == 1, risk_level="low" if index == 0 else "high"))
    registry.register(ToolDefinition("transfer_to_human", lambda config: handoff_tool(),
        ("human_handoff",), read_only=False, kind="escalation", risk_level="medium"))
    registry.register(ToolDefinition('save_callback_request', lambda config: callback_tool(),
        ('call_intake',), validate_callback_dependencies, read_only=False, requires_confirmation=True, risk_level='medium'))
    return registry
