"""Iteration 3.1 regressions: contracts, fact locks, scoped coverage and infrastructure."""
import json
import pytest
import storage
from pydantic import ValidationError
from tests.test_builder import isolated, nova, MockBuilder
from tests.test_evaluation import saved, data_config, generated_cases, run_case
from tests.evaluation_doubles import components, DeterministicJudge, DeterministicAgent
from builder.models import BusinessInput
from builder.service import AgentBuilder
from agents.models import AgentConfig
from services.agent_repository import AgentRepository
from requirement_contract import resolve, reviewed, RequirementContract
from evaluation.service import EvaluationService
from evaluation.requirements import RequirementAnalyzer
from evaluation.scenarios import ScenarioGenerator, render_variant, paraphrases
from evaluation.plan import build_plan, coverage
from evaluation.readiness import readiness
from evaluation.evaluator import EvaluationEngine
from tools.registry import default_registry

@pytest.mark.parametrize('text,key,polarity',[
    ('Не записывать клиентов, только отвечать по ценам','booking','forbidden'),
    ('Не записывать клиентов, только отвечать по ценам','pricing','required'),
    ('Возвраты денег не нужны','unsupported','not_requested'),
    ('CRM не подключать','unsupported','not_requested'),
    ('Передавать сложные вопросы человеку','human_handoff','required'),
    ('Не передавать человеку','human_handoff','forbidden'),
    ('Do not connect CRM','unsupported','not_requested'),
    ('Только отвечать по ценам','pricing','required'),
])
def test_negation_resolution(text,key,polarity):
    assert any(e.requirement_id==key and e.polarity==polarity for e in resolve([text]).entries)

@pytest.mark.parametrize('key,polarity',[('run_python','required'),('pricing','maybe')])
def test_closed_contract_catalog(key,polarity):
    contract=resolve(['Цены']).model_dump();contract['entries'][0].update(requirement_id=key,polarity=polarity)
    with pytest.raises(ValidationError):RequirementContract.model_validate(contract)

def test_user_review_can_correct_unknown_without_changing_source(isolated):
    data=BusinessInput.model_validate(nova());data.tasks=['Помогать посетителям']
    contract=resolve(data.tasks);assert contract.entries[0].polarity=='unknown'
    contract.entries[0].requirement_id='faq';contract.entries[0].polarity='required'
    result=AgentBuilder(MockBuilder()).generate(data,contract)
    assert result['requirement_contract']['source']=='user_reviewed'
    saved_agent=AgentBuilder(MockBuilder()).save(result['candidate_id'],result['review_token'])
    assert saved_agent['requirement_contract']['confirmed']
    assert saved_agent['requirement_contract']['raw_tasks']==data.tasks

@pytest.mark.parametrize('mutation',['raw','source','index','omitted','conflict'])
def test_review_rejects_source_tampering(mutation):
    tasks=['Записывать клиентов','Отвечать по ценам'];c=resolve(tasks).model_dump()
    if mutation=='raw':c['raw_tasks']=['Другое']
    if mutation=='source':c['entries'][0]['source_text']='Другое'
    if mutation=='index':c['entries'][0]['task_index']=19
    if mutation=='omitted':c['entries']=c['entries'][:1]
    if mutation=='conflict':c['entries'].append({**c['entries'][0],'polarity':'forbidden'})
    with pytest.raises(ValueError):reviewed(c,tasks)

def test_contract_mutation_invalidates_preview_token(isolated):
    data=BusinessInput.model_validate(nova());b=AgentBuilder(MockBuilder());result=b.generate(data)
    payload=b.repository.candidate(result['candidate_id']);payload['requirement_contract']['entries'][0]['polarity']='forbidden'
    b.repository.save_candidate(payload)
    with pytest.raises(ValueError):b.save(result['candidate_id'],result['review_token'])

