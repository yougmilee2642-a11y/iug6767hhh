from agents.runtime import AgentRuntime
from agents.validation import require_valid
from tools.registry import default_registry


def create_runtime(config, provider, registry=None):
    registry = registry or default_registry()
    require_valid(config, registry)
    return AgentRuntime(config, provider, registry.resolve_for_agent(config), registry=registry)
