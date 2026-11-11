from dataclasses import dataclass, field
from typing import Protocol, Any


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ModelReply:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass
class ConversationMessage:
    role: str
    text: str = ""
    calls: list[ToolCall] = field(default_factory=list)
    call_id: str | None = None
    result: dict[str, Any] | None = None


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict


class LLMProvider(Protocol):
    def complete(self, messages: list[ConversationMessage], tools: list[ToolSpec]) -> ModelReply: ...
