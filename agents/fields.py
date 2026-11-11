"""Conservative, schema-driven evidence. Model arguments never create user evidence."""
import re
from agents.models import FieldValue
from tools.base import FieldEvidenceRequired, ToolInputError


def normalize(field, value):
    value = str(value).strip()
    if field.id == 'customer_name':
        value = value.rstrip('.!').strip()
        # Speech noise and answers to another question must not become a name.
        words = value.split()
        if (len(words) > 3 or len({w.casefold() for w in words}) != len(words)
                or re.search(r'\b(?:братка|телефон|номер|сколько|стоит|записывай|пофиг|вчера|сегодня|завтра|скидка|забыл|забыла|не помню|не знаю)\b', value, re.I)
                or value.casefold() in {'да', 'нет', 'не скажу', 'не хочу'}):
            raise ToolInputError('Не удалось разобрать имя', field.question)
    if field.normalization == "digits":
        value = re.sub(r'^плюс\s+', '+', value, flags=re.I)
        value = ("+" if value.startswith("+") else "") + re.sub(r"\D", "", value)
    elif field.normalization == "email":
        value = value.casefold()
    if not value or (field.value_pattern and not re.fullmatch(field.value_pattern, value)):
        raise ToolInputError(f"Некорректное значение: {field.label}", field.question)
    return value


def record(state, field, value, source, evidence):
    if source not in field.allowed_sources:
        raise FieldEvidenceRequired(field)
    value = normalize(field, value)
    state.setdefault("collected_fields", {})[field.id] = FieldValue(
        field_id=field.id, value=value, source=source, evidence=evidence).model_dump()
    state["structured_data"][field.id] = value


def collect_user(state, config, text, turn_index, bind=True):
    binding = state.pop("pending_collection", None) if bind else None
    fields = {f.id: f for f in config.fields}
    for field in config.fields:
        if "user" not in field.allowed_sources:
            continue
        # Explicit declarations are configured semantics, not substring membership.
        patterns = declaration_patterns(field)
        for pattern in patterns:
            matches = list(re.finditer(pattern, text, re.I))
            if matches:
                value = matches[-1].group("value").strip()
                try:
                    record(state, field, value, "user", {"kind": "declaration", "turn": turn_index,
                           "text": text, "pattern": pattern})
                except ToolInputError:
                    continue
                break
    if binding and binding["field_id"] in fields:
        field = fields[binding["field_id"]]
        item = state.get("collected_fields", {}).get(field.id, {})
        if item.get("evidence", {}).get("turn") == turn_index:
            return  # A declaration such as 'Меня зовут Алексей' already mapped this answer.
        # An answer is evidence only for the exact server-issued collection question.
        if (binding["question_index"] == turn_index - 1 and
                collection_question_matches(field, state, turn_index - 1)):
            record(state, field, text, "user", {"kind": "collection_answer", "turn": turn_index,
                   "question_turn": turn_index - 1, "text": text})


def path_values(data, path):
    nodes = [data]
    for part in path.split("."):
        nodes = [value for node in nodes for value in
                 (list(node) if part == "*" and isinstance(node, list) else
                  [node[part]] if isinstance(node, dict) and part in node else [])]
    return nodes


def declaration_patterns(field):
    patterns = [*field.evidence_patterns,
                rf"(?:^|[;\n])\s*{re.escape(field.label)}\s*:\s*(?P<value>[^;\n]+)"]
    if field.id == 'phone' and field.normalization == 'digits':
        patterns.append(r'(?:телефон|номер(?:\s+телефона)?)(?:\s+(?:мой|для связи|это))*\s*[:—-]?\s*(?P<value>(?:плюс\s+|\+)?[0-9][0-9 ()-]{6,24})')
    return patterns


def user_record_valid(field, item, state):
    evidence = item.get("evidence", {})
    turn = evidence.get("turn", -1)
    if not isinstance(turn, int) or not 0 <= turn < len(state["transcript"]):
        return False
    message = state["transcript"][turn]
    if message["role"] != "user" or message["content"] != evidence.get("text"):
        return False
    if evidence.get("kind") == "collection_answer":
        question = evidence.get("question_turn", -1)
        return (question == turn - 1 and question >= 0 and
                collection_question_matches(field, state, question)
                and normalize(field, message["content"]) == item["value"])
    if evidence.get("kind") == "declaration":
        patterns = declaration_patterns(field)
        if evidence.get("pattern") not in patterns:
            return False
        return any(normalize(field, match.group("value")) == item["value"]
                   for match in re.finditer(evidence["pattern"], message["content"], re.I))
    return False


def collection_question_matches(field, state, index):
    message = state['transcript'][index]
    if message['role'] != 'assistant':
        return False
    if index == 0:
        return (message['content'] == state.get('agent_config', {}).get('greeting')
                and message['content'].endswith(field.question))
    if message['content'].strip().endswith(field.question.strip()):
        return True
    return False


def verify_action(state, config, values):
    """Return canonical values with provenance; refuse every unsupported configured field."""
    records = state.setdefault("collected_fields", {})
    for field in config.fields:
        candidate = values.get(field.id)
        existing = records.get(field.id)
        if candidate is None and existing:
            candidate = existing["value"]
        if candidate is None:
            if field.required:
                raise FieldEvidenceRequired(field)
            continue
        candidate = normalize(field, candidate)
        if existing and existing["source"] == "user" and "user" in field.allowed_sources:
            if user_record_valid(field, existing, state) and normalize(field, existing["value"]) == candidate:
                values[field.id] = existing["value"]
                continue
        found = False
        if "tool" in field.allowed_sources:
            for index, event in enumerate(state["tool_events"]):
                for path in field.tool_paths.get(event["name"], []):
                    if candidate in [normalize(field, v) for v in path_values(event["result"], path)]:
                        record(state, field, candidate, "tool", {"event": index, "path": path})
                        found = True
                        break
                if found:
                    break
        if not found and "business_config" in field.allowed_sources:
            for path in field.business_paths:
                if candidate in [normalize(field, v) for v in path_values(config.business.knowledge, path)]:
                    record(state, field, candidate, "business_config", {"path": path})
                    found = True
                    break
        # system/derived require a trusted producer; simply labelling an LLM argument is insufficient.
        if not found:
            raise FieldEvidenceRequired(field)
        values[field.id] = candidate
    return values


def confirmation(config, tool, values):
    labels = {f.id: f.label for f in config.fields}
    displays = {f.id: f.display_values for f in config.fields}
    properties = tool.parameters.get("properties", {})
    lines = [f"{labels.get(key, properties.get(key, {}).get('title', key))}: {displays.get(key, {}).get(str(value), value)}"
             for key, value in values.items()]
    return f"Подтвердите действие «{tool.action_label or tool.name}»:\n" + "\n".join(lines) + "\nВсё верно?"
