"""Bounded harmless provider probes, deliberately NOT a readiness benchmark."""
from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict
from providers.base import ConversationMessage, ToolSpec
from providers.errors import ProviderError, public_error
from providers.capabilities import validate_models
from evaluation.providers import Budget, StructuredGroq, live_agent_provider
from evaluation.config import model_names


class ProbeValue(BaseModel):
    model_config=ConfigDict(extra='forbid')
    value: str


def provider_preflight(budget=None, models=None, agent_factory=None, structured_factory=None, include_simulator=False):
    models=dict(models or model_names())
    local=Budget(6,parent=budget)
    output={'provider':'Groq','models':{},'timestamp':datetime.now(timezone.utc).isoformat(),
        'purpose':'provider_preflight_not_readiness','fallback':False,'maximum_requests':6,
        'request_count':0,'retry_count':0,'status':'FAIL'}
    probes=('agent_text','agent_tools','tool_continuation','structured_outputs')
    output['probes']={name:{'status':'NOT_TESTED'} for name in probes}
    agent=None; current='agent_text'; before=(0,0)
    def finish(name,passed,model,requests_before,retries_before,operation='preflight'):
        meta=agent.metadata() if callable(getattr(agent,'metadata',None)) else {}
        output['probes'][name]={'status':'PASS' if passed else 'FAIL','provider':'Groq','model':model,
            'operation':operation,'request_count':local.requests-requests_before,
            'retry_count':meta.get('retry_count',0)-retries_before}
        if not passed: raise ProviderError(model,'preflight','tool_generation_failed' if name=='agent_tools' else 'unknown')
    def counters():
        return local.requests,(agent.metadata().get('retry_count',0) if callable(getattr(agent,'metadata',None)) else 0)
    try:
        output['capabilities']=validate_models(models,include_simulator)
        output['models']={r:models[r] for r in output['capabilities']}
        agent=(agent_factory or live_agent_provider)(local,models['agent'])
        before=counters()
        reply=agent.complete([ConversationMessage('user','Reply with the word READY. This is a synthetic connectivity test.')],[])
        finish(current,bool(reply.text.strip()) and not reply.tool_calls,models['agent'],*before)
        current='agent_tools'; before=counters()
        tool=ToolSpec('lookup_test_value','Look up a harmless synthetic item value.',
            {'type':'object','properties':{'item_id':{'type':'string','enum':['probe_item']}},'required':['item_id'],'additionalProperties':False})
        messages=[ConversationMessage('system','For item values always use lookup_test_value. After the result, state its value, not reasoning.'),
            ConversationMessage('user','Use lookup_test_value for item_id probe_item and tell me its value.')]
        reply=agent.complete(messages,[tool])
        valid=(len(reply.tool_calls)==1 and reply.tool_calls[0].name==tool.name and reply.tool_calls[0].arguments=={'item_id':'probe_item'})
        finish(current,valid,models['agent'],*before)
        current='tool_continuation'; before=counters()
        call=reply.tool_calls[0]
        # Local execution based on the validated arguments, not a fabricated model answer.
        value={'probe_item':'CALLWISE_SYNTHETIC_734'}[call.arguments['item_id']]
        messages += [ConversationMessage('assistant',reply.text,reply.tool_calls),
                     ConversationMessage('tool',call_id=call.id,result={'value':value})]
        reply=agent.complete(messages,[])
        finish(current,value in reply.text and not reply.tool_calls,models['agent'],*before)
        current='structured_outputs'; before=counters()
        checked={}
        for role in ['generator','judge']+(['simulator'] if include_simulator else []):
            model=models[role]
            if model not in checked:
                adapter=(structured_factory(local,role,model) if structured_factory else StructuredGroq(role,local,model_id=model))
                answer=adapter.request('Return the supplied synthetic value in the strict JSON schema.',{'value':'PREFLIGHT_OK'},ProbeValue)
                checked[model]=answer=={'value':'PREFLIGHT_OK'}
            if not checked[model]: raise ProviderError(model,'preflight','structured_output_failed')
        finish(current,all(checked.values()),models['judge'],*before)
        output['probes'][current]['checked_models']=sorted(checked)
        output['status']='PASS'
    except Exception as exc:
        meta=agent.metadata() if callable(getattr(agent,'metadata',None)) else {}
        safe=public_error(exc,'preflight')
        output['probes'][current].update(status='FAIL',error=safe,provider='Groq',model=safe.get('model',models['agent']),
            operation='preflight',request_count=local.requests-before[0],retry_count=meta.get('retry_count',0)-before[1])
        output['error']=public_error(exc,'preflight')
        # All remaining probes explicitly not tested; no retry loop or mock substitution.
    finally:
        output['request_count']=local.requests
        meta=agent.metadata() if callable(getattr(agent,'metadata',None)) else {}
        output['retry_count']=meta.get('retry_count',0)
        output['retry_diagnostics']=meta.get('retry_diagnostics',[])
        if callable(getattr(agent,'close',None)): agent.close()
    return output
