from typing import Literal
from pydantic import Field, ConfigDict
from agents.models import StrictModel


class EvalModel(StrictModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


Category = Literal['booking','human_handoff','pricing','opening_hours','faq','role','unsupported']
ScenarioType = Literal['HAPPY_PATH','EDGE_CASE','HANDOFF','SAFETY','TOOL_FAILURE','UNSUPPORTED_REQUEST']
AssertionName = Literal['no_unconfirmed_write','user_provenance','allowed_tools','immediate_handoff',
    'booking_completed','no_booking','rejected_probe','slots_grounded','failure_handled','role_identity',
    'price_grounded','unknown_grounded','proposal_changed','knowledge_grounded','callback_saved','callback_not_saved','no_contact_collection']


class Requirement(EvalModel):
    id: str
    source_text: str
    category: Category
    required_scenarios: list[str]
    required_capabilities: list[str]
    required_tools: list[str]
    supported: bool
    coverage_status: Literal['COVERED','PARTIALLY_COVERED','UNSUPPORTED','MISSING']
    missing: list[str]
    critical: bool
    polarity: Literal['required','forbidden','not_requested','unknown'] = 'required'


class ClientPersona(EvalModel):
    opening: str = Field(min_length=1, max_length=1000)
    goal: str = Field(max_length=1000)
    known_data: dict[str,str] = Field(default_factory=dict)
    behavior: Literal['normal','withhold_phone','withhold_extra','ambiguous','change_time','refuse','one_turn'] = 'normal'


class EvaluationScenario(EvalModel):
    id: str
    requirement_id: str | None = None
    scenario_type: ScenarioType
    category: Category
    title: str
    expected_behavior: str
    client: ClientPersona
    initial_context: dict = Field(default_factory=dict)
    expected_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    expected_state: str | None = None
    assertions: list[AssertionName]
    severity: Literal['INFO','MINOR','MAJOR','CRITICAL'] = 'MAJOR'
    source: Literal['trusted_template','generated_variant'] = 'trusted_template'
    template_id: str = ''
    coverage_axes: dict[str,str] = Field(default_factory=dict)


class LanguageVariant(EvalModel):
    template_id: str = Field(min_length=1, max_length=100)
    paraphrase_template: str = Field(min_length=3, max_length=600)


class VariantBatch(EvalModel):
    variants: list[LanguageVariant] = Field(max_length=30)


class SimulatorReply(EvalModel):
    text: str = Field(max_length=1000)
    done: bool


class JudgeResult(EvalModel):
    passed: bool
    score: float = Field(ge=0, le=1, allow_inf_nan=False)
    reasons: list[str] = Field(max_length=8)
    flags: list[Literal['ungrounded_answer','unclear_refusal','off_goal','role_mismatch']] = Field(max_length=4)
