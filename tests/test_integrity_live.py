"""Opt-in bounded live observation, explicitly not a PASS certificate for Groq."""
import os
import json
import pytest
import storage
import app  # Loads the existing local .env; never print credentials.
from tests.test_builder import nova, MockBuilder
from builder.models import BusinessInput
from builder.service import AgentBuilder
from agents.models import AgentConfig
from evaluation.requirements import RequirementAnalyzer
from evaluation.scenarios import trusted_scenarios
from evaluation.providers import Budget, live_agent_provider, GroqJudge, ScriptedUserSimulator
from evaluation.simulation import SimulationEngine
from evaluation.evaluator import EvaluationEngine
from evaluation.readiness import readiness
from tools.registry import default_registry

@pytest.mark.skipif(os.getenv('CALLWISE_INTEGRITY_LIVE')!='1',reason='Opt-in bounded live: CALLWISE_INTEGRITY_LIVE=1')
def test_three_bounded_live_observations(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'DB_PATH',tmp_path/'live.sqlite');monkeypatch.setattr(storage,'DATA_DIR',tmp_path)
    storage.initialize_db()
    data=BusinessInput.model_validate(nova());candidate=AgentBuilder(MockBuilder()).generate(data)
    config=AgentConfig.model_validate(candidate['config']);registry=default_registry()
    requirements=RequirementAnalyzer(registry).analyze(data,config)
    cases={s.id:s for s in trusted_scenarios(data,config,requirements)}
    budget=Budget(12);engine=SimulationEngine(lambda:live_agent_provider(budget),ScriptedUserSimulator(),registry,max_turns=3)
    evaluator=EvaluationEngine(registry,GroqJudge(budget));results=[]
    # Handoff is a real Runtime/server action, not a claim about live model intelligence.
    for sid in ('explicit_handoff','pricing','unsupported_tool'):
        result=evaluator.evaluate(config,cases[sid],engine.run(config,cases[sid]));results.append(result)
        print('LIVE 3.1',sid,result['status'],'error=',result.get('error'))
        if result.get('error',{} ) and result['error'].get('status_code')==429: break
    report=readiness(requirements,results)
    print('LIVE 3.1 summary',json.dumps({'requests':budget.requests,'observed':len(results),'readiness':report['status']},ensure_ascii=False))
    assert budget.requests<=12 and report['status']!='READY'
    with storage.connect() as db:assert db.execute('SELECT count(*) FROM bookings').fetchone()[0]==0
