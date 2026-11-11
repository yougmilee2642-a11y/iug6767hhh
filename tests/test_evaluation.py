import copy
import json
import sqlite3
import threading
import pytest
import storage
import app
from builder.models import BusinessInput
from builder.mapping import stable_id
from builder.service import AgentBuilder
from agents.models import AgentConfig
from agents.runtime import AgentRuntime
from tools.registry import default_registry,ToolRegistry
from tests.test_builder import isolated,nova,draft,MockBuilder
from tests.evaluation_doubles import components,DeterministicAgent,DeterministicJudge
from evaluation.requirements import RequirementAnalyzer
from evaluation.scenarios import ScenarioGenerator,CORE_IDS,trusted_scenarios
from evaluation.simulation import SimulationEngine,public_state
from evaluation.evaluator import EvaluationEngine
from evaluation.providers import ScriptedUserSimulator,Budget,schema_for
from evaluation.models import VariantBatch,SimulatorReply,JudgeResult
from evaluation.readiness import readiness
from evaluation.service import EvaluationService
from evaluation.repository import EvaluationRepository,digest


def data_config():
    data=BusinessInput.model_validate(nova())
    result=AgentBuilder(MockBuilder()).generate(data)
    return data,AgentConfig.model_validate(result['config'])


def saved():
    builder=AgentBuilder(MockBuilder());result=builder.generate(BusinessInput.model_validate(nova()))
    return builder.save(result['candidate_id'],result['review_token'])


def generated_cases(data,c,count=12):
    requirements=RequirementAnalyzer(default_registry()).analyze(data,c)
    return requirements,ScenarioGenerator().generate(data,c,requirements,count)


def run_case(c,s,agent_factory=DeterministicAgent,simulator=None):
    registry=default_registry()
    trace=SimulationEngine(agent_factory,simulator or ScriptedUserSimulator(),registry).run(c,s)
    return EvaluationEngine(registry,DeterministicJudge()).evaluate(c,s,trace)


def test_role_canonical_desired_input_not_model(isolated):
    data=nova();data['desired_role']='Менеджер по продажам'
    result=AgentBuilder(MockBuilder(draft())).generate(BusinessInput.model_validate(data))
    assert result['validation']['valid'] and result['config']['role']['name']=='Менеджер по продажам'
    assert result['config']['role']['id']==stable_id('Менеджер по продажам','role')
    assert 'Менеджер по продажам' in result['config']['greeting']
    assert any('не совпала' in w['message'] for w in result['validation']['warnings'])


@pytest.mark.parametrize('task,category,tools',[('Записывать клиентов','booking',{'check_slots','create_booking'}),('Передавать человеку','human_handoff',{'transfer_to_human'}),('Отвечать по ценам','pricing',set())])
def test_requirement_mapping_trusted_catalog(isolated,task,category,tools):
    data,c=data_config();data.tasks=[task]
    r=next(r for r in RequirementAnalyzer(default_registry()).analyze(data,c) if r.category==category)
    assert set(r.required_tools)==tools and r.supported and r.coverage_status=='COVERED'


def test_refund_and_unknown_not_silently_covered(isolated):
    data,c=data_config();data.tasks=['Автоматически возвращать деньги','Проводить неизвестный ритуал']
    r=RequirementAnalyzer(default_registry()).analyze(data,c)
    assert sum(v.coverage_status=='UNSUPPORTED' for v in r)==2
    assert not all(v.coverage_status=='COVERED' for v in r)


def test_missing_booking_even_perfect_faq_never_ready(isolated):
    data,c=data_config()
    _,cases=generated_cases(data,c)
    perfect_results=[run_case(c,s) for s in cases]
    assert all(r['status']=='PASS' for r in perfect_results)
    c.scenarios=[s for s in c.scenarios if s.id in {'faq','pricing'}];c.tools=[];c.fields=[];c.business.capabilities=[]
    c.role.required_capabilities=[];c.escalation.explicit_human_request='disabled';c.escalation.agent_initiated={}
    requirements=RequirementAnalyzer(default_registry()).analyze(data,c)
    assert next(r for r in requirements if r.category=='booking').coverage_status=='MISSING'
    result={'scenario_id':'faq','status':'PASS','assertions':[],'critical_failures':[]}
    assert readiness(requirements,[result])['status']=='NOT_READY'
    assert readiness(requirements,perfect_results)['status']=='NOT_READY'


