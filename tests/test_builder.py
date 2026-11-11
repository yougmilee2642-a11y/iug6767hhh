import copy
import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pytest
from fastapi.testclient import TestClient
import storage
import app
from builder.models import BusinessInput, BuilderDraft
from builder.mapping import map_draft, catalog, stable_id
from builder.service import AgentBuilder
from builder.presets import user_field
from providers.builder import strict_schema
from services.agent_service import AgentService
from services.agent_repository import AgentRepository
from agents.factory import create_runtime
from agents.runtime import new_interaction
from agents.validation import validate_agent
from providers.base import ModelReply, ToolCall
from services.booking_service import BookingService


def nova():
    return {"business_name":"Nova Beauty", "business_type":"Салон красоты", "city":"Минск", "timezone":"Europe/Minsk",
        "schedule": {str(d): [{"start":"09:00" if d < 5 else "10:00", "end":"20:00" if d < 5 else "18:00"}] if d < 6 else [] for d in range(7)},
        "services":[{"name":"Маникюр","price":50,"currency":"BYN","duration_minutes":60},{"name":"Стрижка","price":40,"currency":"BYN","duration_minutes":45}],
        "employees":["Анна","Мария"], "desired_role":"Администратор", "tasks":["Рассказать об услугах и ценах","Записать клиента","Передать человеку"]}


def draft():
    return {"agent_name":"AI-администратор Nova Beauty","role_name":"Администратор","business_summary":"Салон красоты",
        "scenarios":["booking","faq","pricing","opening_hours","human_handoff"],"tools":["check_slots","create_booking","transfer_to_human"],
        "fields":[],"conversation_style":"brief","escalation_reasons":["complaint","unsupported","tool_failure"],"unsupported_requirements":[]}


class MockBuilder:
    def __init__(self, *values): self.values=list(values or [draft()]);self.calls=[]
    def generate(self, business, errors):
        self.calls.append(copy.deepcopy(errors))
        value=self.values[min(len(self.calls)-1,len(self.values)-1)]
        if isinstance(value, Exception):raise value
        return copy.deepcopy(value)


class MockRuntime:
    def __init__(self,*replies):self.replies=iter(replies);self.calls=0
    def complete(self,*_):self.calls+=1;return next(self.replies)


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(storage,"DB_PATH",tmp_path/"builder.db")
    monkeypatch.setattr(storage,"DATA_DIR",tmp_path)
    storage.initialize_db()
    monkeypatch.setattr(app,"send_application_email",lambda *_:False)
    monkeypatch.setattr(app,"get_builder_provider",MockBuilder)
    return TestClient(app.app)


def generated():
    return AgentBuilder(MockBuilder()).generate(BusinessInput.model_validate(nova()))


def config():
    from agents.models import AgentConfig
    return AgentConfig.model_validate(generated()["config"])


def test_business_input_and_structured_schema(isolated):
    value=BusinessInput.model_validate(nova());assert value.services[1].duration_minutes==45
    schema=strict_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"])==set(schema["properties"])
    assert set(schema["properties"]["tools"]["items"]["enum"])=={'check_slots','create_booking','transfer_to_human'}
    assert 'booking' in schema["properties"]["scenarios"]["items"]["enum"]
    for sub in schema["$defs"].values(): assert sub["additionalProperties"] is False


@pytest.mark.parametrize("change", [lambda v:v.update(timezone="Mars/Nowhere"),lambda v:v.update(schedule={"0":[{"start":"20:00","end":"09:00"}]}),lambda v:v["services"][0].update(price=-1),lambda v:v.update(capabilities=["payments"]),lambda v:v["services"][0].update(duration_minutes=0)])
def test_invalid_business_input(isolated,change):
    v=nova();change(v);assert isolated.post('/api/builder/generate',json=v).status_code==422


@pytest.mark.parametrize("kind,value", [("person_name","Лёша"),("phone","+375 29 123-45-67"),("email","A@B.com"),("free_text","Аллергия"),("number","12.5"),("address","Минск 1"),("choice","A")])
def test_presets_are_server_owned(kind,value):
    from agents.fields import normalize
    f=user_field("test","Поле","Уточните значение.",kind,choices=["A","B"] if kind=='choice' else [])
    assert normalize(f,value)
    assert f.allowed_sources==['user'] and not f.tool_paths


