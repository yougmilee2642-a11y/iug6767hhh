import re
from builder.mapping import stable_id, normalized
from builder.catalog import SCENARIOS
from evaluation.models import Requirement
from requirement_contract import resolve
from evaluation.knowledge import knowledge_dependencies

class RequirementAnalyzer:
    def __init__(self, registry): self.registry = registry

    def analyze(self, business, config, contract=None):
        contract = contract or resolve(business.tasks, 'legacy_inferred')
        result = []
        scenarios = {s.id for s in config.scenarios}
        tools = {t.name for t in config.tools}
        fields = {f.id for f in config.fields}
        capabilities = set(config.business.capabilities)
        for entry in contract.entries:
            index, text = entry.task_index, entry.source_text
            for category in [entry.requirement_id]:
                template = SCENARIOS.get(category)
                required_tools = template.required_tools if template else []
                required_caps = template.required_capabilities if template else []
                required_fields = template.required_fields if template else []
                supported = template is not None and set(required_tools) <= self.registry.definitions.keys()
                alternatives = ['pricing','faq'] if category == 'pricing' else [category]
                missing = []
                if not set(alternatives) & scenarios: missing.append('scenario:' + category)
                missing += ['tool:' + t for t in required_tools if t not in tools]
                missing += ['capability:' + c for c in required_caps if c not in capabilities]
                missing += ['field:' + f for f in required_fields if f not in fields]
                if category=='human_handoff' and config.escalation.explicit_human_request!='immediate':
                    missing.append('policy:immediate_handoff')
                knowledge_missing = knowledge_dependencies(config, category)
                missing += knowledge_missing
                if category in {'pricing','booking'}:
                    for expected in business.services:
                        saved=next((s for s in config.business.knowledge.get('services',[]) if normalized(s.get('name',''))==normalized(expected.name)),None)
                        keys = ('price','currency') if category=='pricing' else ('price','currency','duration_minutes')
                        if not saved or any(saved.get(key)!=getattr(expected,key) for key in keys):
                            missing.append('catalog:'+expected.name)
                count = len(required_tools) + len(required_caps) + len(required_fields) + 1
                if entry.polarity in {'forbidden','not_requested'}:
                    missing = (['forbidden:scenario:'+category] if category in scenarios else []) + ['forbidden:tool:'+t for t in required_tools if t in tools]
                    if entry.polarity == 'not_requested': missing = []
                    supported = True
                elif entry.polarity == 'unknown':
                    supported = False
                status = 'UNSUPPORTED' if not supported else 'COVERED' if not missing else 'MISSING' if len(missing)>=count else 'PARTIALLY_COVERED'
                if supported and entry.polarity=='required' and knowledge_missing: status='MISSING'
                result.append(Requirement(id=stable_id(f'{index}|{text}|{category}','requirement'), source_text=text,
                    category=category, required_scenarios=alternatives, required_tools=required_tools,
                    required_capabilities=required_caps, supported=supported, coverage_status=status,
                    missing=missing if supported else ['Нет поддержанного контракта для этого требования'],
                    critical=category in {'booking','human_handoff'} and entry.polarity in {'required','forbidden'}, polarity=entry.polarity))
        canonical_role = normalized(business.desired_role)
        role_ok = (normalized(config.role.name)==canonical_role and config.role.id==stable_id(business.desired_role,'role')
                   and business.desired_role in config.greeting)
        result.append(Requirement(id='requirement_role',source_text=business.desired_role,category='role',
            required_scenarios=[], required_tools=[],required_capabilities=[],supported=True,
            coverage_status='COVERED' if role_ok else 'MISSING',missing=[] if role_ok else ['Identity не соответствует desired_role'],critical=True))
        return result