def test_launch_is_async_and_duplicate_does_not_start_second_worker(isolated,monkeypatch):
    entered=threading.Event();release=threading.Event();finished=threading.Event()
    calls=[];agent=saved();service=EvaluationService(components_factory=components)
    def held(run):
        calls.append(run['id']);entered.set()
        try:release.wait(5)
        finally:finished.set()
    monkeypatch.setattr(service,'execute',held)
    run=service.launch(agent['id'],12)
    assert entered.wait(2)
    try:
        duplicate=service.launch(agent['id'],20)
        assert duplicate['id']==run['id'] and calls==[run['id']]
        with pytest.raises(ValueError):service.launch('other-agent',12)
    finally:release.set();assert finished.wait(2)


def test_partial_and_missing_custom_registry(isolated):
    data,c=data_config();c.tools=[t for t in c.tools if t.name!='create_booking']
    r=RequirementAnalyzer(default_registry()).analyze(data,c)
    assert next(r for r in r if r.category=='booking').coverage_status=='PARTIALLY_COVERED'
    assert next(r for r in RequirementAnalyzer(ToolRegistry()).analyze(data,c) if r.category=='booking').coverage_status=='UNSUPPORTED'


def test_business_catalog_mismatch_is_visible(isolated):
    data,c=data_config();c.business.knowledge['services'][0]['price']=60
    requirements,scenarios=generated_cases(data,c)
    assert next(r for r in requirements if r.category=='pricing').coverage_status!='COVERED'
    assert next(s for s in scenarios if s.id=='pricing').initial_context['price']==50


def test_core_set_limit_and_seed(isolated):
    data,c=data_config();r,cases=generated_cases(data,c,20)
    assert len(cases)==20 and set(CORE_IDS)<=set(s.id for s in cases)
    assert all(s.requirement_id or s.category=='unsupported' for s in cases)
    assert [s.model_dump() for s in cases]==[s.model_dump() for s in ScenarioGenerator().generate(data,c,r,20,0)]
    with pytest.raises(ValueError):ScenarioGenerator().generate(data,c,r,41)


@pytest.mark.parametrize('bad',[{'variants':[{'template_id':'pricing','opening':'Сколько стоит?','tools':['refund']}]},
    {'variants':[{'template_id':'run_python','opening':'Привет'}]}, {'python':'print(1)'}])
def test_generated_schema_rejects_arbitrary_tools_code(isolated,bad):
    class Bad:
        calls=0
        def generate(self,*args):self.calls+=1;return bad
    data,c=data_config();r,_=generated_cases(data,c)
    provider=Bad()
    with pytest.raises(ValueError):ScenarioGenerator(provider).generate(data,c,r,20)
    assert provider.calls==2


def test_generated_variants_only_copy_trusted_expectations(isolated):
    class Provider:
        def generate(self,*args):return {'variants':[{'template_id':'pricing','paraphrase_template':'Какая цена на {service}?'}]}
    data,c=data_config();r,_=generated_cases(data,c)
    cases=ScenarioGenerator(Provider()).generate(data,c,r,13)
    assert cases[-1].source=='generated_variant' and cases[-1].assertions==next(s for s in cases if s.id=='pricing').assertions
    assert schema_for(VariantBatch)['additionalProperties'] is False


@pytest.mark.parametrize('sid',CORE_IDS)
def test_real_runtime_core_traces(isolated,sid):
    data,c=data_config();_,cases=generated_cases(data,c)
    result=run_case(c,next(s for s in cases if s.id==sid))
    assert result['status']=='PASS',result
    assert result['trace']['transcript'] and result['trace']['duration_seconds']>=0
    if sid=='booking_happy':assert result['trace']['bookings'] and any(e['confirmed'] for e in result['trace']['tool_events'])
    if sid=='explicit_handoff':assert result['trace']['escalations']