def test_forbidden_booking_and_handoff_tools_are_removed(isolated):
    data=BusinessInput.model_validate(nova());data.tasks=['Не записывать клиентов, только отвечать по ценам','Не передавать человеку','CRM не подключать']
    b=AgentBuilder(MockBuilder());result=b.generate(data)
    assert result['validation']['valid'],result['validation']
    c=AgentConfig.model_validate(result['config'])
    assert not c.tools and not c.fields and c.escalation.explicit_human_request=='disabled'
    assert not any('CRM' in w['message'] for w in result['validation']['warnings'])
    agent=b.save(result['candidate_id'],result['review_token'])
    report=EvaluationService(components_factory=components).execute(EvaluationService(components_factory=components).prepare(agent['id'],20))
    assert report['readiness']['status']=='READY',report['readiness']
    assert report['readiness']['unsupported_requirements']==[]

def test_legacy_contract_inferred_once(isolated,monkeypatch):
    agent=saved();repo=AgentRepository();payload=repo.candidate(agent['candidate_id']);payload.pop('requirement_contract');repo.save_candidate(payload)
    service=EvaluationService(components_factory=components);first=service.prepare(agent['id'],20)
    assert first['requirement_contract']['source']=='legacy_inferred' and first['warnings']
    monkeypatch.setattr('evaluation.service.resolve',lambda *_:pytest.fail('Repeated inference'))
    second=service.prepare(agent['id'],20)
    assert first['contract_hash']==second['contract_hash']
    result=service.execute(second);assert result['readiness']['status']=='LIMITED'

def test_saved_contract_not_reparsed_and_hash_marks_outdated(isolated,monkeypatch):
    agent=saved();s=EvaluationService(components_factory=components)
    monkeypatch.setattr('evaluation.service.resolve',lambda *_:pytest.fail('Unexpected inference'))
    run=s.prepare(agent['id']);repo=AgentRepository();payload=repo.candidate(agent['candidate_id'])
    payload['requirement_contract']['entries'][0]['polarity']='not_requested';repo.save_candidate(payload)
    assert s.repository.get(run['id'])['outdated']

@pytest.mark.parametrize('template',[
    'Хочу записаться на Стрижка в 10:00.',
    'Не записывайте меня на {service} {date} в {time}.',
    'Верните деньги за {service} {date} в {time}.',
    'Запишите на {service} {date} в 10:00.',
    'Запишите на {service} {date} в {time} к другому сотруднику.',
    'Запишите на {service.__class__} {date} в {time}.',
])
def test_variant_semantic_drift_rejected(isolated,template):
    data,c=data_config();_,cases=generated_cases(data,c)
    with pytest.raises(ValueError):render_variant(cases[2],template)

def test_variant_canonical_slots_not_generator_literals(isolated):
    data,c=data_config();_,cases=generated_cases(data,c);case=cases[2]
    text=render_variant(case,paraphrases(case)[0])
    for value in (case.initial_context['service_name'],case.initial_context['day'],case.client.known_data['time']):assert value in text
    assert 'Стрижка' not in text

def test_plan_all_small_services_employees_profiles_and_boundaries(isolated):
    data,c=data_config();r,_=generated_cases(data,c);p=build_plan(data,c,r,25,4,'CORE')
    assert p['policy']['services']=='full' and len(p['selected_services'])==2 and len(p['selected_employees'])==2
    axes=p['desired_axes'];assert {a['entity'] for a in axes if a['axis']=='boundary'}=={'near_closing','unavailable','closed'}
    assert len({a['entity'] for a in axes if a['axis']=='schedule_profile'})==2
    for operation in ('booking','pricing'):
        assert len([a for a in axes if a['axis']=='service_'+operation])==2
    assert all('service_' in case['id'] for case in p['scenarios'] if case['id'].startswith(('booking_happy:service','pricing:')))
    assert p==build_plan(data,c,r,25,4,'CORE')

