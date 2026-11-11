import copy
import json
from types import SimpleNamespace as NS
import pytest
import storage
from builder.models import BusinessInput
from builder.service import AgentBuilder
from agents.models import AgentConfig
from agents.validation import validate_agent
from tests.test_builder import isolated,nova,draft,MockBuilder
from tests.evaluation_doubles import components,DeterministicAgent,DeterministicJudge
from evaluation.requirements import RequirementAnalyzer
from evaluation.scenarios import trusted_scenarios,service_context,booking_context,render_variant
from evaluation.plan import build_plan
from evaluation.service import EvaluationService
from evaluation.simulation import SimulationEngine
from evaluation.evaluator import EvaluationEngine
from evaluation.providers import Budget,ScriptedUserSimulator,StructuredGroq,live_agent_provider
from evaluation.preflight import provider_preflight,ProbeValue
from tools.registry import default_registry
from providers.base import ConversationMessage,ToolCall,ToolSpec,ModelReply
from providers.groq import GroqProvider
from providers.errors import ProviderError,normalize_error


def price_data():
    value=nova(); value.update(business_name='Price Test',desired_role='Консультант',employees=[],tasks=['Отвечать по ценам'],
        services=[{'name':'Консультация','price':50,'currency':'BYN','duration_minutes':30}])
    return BusinessInput.model_validate(value)


def price_candidate():
    value=draft();value.update(scenarios=['pricing'],tools=[],role_name='Консультант')
    builder=AgentBuilder(MockBuilder(value));candidate=builder.generate(price_data())
    assert candidate['validation']['valid'],candidate['validation']
    return builder,candidate


def test_price_only_saved_plan_scenario_and_run(isolated):
    builder,candidate=price_candidate()
    agent=builder.save(candidate['candidate_id'],candidate['review_token'])
    config=AgentConfig.model_validate(agent['config']);data=price_data()
    requirements=RequirementAnalyzer(default_registry()).analyze(data,config)
    assert next(r for r in requirements if r.category=='pricing').coverage_status=='COVERED'
    facts=service_context(data,config)
    assert facts['price']==50 and facts['currency']=='BYN'
    assert not {'employee_id','day','clock','datetime'} & facts.keys()
    assert booking_context(data,config)=={}
    plan=build_plan(data,config,requirements,20,0,'CORE')
    assert plan['selected_employees']==[]
    assert plan['desired_axes']==[{'axis':'service_pricing','entity':facts['service_id']}]
    cases=trusted_scenarios(data,config,requirements)
    assert all(not s.expected_tools for s in cases if s.category=='booking')
    price=cases[11]
    assert render_variant(price,'Какая цена на {service}?')=='Какая цена на Консультация?'
    trace=SimulationEngine(DeterministicAgent,ScriptedUserSimulator(),default_registry()).run(config,price)
    result=EvaluationEngine(default_registry(),DeterministicJudge()).evaluate(config,price,trace)
    assert result['status']=='PASS'
    service=EvaluationService(components_factory=components)
    report=service.execute(service.prepare(agent['id'],20,0,'CORE'))
    assert report['provider_health']['status']=='NOT_REQUIRED'
    assert report['readiness']['status']=='READY'
    assert all(s['result']['status']=='PASS' for s in report['scenarios'])


@pytest.mark.parametrize('faq_only',[False,True])
def test_empty_pricing_catalog_is_missing_not_ready(isolated,faq_only):
    _,candidate=price_candidate();config=AgentConfig.model_validate(candidate['config']);data=price_data()
    data.services=[];config.business.knowledge['services']=[]
    if faq_only:
        from builder.catalog import SCENARIOS
        config.scenarios=[SCENARIOS['faq']]
    requirements=RequirementAnalyzer(default_registry()).analyze(data,config)
    requirement=next(r for r in requirements if r.category=='pricing')
    assert requirement.coverage_status=='MISSING'
    assert any('catalog:services' in m for m in requirement.missing)
    from evaluation.readiness import readiness
    assert readiness(requirements,[])['status']!='READY'
    assert build_plan(data,config,requirements,12,0,'CORE')['scenarios']
    case=trusted_scenarios(data,config,requirements)[11]
    assert 'price_grounded' in case.assertions and 'unknown_grounded' not in case.assertions
    trace=SimulationEngine(DeterministicAgent,ScriptedUserSimulator(),default_registry()).run(config,case)
    assert EvaluationEngine(default_registry(),DeterministicJudge()).evaluate(config,case,trace)['status']=='FAIL'