def test_simulator_only_public_view(isolated):
    seen=[]
    class Capture(ScriptedUserSimulator):
        def reply(self,client,visible):seen.append((client,visible));return super().reply(client,visible)
    data,c=data_config();_,cases=generated_cases(data,c);run_case(c,next(s for s in cases if s.id=='booking_happy'),simulator=Capture())
    assert seen
    for client,visible in seen:
        assert set(client)=={'opening','goal','known_data','behavior'} and set(visible)=={'transcript','status'}
        assert 'assertions' not in json.dumps(visible) and 'system' not in {m['role'] for m in visible['transcript']}


def test_thread_local_isolation_no_business_rows(isolated,tmp_path):
    original=storage.database_path();seen=[]
    def worker():
        with storage.isolated_database(tmp_path/'isolated.sqlite'):
            storage.initialize_db();seen.append(storage.database_path())
            with storage.connect() as db:db.execute("INSERT INTO escalations VALUES ('eval','x','x','{}','now','test','test')")
    t=threading.Thread(target=worker);t.start();t.join()
    assert storage.database_path()==original and seen==[tmp_path/'isolated.sqlite']
    with storage.connect() as db:assert db.execute('SELECT count(*) FROM escalations').fetchone()[0]==0
    data,c=data_config();_,cases=generated_cases(data,c);run_case(c,cases[2])
    with storage.connect() as db:
        assert db.execute('SELECT count(*) FROM bookings').fetchone()[0]==0 and db.execute('SELECT count(*) FROM interactions').fetchone()[0]==0


def test_max_turns_and_provider_error(isolated):
    from providers.base import ModelReply
    class Loop:
        def complete(self,*_):return ModelReply('Повторите запрос.')
    class Broken:
        def complete(self,*_):raise RuntimeError('SECRET_KEY_PROVIDER_BODY')
    data,c=data_config();_,cases=generated_cases(data,c)
    engine=SimulationEngine(Loop,ScriptedUserSimulator(),default_registry(),max_turns=2)
    trace=engine.run(c,cases[2]);assert trace['stop_reason']=='turn_limit_exceeded'
    # Booking can now succeed without contacting a provider. Exercise a real
    # model-dependent role question rather than demanding a fictional provider error.
    trace=SimulationEngine(Broken,ScriptedUserSimulator(),default_registry()).run(c,cases[0])
    result=EvaluationEngine(default_registry(),DeterministicJudge()).evaluate(c,cases[0],trace)
    assert result['status']=='ERROR' and 'SECRET_KEY' not in json.dumps(trace)


def test_confirmation_and_invented_field_violations_detected(isolated):
    data,c=data_config();_,cases=generated_cases(data,c);s=cases[2];result=run_case(c,s)
    trace=result['trace'];trace['steps'][-1]['user']='Ну наверное.'
    result=EvaluationEngine(default_registry(),DeterministicJudge()).evaluate(c,s,trace)
    assert result['status']=='FAIL' and 'no_unconfirmed_write' in result['critical_failures']
    trace['collected_fields']['phone']['evidence']['text']='Поддельный источник'
    result=EvaluationEngine(default_registry(),DeterministicJudge()).evaluate(c,s,trace)
    assert 'user_provenance' in result['critical_failures']


def test_missing_handoff_and_fake_tool_execution(isolated):
    data,c=data_config();_,cases=generated_cases(data,c);s=cases[1];trace=run_case(c,s)['trace'];trace['escalations']=[]
    result=EvaluationEngine(default_registry(),DeterministicJudge()).evaluate(c,s,trace)
    assert 'immediate_handoff' in result['critical_failures']
    trace['tool_events'].append({'name':'refund','result':{'executed':True},'confirmed':False})
    result=EvaluationEngine(default_registry(),DeterministicJudge()).evaluate(c,s,trace)
    assert 'allowed_tools' in result['critical_failures']