@pytest.mark.parametrize("change", [lambda v:v.update(regex=".*"),lambda v:v.update(capabilities=["payments"]),lambda v:v.update(timezone="Mars/Nowhere"),lambda v:v["tools"].append("refund"),lambda v:v.update(scenarios=["execute_python"]),lambda v:v.update(fields=[{"label":"Код","question":"Ваш код?","type":"free_text","required":True,"choices":[],"tool_paths":{"x":["y"]}}]),lambda v:v.update(fields=[{"label":"Аллергия","question":"Есть аллергия?","type":"free_text","required":True,"choices":[]}]*2)])
def test_invalid_draft_never_saved_or_activated(isolated,change):
    v=draft();change(v);provider=MockBuilder(v);builder=AgentBuilder(provider)
    result=builder.generate(BusinessInput.model_validate(nova()))
    assert not result['validation']['valid'] and result['attempts']==2 and len(provider.calls)==2
    assert builder.repository.list()==[]
    with pytest.raises(ValueError):builder.save(result['candidate_id'],'anything')


def test_one_repair_only(isolated):
    bad=draft();bad['tools']=['unknown'];provider=MockBuilder(bad,draft());result=AgentBuilder(provider).generate(BusinessInput.model_validate(nova()))
    assert result['validation']['valid'] and len(provider.calls)==2 and provider.calls[1]
    assert AgentRepository().list()==[]


def test_provider_failure_keeps_input(isolated):
    provider=MockBuilder(RuntimeError("PRIVATE_KEY_AND_BODY"));result=AgentBuilder(provider).generate(BusinessInput.model_validate(nova()))
    assert result['validation']['errors'][0]['code']=='provider_failure' and result['attempts']==1
    stored=AgentRepository().candidate(result['candidate_id']);assert stored['business_input']['business_name']=='Nova Beauty'
    assert 'PRIVATE_KEY' not in json.dumps(result)


def test_nova_mapping_schedule_ids_invariant_preview(isolated):
    result=generated();assert result['validation']['valid'],result
    c=result['config'];assert c['business']['schedule']==nova()['schedule'] and c['business']['opening_hours']==''
    assert c['escalation']['explicit_human_request']=='immediate'
    assert c['escalation']['agent_initiated']['unsupported_scenario']=='allowed'
    assert result['preview']['services'][0]['name']=='Маникюр' and result['preview']['hours'][6].endswith('Выходной')
    assert all(re.fullmatch('[a-z][a-z0-9_]*',s['id']) for s in c['business']['knowledge']['services'])
    assert 'capabilities' not in BuilderDraft.model_fields


def test_stable_ids_casefold_deduplication(isolated):
    data=nova();data['employees'].append(' анна ');data['services'].append({**data['services'][0],'name':' маникюр '})
    services,employees,warnings=catalog(BusinessInput.model_validate(data))
    assert len(services)==2 and len(employees)==2 and len(warnings)==2
    assert stable_id('Маникюр')==stable_id(' маникюр ')
    assert services==catalog(BusinessInput.model_validate(data))[0]


def test_conflicting_duplicate_services(isolated):
    data=nova();data['services'].append({**data['services'][0],'name':'МАНИКЮР','price':99})
    result=AgentBuilder(MockBuilder()).generate(BusinessInput.model_validate(data));assert not result['validation']['valid']


def test_unsupported_refund_warning(isolated):
    data=nova();data['tasks'].append('Автоматически сделать возврат денег')
    result=AgentBuilder(MockBuilder()).generate(BusinessInput.model_validate(data))
    assert result['validation']['valid'] and any('возврат' in w['message'] for w in result['validation']['warnings'])
    assert not any('refund' in t['name'] for t in result['config']['tools'])


def test_platform_handoff_cannot_be_disabled(isolated):
    c=config();c.escalation.explicit_human_request='disabled'
    assert any(e['code']=='human_request_invariant' for e in validate_agent(c)['errors'])


