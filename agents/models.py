"""Serializable agent definition; no provider or repository dependencies."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BusinessContext(StrictModel):
    name: str = Field(min_length=2)
    industry: str
    city: str
    description: str = ""
    opening_hours: str = ""
    timezone: str = "UTC"
    schedule: dict[str, list[dict[str, str]]] = Field(default_factory=dict)
    capabilities: list[str] = Field(default_factory=list)
    knowledge: dict[str, Any] = Field(default_factory=dict)


class Role(StrictModel):
    id: str
    name: str
    description: str
    required_capabilities: list[str] = Field(default_factory=list)


class AgentField(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str
    question: str
    required: bool = True
    data_kind: Literal["user", "business"] = "user"
    allowed_sources: list[Literal["user", "tool", "business_config", "system", "derived"]] = Field(default_factory=lambda: ["user"])
    requires_confirmation: bool = True
    normalization: Literal["text", "digits", "email"] = "text"
    value_pattern: str | None = None
    evidence_patterns: list[str] = Field(default_factory=list)
    tool_paths: dict[str, list[str]] = Field(default_factory=dict)
    business_paths: list[str] = Field(default_factory=list)
    display_values: dict[str, str] = Field(default_factory=dict)


class Scenario(StrictModel):
    id: str
    description: str
    steps: list[str]
    required_tools: list[str] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)


class ToolPolicy(StrictModel):
    name: str
    requires_confirmation: bool = False


class EscalationConfig(StrictModel):
    tool: str = "transfer_to_human"
    explicit_request_patterns: list[str] = Field(default_factory=list)
    acknowledgement: str = "Запрос на перевод сотруднику зафиксирован. Реального соединения пока нет."
    explicit_human_request: Literal["immediate", "disabled"] = "immediate"
    agent_initiated: dict[str, Literal["allowed", "disabled"]] = Field(default_factory=dict)


class FieldValue(StrictModel):
    field_id: str
    value: str
    source: Literal["user", "tool", "business_config", "system", "derived"]
    evidence: dict[str, Any]
    confirmed: bool = False


class ConversationSafety(StrictModel):
    privacy_required: bool = True
    max_turns: int = Field(default=40, ge=5, le=100)
    max_minutes: int = Field(default=15, ge=1, le=60)
    off_topic_limit: int = Field(default=2, ge=1, le=5)
    abuse_limit: int = Field(default=2, ge=1, le=5)
    notice: str = Field(default='', max_length=2000)
    notice_version: str = Field(default='demo-v1', min_length=1, max_length=80)


class AgentConfig(StrictModel):
    id: str = Field(min_length=1)
    name: str
    language: str = Field(default="ru", pattern=r"^[a-z]{2}$")
    greeting: str
    business: BusinessContext
    role: Role
    fields: list[AgentField] = Field(default_factory=list)
    scenarios: list[Scenario] = Field(default_factory=list)
    tools: list[ToolPolicy] = Field(default_factory=list)
    rules: list[str] = Field(default_factory=list)
    escalation: EscalationConfig = Field(default_factory=EscalationConfig)
    safety: ConversationSafety = Field(default_factory=ConversationSafety)

    @model_validator(mode="after")
    def unique_identifiers(self):
        for values in ([f.id for f in self.fields], [s.id for s in self.scenarios], [t.name for t in self.tools]):
            if len(values) != len(set(values)):
                raise ValueError("Идентификаторы полей, сценариев и инструментов должны быть уникальными")
        return self