@pytest.mark.parametrize('reply',[{'passed':True,'score':2,'reasons':[],'flags':[]},{'passed':True,'score':1,'reasons':[],'flags':[],'code':'pass'}, RuntimeError('private')])
def test_judge_bad_output_or_failure_is_error(isolated,reply):
    class Judge:
        def judge(self,*_):
            if isinstance(reply,Exception):raise reply
            return reply
    data,c=data_config();_,cases=generated_cases(data,c);s=cases[-1];trace=run_case(c,s)['trace']
    assert EvaluationEngine(default_registry(),Judge()).evaluate(c,s,trace)['status']=='ERROR'


def test_readiness_ready_limited_critical_gates(isolated):
    data,c=data_config();requirements,cases=generated_cases(data,c,20);results=[run_case(c,s) for s in cases]
    assert readiness(requirements,results)['status']=='READY'
    results[-1]['status']='FAIL'
    assert readiness(requirements,results)['status']=='LIMITED'  # Even 95% is not a clean suite.
    results[-2]['status']='FAIL'
    assert readiness(requirements,results)['status']=='LIMITED'
    results[-1]['critical_failures']=['no_unconfirmed_write']
    assert readiness(requirements,results)['status']=='NOT_READY'


def test_persistence_outdated_and_no_automatic_deactivation(isolated):
    agent=saved();service=EvaluationService(components_factory=components)
    run=service.prepare(agent['id'],12);result=service.execute(run)
    assert result['status']=='completed' and result['current'] and result['readiness']['status']=='LIMITED'
    assert service.repository.result(run['id'],next(s['id'] for s in result['scenarios'] if s['template_id']=='booking_happy'))['trace']['tool_events']
    with storage.connect() as db:
        original=json.loads(db.execute('SELECT config_json FROM agents WHERE id=?',(agent['id'],)).fetchone()[0])
        original['greeting']+=' Изменено.'
        db.execute('UPDATE agents SET config_json=? WHERE id=?',(json.dumps(original),agent['id']))
    assert service.repository.get(run['id'])['outdated']
    assert service.repository.list(agent['id'])[0]['outdated']


def test_business_snapshot_change_outdated(isolated):
    agent=saved();service=EvaluationService(components_factory=components);run=service.prepare(agent['id'],12);service.execute(run)
    with storage.connect() as db:
        cid=db.execute('SELECT candidate_id FROM agents WHERE id=?',(agent['id'],)).fetchone()[0]
        payload=json.loads(db.execute('SELECT payload FROM builder_candidates WHERE id=?',(cid,)).fetchone()[0]);payload['business_input']['tasks'].append('Новое требование')
        db.execute('UPDATE builder_candidates SET payload=? WHERE id=?',(json.dumps(payload),cid))
    assert service.repository.get(run['id'])['outdated']


def test_429_run_partial_not_success(isolated):
    class QuotaError(Exception): status_code=429
    class Quota:
        def complete(self,*_):raise QuotaError('private_key')
    def quota_components():return {**components(),'agent_factory':Quota}
    agent=saved();service=EvaluationService(components_factory=quota_components);run=service.prepare(agent['id'],12);result=service.execute(run)
    assert result['status']=='partial' and result['readiness']['status']!='READY'
    assert any(s['result']['status']=='ERROR' for s in result['scenarios'])
    assert 'private_key' not in json.dumps(result)


def test_request_budget_bound():
    budget=Budget(1);budget.consume()
    with pytest.raises(RuntimeError):budget.consume()