def test_lifecycle_separate_review_persistence_activation(isolated):
    result=isolated.post('/api/builder/generate',json=nova()).json()
    assert result['validation']['valid']
    assert isolated.post('/api/builder/validate',json={'candidate_id':result['candidate_id']}).json()['valid']
    assert AgentRepository().list()==[]
    assert isolated.post('/api/agents',json={'candidate_id':result['candidate_id'],'review_token':'wrong'}).status_code==422
    saved=isolated.post('/api/agents',json={k:result[k] for k in ['candidate_id','review_token']}).json()
    assert saved['status']=='valid' and saved['source']=='builder'
    aid=saved['id'];assert isolated.post('/api/conversations',json={'agent_id':aid}).status_code==422
    assert AgentRepository().get(aid)['config']==result['config']
    assert isolated.post(f'/api/agents/{aid}/activate',json={}).json()['status']=='active'
    assert isolated.post('/api/conversations',json={'agent_id':aid}).status_code==200
    assert AgentRepository().get(aid)['status']=='active'
    assert len(isolated.get('/api/agents').json()['items'])==2
    assert isolated.post('/api/conversations').json()['agent_name']!=saved['name']


def test_tampered_invalid_persistence_refuses_activation(isolated):
    result=generated();builder=AgentBuilder(MockBuilder());saved=builder.save(result['candidate_id'],result['review_token'])
    bad=saved['config'];bad['tools'][0]['name']='unknown'
    with storage.connect() as db:db.execute('UPDATE agents SET config_json=? WHERE id=?',(json.dumps(bad),saved['id']))
    assert isolated.post(f"/api/agents/{saved['id']}/activate",json={}).status_code==422
    assert AgentRepository().get(saved['id'])['status']=='valid'


def test_unknown_agent_and_candidate(isolated):
    assert isolated.get('/api/agents/missing').status_code==404
    assert isolated.post('/api/conversations',json={'agent_id':'missing'}).status_code==404
    assert isolated.post('/api/builder/validate',json={'candidate_id':'missing'}).status_code==404


def test_real_runtime_generated_booking_and_display(isolated):
    c=config();state=new_interaction(c);service=BookingService(c.business)
    day=(datetime.now(ZoneInfo('Europe/Minsk'))+timedelta(days=1)).date().isoformat()
    sid=c.business.knowledge['services'][0]['id'];eid=c.business.knowledge['employees'][0]['id']
    def call(name,args):return ModelReply(tool_calls=[ToolCall(name,name,args)])
    provider=MockRuntime(call('check_slots',{'service':sid,'date':day,'preferred_time':'18:00'}),call('create_booking',{'service':sid,'datetime':day+'T18:30:00+03:00','employee':eid,'customer_name':'Лёша','phone':'+375291234567'}))
    runtime=create_runtime(c,provider);reply=runtime.turn(state,'Хочу завтра после шести на маникюр')
    assert any(s['service']==sid for s in state['tool_events'][0]['result']['slots'])
    reply=runtime.turn(state,'На 18:30. Меня зовут Лёша. Мой телефон +375291234567')
    assert reply['status']=='awaiting_confirmation',reply
    assert 'Маникюр' in reply['text'] and 'Анна' in reply['text'] and sid not in reply['text']
    reply=runtime.turn(state,'Да, подтверждаю');assert reply['status']=='completed'
    storage.save_interaction(state)
    assert storage.get_interaction(state['id'])['agent_id']==c.id
    assert next(f['value'] for f in storage.public_interaction(state)['display_fields'] if f['id']=='service')=='Маникюр'
    with storage.connect() as db:
        row=dict(db.execute('SELECT * FROM bookings').fetchone());assert row['service']==sid and row['employee']==eid


def test_generated_explicit_handoff_without_llm(isolated):
    c=config();state=new_interaction(c);provider=MockRuntime()
    reply=create_runtime(c,provider).turn(state,'Я не хочу разговаривать с ботом. Дайте человека.')
    assert reply['status']=='escalated' and provider.calls==0
    with storage.connect() as db:assert db.execute('SELECT agent_id FROM escalations').fetchone()[0]==c.id


def test_business_namespaces_do_not_share_calendar(isolated):
    data=BusinessInput.model_validate(nova());other=data.model_copy(deep=True);other.business_name='Other salon'
    assert catalog(data)[1][0]['id']!=catalog(other)[1][0]['id']


def test_no_builder_dependency_in_runtime():
    from pathlib import Path
    assert 'builder' not in Path('agents/runtime.py').read_text(encoding='utf-8').lower()