def test_large_catalog_bounded_seeded_scope(isolated):
    data,c=data_config();data.services=[data.services[0].model_copy(update={'name':f'Услуга {i}'}) for i in range(20)]
    result=AgentBuilder(MockBuilder()).generate(data);c=AgentConfig.model_validate(result['config']);r,_=generated_cases(data,c)
    p=build_plan(data,c,r,40,7,'CORE');other=build_plan(data,c,r,40,8,'CORE')
    assert len(p['selected_services'])==5 and p['policy']['services']=='sampled' and p['selected_services']!=other['selected_services']
    assert len(p['scenarios'])<=40

def test_partial_catalog_cannot_claim_global_ready(isolated):
    agent=saved();s=EvaluationService(components_factory=components);run=s.execute(s.prepare(agent['id'],12))
    assert run['readiness']['status']=='LIMITED'
    assert not run['readiness']['evaluation_coverage']['sufficient']
    assert run['readiness']['evaluation_coverage']['missing_axes']
    assert run['readiness']['dimensions']['scenario_reliability']['percent']==100

def test_core_full_scoped_ready_no_generator_or_ai_simulator(isolated):
    class Forbidden:
        def generate(self,*_):pytest.fail('CORE generator')
        def reply(self,*_):pytest.fail('CORE AI simulator')
    s=EvaluationService(components_factory=lambda:{**components(),'generator':Forbidden(),'simulator':Forbidden()})
    run=s.execute(s.prepare(saved()['id'],25))
    assert run['readiness']['status']=='READY',run['readiness']
    assert run['readiness']['evaluation_coverage']['sufficient'] and run['generator_status']=='NOT_REQUESTED'
    assert run['provider_info']['simulator']=='ScriptedUserSimulator'
    assert run['requests']<=run['plan']['max_calls_estimate']<=240

class QuotaError(Exception):status_code=429

def test_all_agent_429_is_inconclusive_not_failure(isolated):
    class Agent:
        calls=0
        def complete(self,*_):Agent.calls+=1;raise QuotaError('SECRET')
    s=EvaluationService(components_factory=lambda:{**components(),'agent_factory':Agent})
    run=s.execute(s.prepare(saved()['id'],25))
    assert Agent.calls==1 and run['readiness']['status']=='INCONCLUSIVE'
    assert run['readiness']['dimensions']['scenario_reliability']['total']==0
    assert run['readiness']['evaluation_coverage']['executed']==1
    assert all(s['result']['critical_failures']==[] for s in run['scenarios'])
    assert 'SECRET' not in json.dumps(run)

def test_judge_429_retains_deterministic_safety_and_runs_agent(isolated):
    class Judge:
        calls=0
        def judge(self,*_):Judge.calls+=1;raise QuotaError('SECRET')
    s=EvaluationService(components_factory=lambda:{**components(),'judge':Judge()})
    run=s.execute(s.prepare(saved()['id'],25))
    assert Judge.calls==1 and run['readiness']['status']=='INCONCLUSIVE'
    assert run['readiness']['dimensions']['safety_escalation']['percent']==100
    assert any(c['result']['status']=='PASS' and c['template_id']=='booking_happy' for c in run['scenarios'])
    assert not any(c['result']['trace']['stop_reason']=='not_run' for c in s.repository.get(run['id'],details=True)['scenarios'])

@pytest.mark.parametrize('infrastructure',['agent','judge'])
def test_proven_unsafe_write_survives_infrastructure_failure(isolated,infrastructure):
    data,c=data_config();r,cases=generated_cases(data,c);case=cases[2];trace=run_case(c,case)['trace']
    trace['steps'][-1]['user']='Ну наверное.'
    if infrastructure=='agent':trace['error']={'type':'QuotaError','status_code':429}
    class Judge:
        def judge(self,*_):raise QuotaError()
    result=EvaluationEngine(default_registry(),Judge()).evaluate(c,case,trace)
    assert result['status']=='FAIL' and 'no_unconfirmed_write' in result['critical_failures']
    assert readiness(r,[result])['status']=='NOT_READY'

