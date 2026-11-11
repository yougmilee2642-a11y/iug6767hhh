import copy
import json
import pytest
from tests.test_evaluation_quick import isolated_db, saved_quick
from tests.test_track1_quick import IntakeProvider
from services.track1_service import QuickInput, Track1Service, make_config
from services.agent_repository import AgentRepository
from evaluation.quick import quick_scenarios, quick_plan
from evaluation.simulation import SimulationEngine
from evaluation.providers import ScriptedUserSimulator
from evaluation.evaluator import EvaluationEngine
from evaluation.service import EvaluationService, default_components
from evaluation.local import evaluation_options, LocalJudge
from providers.base import ModelReply
from providers.ollama import OllamaProvider
from tools.registry import default_registry
import storage


class Judge:
    def judge(self,case): return {'passed':True,'score':1,'reasons':[],'flags':[]}


def run_case(role,sid,provider=IntakeProvider):
    config=make_config(QuickInput(business_name='Тест',role=role,facts='Наш телефон +375291112233.'),'test')
    case=next(s for s in quick_scenarios(config) if s.id==sid)
    trace=SimulationEngine(provider,ScriptedUserSimulator(),default_registry()).run(config,case)
    return config,case,trace


def test_callback_success_uses_real_confirmed_row_and_user_evidence(isolated_db):
    config,case,trace=run_case('secretary','callback_confirmed')
    result=EvaluationEngine(default_registry(),Judge()).evaluate(config,case,trace)
    assert result['status']=='PASS',result['failure_reasons']
    assert trace['callback_requests'][0]['payload']['request_details']=='доставка'
    with storage.connect() as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='callback_requests'").fetchone()


@pytest.mark.parametrize('sid',['callback_refused','callback_missing_phone','callback_no_fabrication','callback_cancel'])
def test_callback_negative_paths_do_not_write(isolated_db,sid):
    config,case,trace=run_case('secretary',sid)
    assert not trace['callback_requests']
    result=EvaluationEngine(default_registry(),Judge()).evaluate(config,case,trace)
    assert all(a['passed'] for a in result['assertions'] if a['name'] in {'no_unconfirmed_write','user_provenance','callback_not_saved'})


@pytest.mark.parametrize('corruption',['no_event','no_step','other_interaction','other_agent','wrong_payload','wrong_consent','invalid_evidence'])
def test_corrupt_callback_proof_is_rejected(isolated_db,corruption):
    config,case,trace=run_case('secretary','callback_confirmed')
    if corruption=='no_event': trace['tool_events']=[]
    elif corruption=='no_step': trace['steps']=[]
    elif corruption=='other_interaction': trace['callback_requests'][0]['interaction_id']='other'
    elif corruption=='other_agent': trace['callback_requests'][0]['agent_id']='other'
    elif corruption=='wrong_payload': trace['callback_requests'][0]['payload']['phone']='+375299999999'
    elif corruption=='wrong_consent': trace['steps'][-1]['user']='Ну наверное.'
    else: trace['action_provenance']['phone']['evidence']['text']='not in transcript'
    result=EvaluationEngine(default_registry(),Judge()).evaluate(config,case,trace)
    assert result['status']=='FAIL'
    assert any(not a['passed'] for a in result['assertions'] if a['name'] in {'no_unconfirmed_write','user_provenance'})


@pytest.mark.parametrize('text,allowed',[
    ('Наш телефон +375291112233.',True),
    ('Телефон компании указан на сайте.',True),
    ('У меня нет информации о вашем телефоне.',True),
    ('Куда вам перезвонить?',False),
    ('Как к вам обращаться?',False),
    ('Можете оставить свой номер?',False),
    ('Назовите ваш телефон.',False),
])
def test_company_contact_is_distinct_from_collecting_client_contact(isolated_db,text,allowed):
    class Answer:
        def complete(self,messages,tools): return ModelReply(text)
    config,case,trace=run_case('support','support_no_contact',Answer)
    result=EvaluationEngine(default_registry(),Judge()).evaluate(config,case,trace)
    assert next(a['passed'] for a in result['assertions'] if a['name']=='no_contact_collection') is allowed


def test_missing_callback_table_is_allowed_but_bad_payload_is_error(isolated_db,monkeypatch):
    import tools.callback
    original=tools.callback.callback_tool
    def corrupt_tool():
        tool=original();execute=tool.execute
        def corrupt(arguments,context):
            result=execute(arguments,context)
            with storage.connect() as db: db.execute("UPDATE callback_requests SET payload='not json'")
            return result
        tool.execute=corrupt
        return tool
    monkeypatch.setattr(tools.callback,'callback_tool',corrupt_tool)
    _,_,trace=run_case('secretary','callback_confirmed')
    assert trace['error']['code']=='callback_result_read_error'


@pytest.mark.parametrize('role',['secretary','support'])
@pytest.mark.parametrize('count',[12,20,40])
def test_bounded_plan_covers_every_mandatory_scenario(isolated_db,role,count):
    config=make_config(QuickInput(business_name='Тест',role=role),'test')
    plan=quick_plan(config,count,7,'CORE')
    assert len(plan['scenarios'])==count
    assert set(plan['mandatory_scenarios'])<={s['template_id'] for s in plan['scenarios']}
    assert plan['request_budget']==240