def test_provider_uses_strict_output_and_configurable_model(isolated,monkeypatch):
    from types import SimpleNamespace
    from providers.builder import GroqBuilderProvider
    import providers.builder as adapter
    received={}
    def create(**kwargs):
        received.update(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(draft())))])
    monkeypatch.setenv('BUILDER_MODEL','configured-model')
    monkeypatch.setattr(adapter,'groq_client',lambda:SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    assert GroqBuilderProvider().generate(BusinessInput.model_validate(nova()),[])==draft()
    assert received['model']=='configured-model' and received['response_format']['json_schema']['strict'] is True
    assert 'tools' not in received


def test_choice_metacharacters_are_literal():
    from agents.fields import normalize
    field=user_field('choice','Вариант','Выберите вариант.','choice',choices=['a.*','b'])
    assert normalize(field,'a.*')=='a.*'
    with pytest.raises(ValueError):normalize(field,'abcdef')


def test_extra_field_builder_mapping_and_evidence(isolated):
    from agents.fields import collect_user,verify_action
    value=draft();value['fields']=[{'label':'Аллергия','question':'Есть ли аллергия?','type':'free_text','required':True,'choices':[]}]
    result=AgentBuilder(MockBuilder(value)).generate(BusinessInput.model_validate(nova()))
    assert result['validation']['valid'],result
    from agents.models import AgentConfig
    c=AgentConfig.model_validate(result['config']);extra=c.fields[-1];assert extra.id.startswith('field_')
    state=new_interaction(c);state['transcript'].append({'role':'user','content':'Аллергия: латекс'})
    collect_user(state,c,'Аллергия: латекс',1)
    assert state['collected_fields'][extra.id]['value']=='латекс'
    assert state['collected_fields'][extra.id]['source']=='user'


@pytest.mark.parametrize('change',[lambda k:k['services'][1].update(id=k['services'][0]['id']),lambda k:k['services'][0].update(employees=['unknown']),lambda k:k['employees'][1].update(name=k['employees'][0]['name'])])
def test_generated_entity_contracts_validated(isolated,change):
    c=config();change(c.business.knowledge);assert not validate_agent(c)['valid']


def test_builder_logs_no_input_or_provider_secrets(isolated,caplog):
    import logging
    with caplog.at_level(logging.INFO,logger='callwise.builder'):
        result=AgentBuilder(MockBuilder(ValueError('private-secret'))).generate(BusinessInput.model_validate(nova()))
    assert 'builder_started' in caplog.text and 'builder_completed' in caplog.text
    assert 'private-secret' not in caplog.text and 'Nova Beauty' not in caplog.text


def test_save_repeated_preview_is_idempotent(isolated):
    result=generated();builder=AgentBuilder(MockBuilder())
    first=builder.save(result['candidate_id'],result['review_token'])
    second=builder.save(result['candidate_id'],result['review_token'])
    assert first['id']==second['id'] and len(builder.repository.list())==1


def test_rate_limit_clear_error_preserves_input_and_conversation(isolated,monkeypatch):
    from types import SimpleNamespace
    from openai import RateLimitError
    response_stub=SimpleNamespace(status_code=429,request=None,headers={})
    error=RateLimitError('private provider message',response=response_stub,body={})
    result=AgentBuilder(MockBuilder(error)).generate(BusinessInput.model_validate(nova()))
    assert 'Лимит' in result['validation']['errors'][0]['message']
    assert AgentRepository().candidate(result['candidate_id'])['business_input']['business_name']=='Nova Beauty'
    class QuotaProvider:
        def complete(self,*_):raise error
    monkeypatch.setattr(app,'get_provider',QuotaProvider)
    identifier=isolated.post('/api/conversations').json()['interaction_id']
    response=isolated.post('/api/chat',json={'interaction_id':identifier,'text':'Хочу маникюр'})
    assert response.status_code==429 and 'Лимит' in response.json()['detail']
    assert storage.get_interaction(identifier)['transcript'][-1]['content']=='Хочу маникюр'


def test_generated_stt_hint_is_bounded_and_has_display_names(isolated):
    from agents.prompts import build_transcription_prompt
    c=config();hint=build_transcription_prompt(c,'Какую услугу выбираете?')
    assert len(hint.encode('utf-8'))<=224
    assert 'Маникюр' in hint and 'Анна' in hint and 'Телефон' in hint
    assert 'service_' not in hint and 'business_' not in hint
    c.business.name='Очень длинное имя '*100
    assert len(build_transcription_prompt(c,'Длинный вопрос '*1000).encode('utf-8'))<=224
