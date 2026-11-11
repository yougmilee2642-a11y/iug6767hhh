"""Small opt-in intelligence run: no full 20-scenario cloud burn, no voice layer."""
import os
import pytest
import storage
import app
from tests.test_builder import nova,MockBuilder
from builder.models import BusinessInput
from builder.service import AgentBuilder
from agents.models import AgentConfig
from evaluation.service import default_components
from evaluation.requirements import RequirementAnalyzer
from evaluation.scenarios import ScenarioGenerator
from evaluation.simulation import SimulationEngine
from evaluation.evaluator import EvaluationEngine
from tools.registry import default_registry

pytestmark=pytest.mark.skipif(os.getenv('CALLWISE_EVAL_LIVE_TESTS')!='1',reason='Opt-in Groq evaluation: CALLWISE_EVAL_LIVE_TESTS=1')


@pytest.fixture
def environment(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'DB_PATH',tmp_path/'live_eval.sqlite');monkeypatch.setattr(storage,'DATA_DIR',tmp_path)
    storage.initialize_db()


@pytest.mark.parametrize('sid',['booking_happy','explicit_handoff','ambiguous_confirmation','unsupported_tool','pricing'])
def test_real_groq_small_evaluation(environment,sid):
    data=BusinessInput.model_validate(nova());candidate=AgentBuilder(MockBuilder()).generate(data)
    config=AgentConfig.model_validate(candidate['config']);registry=default_registry()
    requirements=RequirementAnalyzer(registry).analyze(data,config)
    case=next(s for s in ScenarioGenerator().generate(data,config,requirements,12) if s.id==sid)
    components=default_components()
    trace=SimulationEngine(components['agent_factory'],components['simulator'],registry).run(config,case)
    result=EvaluationEngine(registry,components['judge']).evaluate(config,case,trace)
    print('LIVE EVALUATION',sid,result['status'],result['failure_reasons'])
    assert result['status']=='PASS',{'scenario':sid,'status':result['status'],'error':result['error'],'reasons':result['failure_reasons']}
    with storage.connect() as db:
        assert db.execute('SELECT count(*) FROM bookings').fetchone()[0]==0


def test_real_structured_generator_and_user_simulator(environment):
    from evaluation.models import SimulatorReply
    from evaluation.providers import GroqUserSimulator
    data=BusinessInput.model_validate(nova());candidate=AgentBuilder(MockBuilder()).generate(data)
    config=AgentConfig.model_validate(candidate['config']);registry=default_registry();components=default_components()
    requirements=RequirementAnalyzer(registry).analyze(data,config)
    cases=ScenarioGenerator(components['generator']).generate(data,config,requirements,14)
    assert len(cases)==14 and any(s.source=='generated_variant' for s in cases)
    public={'transcript':[{'role':'assistant','content':'Как вас зовут?'}],'status':'active'}
    reply=SimulatorReply.model_validate(GroqUserSimulator(components['budget']).reply(cases[2].client.model_dump(),public))
    assert reply.text and 'Тест' in reply.text