def test_report_becomes_outdated_after_input_or_config_change(isolated_db):
    agent=saved_quick('support');service=EvaluationService()
    run=service.prepare(agent['id'],12,0,'CORE')
    assert service.repository.get(run['id'])['current']
    repo=AgentRepository();candidate=repo.candidate(agent['candidate_id'])
    candidate['input']['facts']='Новый факт';repo.save_candidate(candidate)
    assert service.repository.get(run['id'])['outdated']
    candidate['input']['facts']='Компания принимает вопросы клиентов.';repo.save_candidate(candidate)
    assert service.repository.get(run['id'])['current']
    config=copy.deepcopy(agent['config']);config['greeting']='Другое приветствие'
    from agents.models import AgentConfig
    repo.save(AgentConfig.model_validate(config))
    assert service.repository.get(run['id'])['outdated']


def test_blank_city_stays_unspecified_in_quick_snapshot(isolated_db):
    service=Track1Service();candidate=service.preview(QuickInput(business_name='Тест',city='',role='support'))
    agent=service.save(candidate['candidate_id'],candidate['review_token'])
    run=EvaluationService().prepare(agent['id'],12)
    assert run['business_snapshot']['city']=='' and run['business_snapshot']['schedule']=={}


def test_local_components_and_options_never_select_cloud(monkeypatch):
    monkeypatch.setenv('CALLWISE_LOCAL_ONLY','true');monkeypatch.setenv('OLLAMA_MODEL','qwen2.5:3b')
    monkeypatch.setattr(OllamaProvider,'available',lambda self:True)
    components=default_components()
    assert isinstance(components['agent_factory'](),OllamaProvider)
    assert isinstance(components['judge'],LocalJudge)
    assert components['provider_info']['quality_independent'] is False
    assert components['preflight']()['provider']=='Ollama'
    assert evaluation_options()['available']
    monkeypatch.setattr(OllamaProvider,'available',lambda self:False)
    assert not evaluation_options()['available']


def test_local_judge_validates_visible_json_and_does_not_use_cloud(monkeypatch):
    def structured(self,messages,schema,predict):
        assert json.loads(messages[1].text)=={'criteria':['no_contact_collection']}
        assert schema['properties']['score']['enum']==[0,1]
        return {'passed':True,'score':1,'reasons':[],'flags':[]}
    monkeypatch.setattr(OllamaProvider,'structured',structured)
    from evaluation.providers import Budget
    assert LocalJudge(Budget()).judge({'criteria':['no_contact_collection']})['passed']


def test_same_model_quality_does_not_claim_independent_ready(isolated_db):
    # Force completed results so readiness policy is tested independently of language quality.
    import evaluation.service as module
    from unittest.mock import patch
    agent=saved_quick('support')
    comps={'agent_factory':IntakeProvider,'simulator':ScriptedUserSimulator(),'judge':Judge(),
           'provider_info':{'provider':'Ollama','quality_independent':False}}
    service=EvaluationService(components_factory=lambda:comps)
    run=service.prepare(agent['id'],12)
    with patch.object(module,'readiness',return_value={'status':'READY','recommendation':'x'}): result=service.execute(run)
    assert result['readiness']['status']=='LIMITED'
    assert result['readiness']['quality_independent'] is False


def test_local_api_launches_without_cloud_and_keeps_owner_guard(isolated_db,monkeypatch):
    import app
    from fastapi.testclient import TestClient
    monkeypatch.setenv('CALLWISE_LOCAL_ONLY','true')
    monkeypatch.setenv('CALLWISE_OWNER_PASSWORD','')
    class Service:
        def launch(self,agent_id,count,seed,mode):
            assert isinstance(default_components()['agent_factory'](),OllamaProvider)
            return {'id':'local-test','status':'pending'}
    monkeypatch.setattr(app,'get_evaluation_service',Service)
    client=TestClient(app.app)
    assert client.post('/api/evaluations',json={'agent_id':'test'}).status_code==202
    assert client.post('/api/evaluations',json={'agent_id':'test'},headers={'origin':'https://evil.example'}).status_code==403
    monkeypatch.setenv('CALLWISE_OWNER_PASSWORD','synthetic-owner-password')
    assert client.post('/api/evaluations',json={'agent_id':'test'}).status_code==401


@pytest.mark.parametrize('text',['Соедините меня с владельцем немедленно.','Хочу поговорить с менеджером.'])
def test_owner_request_is_handled_by_server_without_model(isolated_db,text):
    from agents.factory import create_runtime
    from agents.runtime import new_interaction
    class NeverCalled:
        def complete(self,*args): pytest.fail('Explicit human request must be handled by server')
    config=make_config(QuickInput(business_name='Тест',role='support'),'test')
    runtime=create_runtime(config,NeverCalled(),default_registry());state=new_interaction(config)
    runtime.turn(state,text)
    assert state['status']=='escalated'
    assert state['tool_events'][0]['result']['escalation']['reason_type']=='explicit_user_request'
    assert 'Реального соединения' in state['transcript'][-1]['content']


@pytest.mark.parametrize('preview,expected',[(True,'PASS'),(False,'FAIL')])
def test_same_model_opinion_is_separate_from_deterministic_result(isolated_db,preview,expected):
    class Answer:
        def complete(self,messages,tools): return ModelReply('Наш телефон +375291112233.')
    class UncertainJudge:
        def judge(self,case): return {'passed':False,'score':0,'reasons':['Нужно проверить ответ вручную.'],'flags':['off_goal']}
    config,case,trace=run_case('support','support_no_contact',Answer)
    result=EvaluationEngine(default_registry(),UncertainJudge(),quality_preview=preview).evaluate(config,case,trace)
    assert result['status']==expected
    assert result['judge_status']=='FAIL'
    assert bool(result['quality_review_notes']) is preview
