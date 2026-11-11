"""All evidence and validation expressions are trusted server constants."""
import re
from agents.models import AgentField

PRESETS = {
    "person_name": {"value_pattern": r"[А-Яа-яЁёA-Za-z][А-Яа-яЁёA-Za-z '\-]{0,99}"},
    "phone": {"normalization": "digits", "value_pattern": r"\+?\d{7,15}"},
    "email": {"normalization": "email", "value_pattern": r"[^\s@]+@[^\s@]+\.[^\s@]+"},
    "free_text": {"value_pattern": r"[\s\S]{1,1000}"},
    "number": {"value_pattern": r"-?\d+(?:[.,]\d+)?"},
    "address": {"value_pattern": r"[\s\S]{3,300}"},
    "choice": {},
}


def user_field(field_id, label, question, kind, required=True, choices=()):
    values = dict(PRESETS[kind])
    if kind == "choice":
        if not choices or len(set(choices)) != len(choices) or any(not c.strip() or len(c) > 80 for c in choices):
            raise ValueError("Поле выбора требует непустые уникальные варианты (до 80 символов)")
        values["value_pattern"] = "(?:" + "|".join(re.escape(c) for c in choices) + ")"
    elif choices:
        raise ValueError("Варианты разрешены только для поля choice")
    evidence = []
    if field_id == "customer_name":
        evidence = [r"(?:меня зовут|моё имя|мое имя)\s+(?P<value>[А-Яа-яЁёA-Za-z][А-Яа-яЁёA-Za-z '\-]{0,99})"]
    elif field_id == "phone":
        evidence = [r"(?:телефон|номер)\s*[:\-]?\s*(?P<value>\+?[\d ()\-]{7,25})"]
    return AgentField(id=field_id, label=label, question=question, required=required,
                      evidence_patterns=evidence, **values)