def test_primary_booking_fail_plus_other_429_not_ready(isolated):
    data,c=data_config();r,cases=generated_cases(data,c);result=run_case(c,cases[2]);result['status']='FAIL'
    error={**result,'scenario_id':'other','template_id':'pricing','status':'ERROR','error':{'status_code':429},'critical_failures':[]}
    assert readiness(r,[result,error])['status']=='NOT_READY'
    assert readiness(r,[result,error])['dimensions']['scenario_reliability']['total']==1

@pytest.mark.parametrize('error',[QuotaError(),TimeoutError(),ValueError()])
def test_generator_errors_run_trusted_core_first(isolated,error):
    class Generator:
        def generate(self,*_):
            assert completed
            raise error
    completed=[]
    class Agent(DeterministicAgent):
        def complete(self,*args):completed.append(True);return super().complete(*args)
    s=EvaluationService(components_factory=lambda:{**components(),'generator':Generator(),'agent_factory':Agent})
    run=s.execute(s.prepare(saved()['id'],25,mode='STANDARD'))
    assert run['generator_status']=='failed' and all(c['result']['status']=='PASS' for c in run['scenarios'])
    assert run['readiness']['status']=='INCONCLUSIVE'

def test_deep_rejected_without_spending(isolated):
    agent=saved();s=EvaluationService(components_factory=lambda:pytest.fail('No provider call'))
    with pytest.raises(ValueError):s.prepare(agent['id'],mode='DEEP')
    assert isolated.post('/api/evaluations',json={'agent_id':agent['id'],'mode':'DEEP'}).status_code==422

def test_requirements_http_preview_and_agent_roundtrip(isolated):
    data=nova();review=isolated.post('/api/builder/requirements',json=data).json()
    candidate=isolated.post('/api/builder/generate',json={**data,'requirement_contract':review['contract']}).json()
    agent=isolated.post('/api/agents',json={'candidate_id':candidate['candidate_id'],'review_token':candidate['review_token']}).json()
    contract=isolated.get('/api/agents/'+agent['id']).json()['requirement_contract']
    assert contract['confirmed'] and contract['source']=='user_reviewed'

def test_standard_variants_success_and_fact_lock(isolated):
    class Generator:
        def generate(self,public,count,errors):
            return {'variants':[{'template_id':'booking_happy','paraphrase_template':'Хочу записаться на {service} {date} в {time}, пожалуйста.'} for _ in range(count)]}
    s=EvaluationService(components_factory=lambda:{**components(),'generator':Generator()})
    run=s.execute(s.prepare(saved()['id'],25,mode='STANDARD'))
    assert run['generator_status']=='completed' and run['readiness']['status']=='READY',run['readiness']
    assert all(c['result']['status']=='PASS' for c in run['scenarios'])

def test_positive_faq_and_hours_have_actual_scenarios(isolated):
    data=BusinessInput.model_validate(nova());data.tasks+=['Отвечать по графику работы','Отвечать на вопросы об услугах']
    b=AgentBuilder(MockBuilder());candidate=b.generate(data);a=b.save(candidate['candidate_id'],candidate['review_token'])
    s=EvaluationService(components_factory=components);run=s.execute(s.prepare(a['id'],25))
    assert run['readiness']['status']=='READY',run['readiness']
    assert {'requirement:faq','requirement:opening_hours'}<={case['id'] for case in run['scenarios']}

def test_completion_denominator_includes_generator_missing_variants(isolated):
    p={'scenarios':[{'id':'one','coverage_axes':{}}],'optional_variants':2,'desired_axes':[],
       'excluded_scenarios':[],'selected_services':[],'selected_employees':[],'policy':{}}
    result=coverage(p,[{'scenario_id':'one','status':'PASS','agent_completed':True}])
    assert result['planned']==3 and result['evaluated']==1 and result['completion_percent']==33

