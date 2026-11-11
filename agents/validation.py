"""Semantic contracts, independent of the business industry and LLM provider."""
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from agents.models import AgentConfig
from services.business_hours import validate_schedule, parse_schedule
from agents.fields import path_values


def schema_path_exists(schema, path):
    for part in path.split("."):
        schema = schema.get("items", {}) if part == "*" else schema.get("properties", {}).get(part, {})
        if not schema:
            return False
    return True


class InvalidAgentConfig(ValueError):
    def __init__(self, report):
        self.report = report
        super().__init__("; ".join(e["message"] for e in report["errors"]))


def validate_agent(candidate, registry=None):
    if registry is None:
        from tools.registry import default_registry
        registry = default_registry()
    errors, warnings = [], []
    def error(path, code, message):
        errors.append({"path": path, "code": code, "message": message})
    try:
        config = AgentConfig.model_validate(candidate.model_dump() if isinstance(candidate, AgentConfig) else candidate)
    except ValidationError as exc:
        for entry in exc.errors():
            error(".".join(map(str, entry["loc"])), "schema", entry["msg"])
        return {"valid": False, "errors": errors, "warnings": warnings}
    try:
        ZoneInfo(config.business.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        error("business.timezone", "invalid_timezone", "Нужна действующая IANA timezone")
    try:
        unknown_hours = (not config.business.schedule and not config.business.opening_hours
                         and config.business.knowledge.get('hours_status') == 'not_provided'
                         and set(config.business.capabilities) <= {'call_intake', 'human_handoff'}
                         and all(s.id not in {'opening_hours', 'booking'} for s in config.scenarios)
                         and all(t.name not in {'check_slots', 'create_booking'} for t in config.tools))
        if not unknown_hours:
            validate_schedule(config.business.schedule)
        if config.business.opening_hours and parse_schedule(config.business.opening_hours) != config.business.schedule:
            raise ValueError("Display hours and schedule disagree")
    except (ValueError, TypeError, KeyError):
        error("business.schedule", "invalid_hours", "Некорректные рабочие часы: дни 0–6, окна start/end, без пересечений")
    # The current speech/confirmation adapters implement Russian only. Refuse unsupported runnable configs.
    if config.language != "ru":
        error("language", "unsupported_language", "В этой версии адаптеры подтверждения/STT/TTS поддерживают ru")
    if not config.greeting.strip():
        error("greeting", "missing_greeting", "Нужно приветствие")
    available = set(config.business.capabilities)
    field_ids = {f.id for f in config.fields}
    selected = {t.name for t in config.tools}
    if "human_handoff" in available and config.escalation.explicit_human_request != "immediate":
        error("escalation.explicit_human_request", "human_request_invariant", "При human_handoff явный запрос человека нельзя отключить")
    for owner, required in [("role", config.role.required_capabilities),
                            *[(f"scenarios.{s.id}", s.required_capabilities) for s in config.scenarios]]:
        for capability in set(required) - available:
            error(owner, "missing_capability", f"Нет capability: {capability}")
    for scenario in config.scenarios:
        for name in set(scenario.required_tools) - selected:
            error(f"scenarios.{scenario.id}", "missing_tool_reference", f"Сценарию нужен инструмент {name}")
        for name in set(scenario.required_fields) - field_ids:
            error(f"scenarios.{scenario.id}", "missing_field_reference", f"Сценарию нужно поле {name}")
    for field in config.fields:
        if field.data_kind == "user" and set(field.allowed_sources) - {"user"}:
            error(f"fields.{field.id}", "unsafe_user_source", "Пользовательское поле должно иметь user evidence")
        if not field.allowed_sources:
            error(f"fields.{field.id}", "missing_source", "У поля нет допустимого источника")
        if "tool" in field.allowed_sources and not field.tool_paths:
            error(f"fields.{field.id}", "missing_evidence_path", "Для tool source нужны tool_paths")
        if "business_config" in field.allowed_sources and not field.business_paths:
            error(f"fields.{field.id}", "missing_evidence_path", "Для business_config source нужны business_paths")
        for name in set(field.tool_paths) - selected:
            error(f"fields.{field.id}.tool_paths", "unknown_source_tool", f"Источник не разрешён: {name}")
        for name, paths in field.tool_paths.items():
            if name in selected and name in registry.definitions:
                try:
                    schema = registry.get(name).factory(config).result_schema
                    for path in paths:
                        if not schema_path_exists(schema, path):
                            error(f"fields.{field.id}.tool_paths", "unknown_source_path", f"В result schema {name} нет пути {path}")
                except Exception:
                    error(f"fields.{field.id}.tool_paths", "unavailable_source", f"Источник {name} недоступен")
        for path in field.business_paths:
            if not path_values(config.business.knowledge, path):
                error(f"fields.{field.id}.business_paths", "unknown_source_path", f"В knowledge нет пути {path}")
        if field.required and set(field.allowed_sources) <= {"system", "derived"}:
            error(f"fields.{field.id}", "missing_producer", "Для system/derived поля не зарегистрирован доверенный producer")
        for pattern in [*field.evidence_patterns, *([field.value_pattern] if field.value_pattern else [])]:
            try:
                compiled = re.compile(pattern)
                if pattern in field.evidence_patterns and "value" not in compiled.groupindex:
                    error(f"fields.{field.id}", "invalid_evidence", "evidence_patterns требуют именованную группу value")
            except re.error:
                error(f"fields.{field.id}", "invalid_pattern", "Некорректное регулярное выражение")
    for policy in config.tools:
        path = f"tools.{policy.name}"
        try:
            definition = registry.get(policy.name)
        except ValueError as exc:
            error(path, "unknown_tool", str(exc))
            continue
        for capability in set(definition.required_capabilities) - available:
            error(path, "missing_capability", f"Инструменту нужен capability: {capability}")
        try:
            for message in definition.validate_dependencies(config):
                error(path, "dependency", message)
            tool = definition.factory(config)
            if tool.name != policy.name or not callable(tool.execute):
                raise ValueError("Неверная реализация")
            Draft202012Validator.check_schema(tool.parameters)
            if (definition.requires_confirmation or policy.requires_confirmation or
                    (not definition.read_only and definition.kind != "escalation")) and not tool.prepare:
                error(path, "missing_prepare", "Write action требует безопасной подготовки подтверждения")
            properties = tool.parameters.get("properties", {})
            declared = set(properties) | set(properties.get("additional_fields", {}).get("properties", {}))
            for field_id in tool.action_fields:
                if field_id not in field_ids or field_id not in declared:
                    error(path, "action_field_contract", f"Поле действия отсутствует в config/schema: {field_id}")
            by_id = {f.id: f for f in config.fields}
            for field_id, permitted in tool.source_constraints.items():
                if field_id in by_id and set(by_id[field_id].allowed_sources) - set(permitted):
                    error(path, "unsafe_action_source", f"Контракт действия запрещает этот источник поля {field_id}")
        except Exception as exc:
            error(path, "unavailable_tool", f"Инструмент недоступен: {type(exc).__name__}")
    escalation_enabled = (config.escalation.explicit_human_request == "immediate" or
                          "allowed" in config.escalation.agent_initiated.values())
    if escalation_enabled:
        name = config.escalation.tool
        if name not in selected or name not in registry.definitions:
            error("escalation.tool", "unknown_escalation_tool", f"Escalation tool не зарегистрирован/не разрешён: {name}")
        elif registry.get(name).kind != "escalation":
            error("escalation.tool", "invalid_escalation_tool", "Нужен инструмент с kind=escalation")
    for pattern in config.escalation.explicit_request_patterns:
        try:
            re.compile(pattern)
        except re.error:
            error("escalation", "invalid_pattern", "Некорректный шаблон запроса человека")
    warnings.append({"path": "scenarios", "code": "declarative_contracts", "message":
                     "Свободный текст сценариев не доказывает совместимость; зависимости задавайте required_tools/fields/capabilities."})
    return {"valid": not errors, "errors": errors, "warnings": warnings}


def require_valid(config, registry=None):
    report = validate_agent(config, registry)
    if not report["valid"]:
        raise InvalidAgentConfig(report)
    return config