@pytest.mark.parametrize('change',[lambda s:s.pop('price'),lambda s:s.update(price=float('nan')),lambda s:s.update(currency=''),lambda s:s.update(price=-1)])
def test_invalid_price_facts_missing(isolated,change):
    _,candidate=price_candidate();config=AgentConfig.model_validate(candidate['config'])
    change(config.business.knowledge['services'][0])
    r=next(r for r in RequirementAnalyzer(default_registry()).analyze(price_data(),config) if r.category=='pricing')
    assert r.coverage_status=='MISSING'


def test_pricing_no_duration_or_calendar_dependency_booking_requires_them(isolated):
    _,candidate=price_candidate();config=AgentConfig.model_validate(candidate['config']);data=price_data()
    config.business.knowledge['services'][0].pop('duration_minutes')
    config.business.schedule={}
    assert next(r for r in RequirementAnalyzer(default_registry()).analyze(data,config) if r.category=='pricing').coverage_status=='COVERED'
    data.tasks=['Записывать клиентов']
    assert next(r for r in RequirementAnalyzer(default_registry()).analyze(data,config) if r.category=='booking').coverage_status=='MISSING'
    assert booking_context(data,config)=={}


def test_opening_hours_knowledge_dependency(isolated):
    _,candidate=price_candidate();config=AgentConfig.model_validate(candidate['config']);data=price_data()
    from builder.catalog import SCENARIOS
    config.scenarios.append(SCENARIOS['opening_hours']);data.tasks=['Отвечать о часах работы']
    requirements=RequirementAnalyzer(default_registry()).analyze(data,config)
    assert next(r for r in requirements if r.category=='opening_hours').coverage_status=='COVERED'
    config.business.schedule={}
    assert next(r for r in RequirementAnalyzer(default_registry()).analyze(data,config) if r.category=='opening_hours').coverage_status=='MISSING'


class SDKError(Exception):
    def __init__(self,status,body): self.status_code=status;self.body=body


def client_of(create): return NS(chat=NS(completions=NS(create=create)))


def answer(text='OK',calls=()): return NS(choices=[NS(message=NS(content=text,tool_calls=list(calls)))])


TOOL=ToolSpec('check_slots','Check synthetic slots',{'type':'object','properties':{'service':{'type':'string'}},'required':['service'],'additionalProperties':False})


def test_proven_400_retry_same_payload_and_count():
    attempts=[]
    def create(**options):
        attempts.append(copy.deepcopy(options))
        if len(attempts)==1: raise SDKError(400,{'error':{'type':'invalid_request_error','code':'tool_use_failed',
            'failed_generation':{'reason':'Tool call arguments are not valid JSON','tool_name':'check_slots','attempted_arguments':'SECRET_KEY +375299876543'}}})
        return answer()
    budget=Budget(3);provider=GroqProvider(client_of(create),model='openai/gpt-oss-20b',budget=budget)
    provider.complete([ConversationMessage('user','synthetic')],[TOOL])
    assert budget.requests==2 and provider.retry_count==1
    assert attempts[0]['messages']==attempts[1]['messages'] and attempts[0]['tools']==attempts[1]['tools']
    assert attempts[0]['temperature']==.2 and attempts[1]['temperature']==0
    assert attempts[0]['reasoning_effort']=='low' and attempts[0]['tool_choice']=='auto' and attempts[0]['parallel_tool_calls'] is False
    assert attempts[0]['max_completion_tokens']==1800
    public=json.dumps(provider.metadata())
    assert 'tool_generation_failed' in public and 'invalid_tool_arguments_json' in public
    assert 'SECRET_KEY' not in public and '+375299876543' not in public and 'attempted_arguments' not in public