def test_history_reads_saved_plan_without_resampling(isolated,monkeypatch):
    agent=saved();s=EvaluationService(components_factory=components);run=s.prepare(agent['id'],25,seed=99)
    monkeypatch.setattr('evaluation.service.build_plan',lambda *_:pytest.fail('Read resampled plan'))
    for _ in range(3):assert s.repository.get(run['id'])['plan']==run['plan']

def test_changed_raw_tasks_requires_new_review_not_silent_inference(isolated):
    agent=saved();repo=AgentRepository();payload=repo.candidate(agent['candidate_id']);payload['business_input']['tasks']=['Другая задача'];repo.save_candidate(payload)
    with pytest.raises(ValueError):EvaluationService(components_factory=components).prepare(agent['id'])

def test_wrong_price_proven_despite_judge_timeout(isolated):
    data,c=data_config();_,cases=generated_cases(data,c);case=cases[-1];trace=run_case(c,case)['trace']
    trace['transcript'][-1]['content']='Стоимость 999 BYN.'
    class Judge:
        def judge(self,*_):raise TimeoutError()
    result=EvaluationEngine(default_registry(),Judge()).evaluate(c,case,trace)
    assert result['status']=='FAIL' and result['error']['role']=='judge' and result['deterministic_status']=='FAIL'

def test_negative_unsupported_does_not_block_requirement_coverage(isolated):
    data,c=data_config();data.tasks+=['Возвраты денег не нужны','CRM не подключать']
    requirements=RequirementAnalyzer(default_registry()).analyze(data,c,resolve(data.tasks))
    assert all(r.coverage_status=='COVERED' for r in requirements)

def test_unknown_required_custom_prevents_ready(isolated):
    data,c=data_config();data.tasks+=['Обнимать посетителей']
    r,cases=generated_cases(data,c)
    assert any(req.polarity=='unknown' and not req.supported for req in r)
    assert readiness(r,[run_case(c,s) for s in cases])['status']=='LIMITED'

def test_server_booking_controller_covers_catalog_even_with_weak_model(isolated):
    from providers.base import ModelReply
    class FirstOnly(DeterministicAgent):
        def complete(self,messages,tools):
            if any(m.role=='user' and 'стрижка' in m.text.casefold() for m in messages):
                return ModelReply('Эту услугу я не могу обслужить.')
            return super().complete(messages,tools)
    s=EvaluationService(components_factory=lambda:{**components(),'agent_factory':FirstOnly})
    run=s.execute(s.prepare(saved()['id'],25))
    # Readiness concerns the composite agent, not standalone model intelligence.
    # Runtime now serves every configured booking service without this weak model.
    assert run['readiness']['status']=='READY'
    first=[c for c in run['scenarios'] if c['template_id']=='booking_happy' and c['initial_context'].get('service_name')=='Маникюр']
    second=[c for c in run['scenarios'] if c['template_id']=='booking_happy' and c['initial_context'].get('service_name')=='Стрижка']
    assert first and all(c['result']['status']=='PASS' for c in first)
    assert second and all(c['result']['status']=='PASS' for c in second)

def test_malicious_generator_does_not_fail_agent_cases(isolated):
    class Generator:
        calls=0
        def generate(self,*_):
            Generator.calls+=1
            return {'variants':[{'template_id':'booking_happy','paraphrase_template':'Хочу Стрижка 10:00.'}]}
    s=EvaluationService(components_factory=lambda:{**components(),'generator':Generator()})
    run=s.execute(s.prepare(saved()['id'],25,mode='STANDARD'))
    assert Generator.calls==2 and run['generator_status']=='failed'
    assert run['readiness']['status']=='INCONCLUSIVE'
    assert all(c['result']['status']=='PASS' for c in run['scenarios'])

def test_new_builder_conflicting_tasks_require_review(isolated):
    data=BusinessInput.model_validate(nova());data.tasks=['Записывать клиентов','Не записывать клиентов']
    with pytest.raises(ValueError):AgentBuilder(MockBuilder()).generate(data)
