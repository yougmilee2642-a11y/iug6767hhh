import hashlib
import json
import logging
import uuid
from pydantic import ValidationError
from agents.models import AgentConfig
from agents.validation import validate_agent, require_valid
from builder.models import BuilderDraft
from builder.mapping import map_draft
from builder.preview import preview
from services.agent_repository import AgentRepository
from tools.registry import default_registry
from requirement_contract import resolve, reviewed, effective_tasks

logger = logging.getLogger("callwise.builder")

SCHEMA_MESSAGES = {
    "extra_forbidden": "Черновик содержит недопустимые параметры. Они не могут быть сохранены.",
    "missing": "В черновике отсутствует обязательное поле.",
    "literal_error": "В черновике выбран вариант, которого нет в разрешённом каталоге.",
    "string_too_short": "Текст в черновике слишком короткий.",
    "string_too_long": "Текст в черновике слишком длинный.",
    "too_long": "В черновике слишком много элементов.",
    "too_short": "В черновике недостаточно элементов.",
}


def token(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class AgentBuilder:
    def __init__(self, provider, repository=None, registry=None):
        self.provider = provider
        self.repository = repository or AgentRepository()
        self.registry = registry if registry is not None else getattr(provider, "registry", None)
        if self.registry is None:
            self.registry = default_registry()
        # Optional catalog binding preserves simple deterministic provider doubles.
        # Providers that use tool schemas must support binding the pipeline registry.
        if callable(getattr(provider, "bind_registry", None)):
            provider.bind_registry(self.registry)

    def generate(self, business, requirement_contract=None):
        contract = reviewed(requirement_contract, business.tasks) if requirement_contract else resolve(business.tasks)
        if not requirement_contract:
            contract = reviewed(contract, business.tasks).model_copy(update={'source':'resolved'})
        effective = business.model_copy(update={'tasks': effective_tasks(contract)})
        cid = str(uuid.uuid4())
        aid = "agent_" + cid.replace("-", "")
        result = {"candidate_id": cid, "business_input": business.model_dump(), "config": None, "draft": None,
                  "preview": None, "validation": {"valid": False, "errors": [], "warnings": []}, "attempts": 0, "review_token": None}
        result['requirement_contract'] = contract.model_dump()
        errors = []
        logger.info("builder_started candidate=%s", cid)
        for attempt in range(2):
            result["attempts"] = attempt + 1
            try:
                raw = self.provider.generate(effective, errors)
            except Exception as exc:
                # Never log API bodies, input, key or provider exception text.
                logger.warning("builder_provider_failed candidate=%s type=%s", cid, type(exc).__name__)
                message = ("Лимит Builder API исчерпан. Подождите восстановления лимита и повторите генерацию. Данные формы сохранены."
                           if getattr(exc, "status_code", None) == 429 else
                           "Builder недоступен. Проверьте GROQ_API_KEY, сеть, модель и лимиты. Данные формы сохранены.")
                result["validation"] = {"valid": False, "errors": [{"path": "provider", "code": "provider_failure", "message": message}], "warnings": []}
                break
            try:
                draft = BuilderDraft.model_validate(raw)
                config, warnings = map_draft(effective, draft, aid, self.registry, contract)
                report = validate_agent(config, self.registry)
                report["warnings"] += [{"path": "builder", "code": "limitation", "message": w} for w in warnings]
                result.update(draft=draft.model_dump(), config=config.model_dump(), validation=report, preview=preview(config))
                errors = report["errors"]
            except (ValidationError, ValueError, KeyError, TypeError) as exc:
                errors = ([{"path": ".".join(map(str, e["loc"])), "code": "draft_schema",
                            "message": SCHEMA_MESSAGES.get(e["type"], "В черновике неверный тип или формат значения.")} for e in exc.errors()]
                          if isinstance(exc, ValidationError) else [{"path": "mapping", "code": "invalid_draft", "message": str(exc)}])
                result.update(config=None, draft=None, preview=None, validation={"valid": False, "errors": errors, "warnings": []})
            logger.info("builder_validation candidate=%s valid=%s attempt=%s", cid, not errors, attempt + 1)
            if not errors:
                result["review_token"] = token({'config': result['config'], 'requirements': result['requirement_contract']})
                break
            if attempt == 0:
                logger.info("builder_repair candidate=%s", cid)
        self.repository.save_candidate(result)
        logger.info("builder_completed candidate=%s valid=%s", cid, result["validation"]["valid"])
        return result

    def validate(self, candidate_id):
        candidate = self.repository.candidate(candidate_id)
        if not candidate:
            raise LookupError("Черновик не найден")
        return validate_agent(candidate["config"], self.registry) if candidate.get("config") else candidate["validation"]

    def save(self, candidate_id, review_token):
        candidate = self.repository.candidate(candidate_id)
        if not candidate:
            raise LookupError("Черновик не найден")
        if not candidate["validation"]["valid"] or not candidate.get("config"):
            raise ValueError("Невалидный черновик нельзя сохранить как агента")
        content = {'config': candidate['config'], 'requirements': {**candidate['requirement_contract'], 'confirmed':False}} if candidate.get('requirement_contract') else candidate['config']
        if not review_token or token(content) != review_token or candidate["review_token"] != review_token:
            raise ValueError("Предпросмотр изменился. Проверьте черновик заново")
        config = require_valid(AgentConfig.model_validate(candidate["config"]), self.registry)
        if candidate.get('requirement_contract'):
            candidate['requirement_contract']['confirmed'] = True
            self.repository.save_candidate(candidate)
        saved = self.repository.save(config, candidate_id=candidate_id)
        logger.info("agent_saved agent=%s", config.id)
        return saved