@pytest.mark.parametrize('status,body,category',[
    (400,{'code':'unsupported_parameter','message':'reasoning_effort not supported','failed_generation':{'reason':'invalid tool call'}},'invalid_request'),
    (400,{'message':'invalid schema'},'invalid_request'),
    (400,{'code':'model_not_found'},'model_unsupported'),
    (400,{'message':'SECRET random bad input'},'invalid_request'),
    (400,{'code':'unsupported_parameter','failed_generation':{'reason':'invalid tool call'}},'invalid_request'),
    (400,{'code':'tool_use_failed','message':'Invalid tools schema: required properties','failed_generation':{'reason':'not valid JSON'}},'invalid_request'),
    (401,{'message':'SECRET authentication'},'authentication'),
    (429,{'message':'SECRET rate limit'},'rate_limit')])
def test_nonretryable_errors_one_attempt(status,body,category):
    calls=[]
    def create(**options): calls.append(options);raise SDKError(status,{'error':body})
    provider=GroqProvider(client_of(create),model='openai/gpt-oss-20b')
    with pytest.raises(ProviderError) as caught: provider.complete([ConversationMessage('user','synthetic')],[TOOL])
    assert len(calls)==1 and not caught.value.retryable and caught.value.category==category
    assert 'SECRET' not in json.dumps(caught.value.public())


def test_retry_stops_after_second_failure_and_honors_budget():
    def create(**_): raise SDKError(400,{'error':{'code':'tool_use_failed','failed_generation':'SECRET'}})
    provider=GroqProvider(client_of(create),model='openai/gpt-oss-20b',budget=Budget(12))
    with pytest.raises(ProviderError): provider.complete([ConversationMessage('user','test')],[TOOL])
    assert provider.request_count==2 and provider.retry_count==1
    limited=GroqProvider(client_of(create),model='openai/gpt-oss-20b',budget=Budget(1))
    with pytest.raises(RuntimeError): limited.complete([ConversationMessage('user','test')],[TOOL])
    assert limited.request_count==1


def test_tool_result_message_encoding():
    captured={}
    def create(**options): captured.update(options);return answer()
    provider=GroqProvider(client_of(create),model='openai/gpt-oss-20b')
    provider.complete([ConversationMessage('assistant',calls=[ToolCall('call_1','check_slots',{'service':'synthetic'})]),
        ConversationMessage('tool',call_id='call_1',result={'slots':[]})],[TOOL])
    assert captured['messages'][0]['content'] is None
    assert captured['messages'][1]=={'role':'tool','content':'{"slots": []}','tool_call_id':'call_1'}


def fake_preflight_agent(budget,model):
    def create(**options):
        if options.get('tools'):
            return answer('',[NS(id='call_probe',function=NS(name='lookup_test_value',arguments='{"item_id":"probe_item"}'))])
        return answer('CALLWISE_SYNTHETIC_734' if any(m['role']=='tool' for m in options['messages']) else 'READY')
    provider=GroqProvider(client_of(create),model=model,budget=budget)
    provider.close=lambda:None
    return provider


def fake_structured(budget,role,model):
    return StructuredGroq(role,budget,model_id=model,client=client_of(lambda **_:answer('{"value":"PREFLIGHT_OK"}')))


def test_preflight_pass_real_adapter_messages_and_counts():
    parent=Budget(12)
    result=provider_preflight(parent,agent_factory=fake_preflight_agent,structured_factory=fake_structured)
    assert result['status']=='PASS' and result['request_count']==parent.requests==4
    assert all(p['status']=='PASS' for p in result['probes'].values())
    assert result['retry_count']==0 and result['fallback'] is False


