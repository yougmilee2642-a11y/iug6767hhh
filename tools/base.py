from dataclasses import dataclass, field
from typing import Callable
from providers.base import ToolSpec


class ToolInputError(ValueError):
    """Validated missing input with a safe user-facing clarification."""
    def __init__(self, message: str, question: str):
        super().__init__(message)
        self.question = question


class FieldEvidenceRequired(ToolInputError):
    def __init__(self, field):
        super().__init__(f"Нет проверенного значения поля «{field.label}» от пользователя.", field.question)
        self.field_id = field.id


@dataclass
class ToolContext:
    interaction_id: str
    config: object
    transcript: list[dict]
    structured_data: dict
    tool_events: list[dict]
    collected_fields: dict = field(default_factory=dict)
    action_provenance: dict = field(default_factory=dict)


@dataclass
class ToolResult:
    data: dict = field(default_factory=dict)
    status: str | None = None
    text: str = ""
    provenance: dict = field(default_factory=dict)


@dataclass
class BusinessTool:
    name: str
    description: str
    parameters: dict
    execute: Callable
    prepare: Callable | None = None
    always_requires_confirmation: bool = False
    read_only: bool = True
    requires_confirmation: bool = False
    risk_level: str = "low"
    kind: str = "action"
    required_capabilities: tuple[str, ...] = ()
    action_fields: tuple[str, ...] = ()
    source_constraints: dict[str, tuple[str, ...]] = field(default_factory=dict)
    action_label: str = ""
    result_schema: dict = field(default_factory=dict)

    def schema(self):
        return ToolSpec(self.name, self.description, self.parameters)