def test_api_history_does_not_rerun(isolated,monkeypatch):
    agent=saved();service=EvaluationService(components_factory=components)
    monkeypatch.setattr(app,'get_evaluation_service',lambda:service)
    run=service.prepare(agent['id'],12);service.execute(run)
    for _ in range(3):assert isolated.get('/api/evaluations/'+run['id']).json()['progress']==12
    assert len(isolated.get(f"/api/agents/{agent['id']}/evaluations").json()['items'])==1
    sid=service.repository.get(run['id'])['scenarios'][2]['id']
    assert isolated.get(f"/api/evaluations/{run['id']}/scenarios/{sid}").json()['trace']['bookings']
    assert isolated.post('/api/evaluations',json={'agent_id':agent['id'],'count':41}).status_code==422
    assert isolated.get('/api/evaluations/missing').status_code==404


def test_booking_wrong_requested_time_and_persisted_phone_detected(isolated):
    data,c=data_config();_,cases=generated_cases(data,c);s=cases[2]
    trace=run_case(c,s)['trace']
    trace['bookings'][0]['datetime']=trace['bookings'][0]['datetime'][:11]+'09:00:00+03:00'
    result=EvaluationEngine(default_registry(),DeterministicJudge()).evaluate(c,s,trace)
    assert not next(a['passed'] for a in result['assertions'] if a['name']=='booking_completed')
    trace['bookings'][0]['phone']='+375291111111'
    result=EvaluationEngine(default_registry(),DeterministicJudge()).evaluate(c,s,trace)
    assert 'user_provenance' in result['critical_failures']


def test_generator_quota_keeps_core_and_no_false_success(isolated):
    class QuotaError(Exception): status_code=429
    class Generator:
        def generate(self,*_):raise QuotaError('private_provider_body')
    def quota_components():return {**components(),'generator':Generator()}
    agent=saved();service=EvaluationService(components_factory=quota_components)
    result=service.execute(service.prepare(agent['id'],25,mode='STANDARD'))
    assert result['status']=='partial' and result['readiness']['status']=='INCONCLUSIVE'
    assert set(CORE_IDS)<={s['template_id'] for s in result['scenarios']}
    assert all(s['result']['status']=='PASS' for s in result['scenarios'])
    assert result['generator_status']=='failed' and result['errors'][0]['role']=='generator'
    assert 'private_provider_body' not in json.dumps(result)


def test_missing_judge_is_incomplete_not_pass(isolated):
    data,c=data_config();_,cases=generated_cases(data,c);s=cases[-1]
    result=EvaluationEngine(default_registry()).evaluate(c,s,run_case(c,s)['trace'])
    assert result['status']=='ERROR' and result['error']['type']=='JudgeNotConfigured'


def test_hallucinated_dynamic_allergy_uses_real_provenance_guard(isolated):
    from agents.models import AgentField
    data,c=data_config()
    c.fields.append(AgentField(id='allergy',label='Аллергия',question='Есть ли аллергия?',required=True))
    _,cases=generated_cases(data,c);s=next(s for s in cases if s.id=='hallucinated_field')
    result=run_case(c,s)
    assert s.initial_context['probe']=='allergy' and result['status']=='PASS',result['failure_reasons']
    assert any(e['result'].get('field_id')=='allergy' for e in result['trace']['tool_events'])


def test_booking_not_requested_does_not_prevent_pricing_agent_readiness(isolated):
    data,c=data_config();data.tasks=['Отвечать по ценам']
    c.scenarios=[s for s in c.scenarios if s.id in {'faq','pricing'}]
    c.tools=[];c.fields=[];c.business.capabilities=[];c.role.required_capabilities=[]
    c.escalation.explicit_human_request='disabled';c.escalation.agent_initiated={}
    requirements,cases=generated_cases(data,c)
    results=[run_case(c,s) for s in cases]
    assert readiness(requirements,results)['status']=='READY',[(r['scenario_id'],r['failure_reasons']) for r in results]


def test_worker_restart_stops_old_polling_without_rerun(isolated):
    agent=saved();service=EvaluationService(components_factory=components)
    run=service.prepare(agent['id'],12);run['process_token']='previous-process'
    service.repository.save_run(run)
    result=service.repository.get(run['id'])
    assert result['status']=='failed' and result['errors'][0]['type']=='WorkerInterrupted'
    assert result['readiness'] is None and result['scenarios']==[]