def test_preflight_failure_skips_remaining_and_cloud_cases(isolated):
    builder,candidate=price_candidate();agent=builder.save(candidate['candidate_id'],candidate['review_token'])
    calls=[]
    def broken(budget,model):
        def create(**options): calls.append(options);raise SDKError(429,{'error':{'message':'SECRET +375299876543'}})
        provider=GroqProvider(client_of(create),model=model,budget=budget);provider.close=lambda:None
        return provider
    budget=Budget(12)
    result=provider_preflight(budget,agent_factory=broken)
    assert result['status']=='FAIL' and result['request_count']==1
    assert result['probes']['agent_tools']['status']=='NOT_TESTED'
    configured=components();configured['preflight']=lambda:result;configured['budget']=budget
    configured['agent_factory']=lambda:pytest.fail('No scenarios after failed preflight')
    service=EvaluationService(components_factory=lambda:configured)
    run=service.execute(service.prepare(agent['id'],20,0,'CORE'))
    assert run['readiness']['status']=='INCONCLUSIVE' and run['requests']==1
    assert all(s['result']['status']=='ERROR' and not s['result']['attempted'] for s in run['scenarios'])
    assert 'SECRET' not in json.dumps(run) and '+375299876543' not in json.dumps(run)


def test_unknown_model_capability_fails_without_request():
    models={r:'unknown/not-verified' for r in ('agent','generator','judge','simulator')}
    result=provider_preflight(models=models,agent_factory=lambda *_:pytest.fail('No HTTP for unknown capabilities'))
    assert result['status']=='FAIL' and result['request_count']==0 and result['error']['category']=='model_unsupported'


def test_arbitrary_failed_generation_text_sanitized_and_not_retryable():
    error=normalize_error(SDKError(400,{'error':{'type':'invalid_request_error','failed_generation':{
        'reason':'Client +375299876543 KEY SECRET','tool_name':'private_client_SECRET','attempted_arguments':{'phone':'SECRET'}}}}),
        'openai/gpt-oss-20b','agent',['check_slots'])
    serialized=json.dumps(error.public())
    assert error.category=='invalid_request' and not error.retryable
    assert error.diagnostics=={'failed_generation_present':True,'error_type':'invalid_request_error'}
    assert 'SECRET' not in serialized and '+375299876543' not in serialized


def test_structured_failure_never_retries_or_saves_body():
    calls=[]
    def create(**options):
        calls.append(options)
        raise SDKError(400,{'error':{'code':'json_validate_failed','failed_generation':{'reason':'SECRET +375299876543'}}})
    budget=Budget(12)
    adapter=StructuredGroq('judge',budget,model_id='openai/gpt-oss-20b',client=client_of(create))
    with pytest.raises(ProviderError) as caught: adapter.request('synthetic',{'value':'OK'},ProbeValue)
    assert len(calls)==budget.requests==1 and not caught.value.retryable
    assert caught.value.category=='structured_output_failed'
    assert 'SECRET' not in json.dumps(caught.value.public())


def test_functional_suite_round_trip_and_four_requests_without_network():
    from evaluation.provider_diagnostics import functional_smoke
    from evaluation.config import model_names
    class Adapter:
        def __init__(self,budget): self.provider=DeterministicAgent();self.budget=budget;self.requests=0
        def complete(self,messages,tools):
            self.budget.consume();self.requests+=1
            # Use the real tool history on the continuation; no fabricated slot result.
            if any(m.role=='tool' and 'slots' in (m.result or {}) for m in messages): return ModelReply('Доступное время указано в результате проверки.')
            return self.provider.complete(messages,tools)
        def metadata(self): return {'request_count':self.requests,'retry_count':0,'retry_diagnostics':[]}
        def close(self): pass
    budget=Budget(12)
    result=functional_smoke(budget,model_names(),agent_factory=lambda budget,model:Adapter(budget))
    assert result['status']=='PASS' and result['tool_round_trip']
    assert result['request_count']==budget.requests==4 and len(result['observations'])==5
    assert result['bookings_written']==0


def test_functional_stops_immediately_on_rate_limit():
    from evaluation.provider_diagnostics import functional_smoke
    from evaluation.config import model_names
    class Limited:
        def __init__(self,budget): self.budget=budget
        def complete(self,*_):
            self.budget.consume();raise ProviderError('openai/gpt-oss-20b','agent','rate_limit',429)
        def metadata(self): return {'retry_count':0}
        def close(self): pass
    budget=Budget(12)
    result=functional_smoke(budget,model_names(),agent_factory=lambda budget,model:Limited(budget))
    assert result['status']=='INCONCLUSIVE' and result['request_count']==budget.requests==1
    assert len(result['observations'])==1 and result['observations'][0]['status']=='ERROR'
