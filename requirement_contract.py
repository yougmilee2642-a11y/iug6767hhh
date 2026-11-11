"""Closed, reviewed requirements. Resolution runs at intake, never per evaluation."""
import re
from typing import Literal
from pydantic import Field
from agents.models import StrictModel

RequirementId = Literal['booking', 'pricing', 'faq', 'opening_hours', 'human_handoff', 'unsupported']
Polarity = Literal['required', 'forbidden', 'not_requested', 'unknown']
CATALOG = {
    'booking': 'Запись клиентов', 'pricing': 'Ответы по ценам', 'faq': 'Ответы об услугах',
    'opening_hours': 'Рабочие часы', 'human_handoff': 'Передача человеку',
    'unsupported': 'Пользовательская / неподдержанная задача',
}
PATTERNS = {
    'booking': r'запис|бронир|booking|reserv|appointment',
    'human_handoff': r'человек|оператор|переда|перевод|handoff|human',
    'pricing': r'цен|стоим|price|pricing', 'opening_hours': r'час|расписан|график|opening|hours',
    'faq': r'ответ|услуг|информац|вопрос|faq|question',
    'unsupported': r'возврат|refund|деньг|оплат|плат[её]ж|payment|crm|google|гугл|sip|мтс',
}

class RequirementDecision(StrictModel):
    task_index: int = Field(ge=0, le=19)
    source_text: str = Field(min_length=1, max_length=500)
    requirement_id: RequirementId
    polarity: Polarity

class RequirementContract(StrictModel):
    version: str = 'requirements-1'
    raw_tasks: list[str] = Field(min_length=1, max_length=20)
    entries: list[RequirementDecision] = Field(min_length=1, max_length=120)
    source: Literal['resolved', 'user_reviewed', 'legacy_inferred'] = 'resolved'
    confirmed: bool = False

def resolve(tasks, source='resolved'):
    entries = []
    for index, task in enumerate(tasks):
        clauses = re.split(r'[,;.!]|\b(?:только|но|а также)\b', task, flags=re.I)
        found = False
        for clause in clauses:
            categories = [key for key, pattern in PATTERNS.items() if re.search(pattern, clause, re.I)]
            if 'pricing' in categories and 'faq' in categories: categories.remove('faq')
            if 'human_handoff' in categories and 'faq' in categories: categories.remove('faq')
            negated = bool(re.search(r'\bне\b|\bбез\b|\bnot\b|\bno\b', clause, re.I))
            for category in categories:
                found = True
                polarity = ('not_requested' if category == 'unsupported' else 'forbidden') if negated else 'required'
                decision = RequirementDecision(task_index=index, source_text=task, requirement_id=category, polarity=polarity)
                if decision not in entries: entries.append(decision)
        if not found:
            entries.append(RequirementDecision(task_index=index, source_text=task, requirement_id='unsupported', polarity='unknown'))
    return RequirementContract(raw_tasks=tasks, entries=entries, source=source)

def reviewed(value, tasks):
    contract = RequirementContract.model_validate(value)
    if contract.version != 'requirements-1' or contract.raw_tasks != tasks:
        raise ValueError('Договор требований не соответствует текущим задачам')
    for entry in contract.entries:
        if entry.task_index >= len(tasks) or entry.source_text != tasks[entry.task_index]:
            raise ValueError('Исходный текст требования изменён')
    if {e.task_index for e in contract.entries} != set(range(len(tasks))):
        raise ValueError('Каждая исходная задача должна быть рассмотрена')
    for key in CATALOG:
        polarities = {e.polarity for e in contract.entries if e.requirement_id == key}
        if 'required' in polarities and 'forbidden' in polarities:
            raise ValueError('Противоречивые требования: ' + key)
    return contract.model_copy(update={'source': 'user_reviewed', 'confirmed': False})

def effective_tasks(contract):
    return [CATALOG[e.requirement_id] if e.requirement_id != 'unsupported' else e.source_text
            for e in contract.entries if e.polarity == 'required'] or ['Только отвечать по доступной информации; действия не подключать']
