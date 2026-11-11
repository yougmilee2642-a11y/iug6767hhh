import logging
from agents.models import AgentConfig
from agents.validation import require_valid
from prompts import load_agent
from storage import get_config
from services.agent_repository import AgentRepository


class AgentService:
    def __init__(self, repository=None):
        self.repository = repository or AgentRepository()

    def demo(self):
        config = load_agent(get_config())
        self.repository.save(config, source="demo", status="active")
        return config

    def resolve(self, agent_id=None):
        if not agent_id:
            return self.demo()
        item = self.repository.get(agent_id)
        if item and item["source"] == "demo":
            return self.demo()
        if not item:
            # Also supports first request naming the default demo before it was seeded.
            demo = self.demo()
            if demo.id == agent_id:
                return demo
            raise LookupError("Агент не найден")
        if item["status"] != "active":
            raise ValueError("Для разговора сначала активируйте валидного агента")
        return require_valid(AgentConfig.model_validate(item["config"]))

    def activate(self, agent_id):
        item = self.repository.get(agent_id)
        if not item:
            raise LookupError("Агент не найден")
        config = require_valid(AgentConfig.model_validate(item["config"]))
        self.repository.set_status(config.id, "active")
        logging.getLogger("callwise.builder").info("agent_activated agent=%s", config.id)
        return self.repository.get(config.id)
