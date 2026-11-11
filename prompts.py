"""Configuration loading and compatibility entry points for the existing app."""
import json
import os
from pathlib import Path
from agents.models import AgentConfig, AgentField
from agents.prompts import build_system_prompt, build_transcription_prompt
from agents.validation import require_valid, InvalidAgentConfig
from services.business_hours import parse_schedule


def load_agent(config: dict | None = None) -> AgentConfig:
    path = Path(os.getenv("AGENT_CONFIG_PATH", str(Path(__file__).parent / "configs" / "beauty_salon.json")))
    if not path.is_absolute():
        path = Path(__file__).parent / path
    agent = AgentConfig.model_validate_json(path.read_text(encoding="utf-8"))
    if config is None:
        return require_valid(agent)
    agent.business.name = config["business_name"]
    agent.business.industry = config["industry"]
    agent.business.city = config["city"]
    agent.business.description = config.get("description", "")
    agent.business.opening_hours = config.get("opening_hours", "")
    agent.business.timezone = config.get("timezone", agent.business.timezone)
    agent.business.schedule = parse_schedule(config.get("schedule") or agent.business.opening_hours)
    agent.business.knowledge["notes"] = config.get("knowledge_base", "")
    if config.get("services"):
        agent.business.knowledge["services"] = json.loads(config["services"])
    agent.language = config.get("language", "ru")
    agent.greeting = config["greeting"]
    existing = {field.id for field in agent.fields}
    questions = config.get("custom_questions", [])
    if any(question["id"] in existing for question in questions):
        raise InvalidAgentConfig({"valid": False, "errors": [{"path": "custom_questions", "code": "duplicate_field",
            "message": "Дополнительное поле не может повторять ID базового поля"}], "warnings": []})
    agent.fields.extend(AgentField(**question) for question in questions)
    return require_valid(AgentConfig.model_validate(agent.model_dump()))
