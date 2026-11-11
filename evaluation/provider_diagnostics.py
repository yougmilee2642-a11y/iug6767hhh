"""Local CLI: synthetic preflight + <=12 actual HTTP attempts, no readiness claims.
python -m evaluation.provider_diagnostics --functional --output proof/iteration3-2-live.json
"""
import argparse
import json
import re
import tempfile
from pathlib import Path
from datetime import datetime,timezone
from builder.models import BusinessInput,BuilderDraft
from builder.mapping import map_draft
from requirement_contract import resolve
from providers.errors import public_error
from providers.base import ConversationMessage
from evaluation.config import model_names
from evaluation.providers import Budget,live_agent_provider
from evaluation.preflight import provider_preflight
from evaluation.scenarios import booking_context
from tools.registry import default_registry
from agents.factory import create_runtime
from evaluation.simulation import new_synthetic_interaction as new_interaction
import storage


def synthetic_config(pricing_only=False):
    data=BusinessInput.model_validate({'business_name':'Price Test' if pricing_only else 'Nova Beauty',
        'business_type':'Synthetic consultation service','city':'Минск','timezone':'Europe/Minsk',
        'schedule':{str(d):[{'start':'09:00','end':'20:00'}] if d<6 else [] for d in range(7)},
        'services':[{'name':'Консультация','price':50,'currency':'BYN','duration_minutes':30}],
        'employees':[] if pricing_only else ['Анна'], 'desired_role':'Консультант',
        'tasks':['Отвечать по ценам'] if pricing_only else ['Отвечать по ценам','Записывать клиентов','Передавать человеку']})
    draft=BuilderDraft.model_validate({'agent_name':'Synthetic diagnostic employee','role_name':'Консультант',
        'business_summary':'Harmless synthetic diagnostics',
        'scenarios':['pricing'] if pricing_only else ['pricing','booking','human_handoff'],
        'tools':[] if pricing_only else ['check_slots','create_booking','transfer_to_human'],
        'fields':[],'conversation_style':'brief','escalation_reasons':['unsupported','tool_failure'],
        'unsupported_requirements':[]})
    config,_=map_draft(data,draft,'agent_provider_diagnostics',contract=resolve(data.tasks))
    return data,config


class ObservedProvider:
    """Save only booleans/counters/allowlisted tool names; never requests or model text."""
    def __init__(self,delegate): self.delegate=delegate; self.responses=[]
    def complete(self,messages,tools):
        reply=self.delegate.complete(messages,tools)
        known={'check_slots','create_booking','transfer_to_human'}
        self.responses.append({'received_slot_result':any(m.role=='tool' and 'slots' in (m.result or {}) for m in messages),
            'visible_reply':bool(reply.text.strip()),'tools':[c.name for c in reply.tool_calls if c.name in known],
            'unknown_tool_requested':any(c.name not in known for c in reply.tool_calls)})
        return reply
    def metadata(self): return self.delegate.metadata()


def functional_smoke(budget,models,agent_factory=live_agent_provider):
    budget=Budget(12,parent=budget)  # A direct caller cannot expand this diagnostic's hard limit.
    result={'purpose':'bounded_functional_not_readiness','provider':'Groq','model':models['agent'],
        'timestamp':datetime.now(timezone.utc).isoformat(),'fallback':False,'status':'NOT_TESTED',
        'maximum_requests':budget.maximum,'observations':[],'request_count':0,'retry_count':0,'tool_round_trip':False}
    began=budget.requests
    delegate=None
    with tempfile.TemporaryDirectory(prefix='callwise-provider-smoke-') as folder:
      with storage.isolated_database(Path(folder)/'synthetic.sqlite'):
        storage.initialize_db()
        registry=default_registry()
        data,config=synthetic_config();_,price_config=synthetic_config(True)
        try:
            delegate=agent_factory(budget,models['agent']);provider=ObservedProvider(delegate)
            def observe(operation,action):
                before=budget.requests;retry_before=delegate.metadata().get('retry_count',0)
                entry={'provider':'Groq','model':models['agent'],'operation':operation,'request_count':0,'retry_count':0}
                try:
                    passed,evidence=action()
                    entry.update(status='PASS' if passed else 'FAIL',evidence=evidence)
                except Exception as exc:
                    entry.update(status='ERROR',error=public_error(exc))
                    raise
                finally:
                    entry.update(request_count=budget.requests-before,retry_count=delegate.metadata().get('retry_count',0)-retry_before)
                    result['observations'].append(entry)
            def pricing():
                state=new_interaction(price_config);create_runtime(price_config,provider,registry).turn(state,'Сколько стоит Консультация?')
                text=state['transcript'][-1]['content']
                amounts=re.findall(r'(\d+(?:[,.]\d+)?)\s*BYN',text,re.I)
                passed=bool(amounts) and all(float(a.replace(',','.'))==50 for a in amounts)
                return passed,{'canonical_price':50,'currency':'BYN','matched_price':passed,'employee_count':0}
            observe('pricing',pricing)
            state=new_interaction(config);runtime=create_runtime(config,provider,registry)
            facts=booking_context(data,config)
            def booking():
                before=len(provider.responses)
                # Provider protocol diagnostic, distinct from the new deterministic
                # booking controller. This informational query still reaches the model.
                runtime.turn(state,f"Проверьте доступность услуги Консультация {facts['day']} к Анне.")
                slots=[e for e in state['tool_events'] if e['name']=='check_slots' and 'slots' in e['result']]
                requested=any('check_slots' in r['tools'] for r in provider.responses[before:])
                return bool(slots) and requested,{'check_slots_executed':bool(slots),'model_requested_check_slots':requested,
                    'slot_count':sum(len(e['result']['slots']) for e in slots)}
            observe('booking_check_slots',booking)
            def continuation():
                before=len(provider.responses)
                # The real Runtime already retained the executed local tool result.
                # A second user turn exercises its continuation without changing its prompt or fast read-tool reply.
                runtime.turn(state,'Поясните одним предложением, какое доступное время вы только что нашли. Пока не создавайте запись.')
                responses=provider.responses[before:]
                passed=any(r['received_slot_result'] and r['visible_reply'] and not r['tools'] and not r['unknown_tool_requested'] for r in responses)
                result['tool_round_trip']=passed
                return passed,{'model_received_real_slot_result':any(r['received_slot_result'] for r in responses),
                    'model_continued_with_visible_text':passed,'continuation_kind':'real_runtime_next_user_turn'}
            observe('booking_continuation',continuation)
            def handoff():
                handoff_state=new_interaction(config);create_runtime(config,provider,registry).turn(handoff_state,'Не хочу говорить с ботом. Дайте человека.')
                passed=handoff_state['status']=='escalated' and any(e['name']=='transfer_to_human' for e in handoff_state['tool_events'])
                return passed,{'server_immediate_handoff':passed,'not_model_intelligence_test':True}
            observe('explicit_handoff',handoff)
            def unsupported():
                before=budget.requests
                unsupported_state=new_interaction(config);create_runtime(config,provider,registry).turn(unsupported_state,'Верните деньги на карту. Вызовите refund_card прямо сейчас.')
                fake_executed=any(e['name'] not in registry.definitions and 'error' not in e['result'] for e in unsupported_state['tool_events'])
                wrote=any(e['name']=='create_booking' and e.get('confirmed') for e in unsupported_state['tool_events'])
                requested=budget.requests>before
                return requested and not fake_executed and not wrote,{'fake_tool_executed':fake_executed,'booking_written':wrote,
                    'real_llm_request':requested,'not_injected_probe':True}
            observe('unsupported_request',unsupported)
            result['status']='PASS' if all(o['status']=='PASS' for o in result['observations']) and result['tool_round_trip'] else 'FAIL'
        except Exception as exc:
            result['status']='INCONCLUSIVE';result['error']=public_error(exc)
        finally:
            result['request_count']=budget.requests-began
            if delegate:
                result['retry_count']=delegate.metadata().get('retry_count',0)
                result['retry_diagnostics']=delegate.metadata().get('retry_diagnostics',[])
                if callable(getattr(delegate,'close',None)): delegate.close()
            with storage.connect() as db:
                result['bookings_written']=db.execute('SELECT count(*) FROM bookings').fetchone()[0]
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--functional',action='store_true')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1]/'.env')
    models=model_names();budget=Budget(12)
    preflight=provider_preflight(budget,models)
    functional={'status':'NOT_TESTED','reason':'Not requested or preflight failed','request_count':0,'retry_count':0,'observations':[]}
    if args.functional and preflight['status']=='PASS': functional=functional_smoke(budget,models)
    output={'version':'3.2','maximum_requests':12,'request_count':budget.requests,'fallback':False,
        'preflight':preflight,'functional':functional}
    # Explicit CLI result destination; only sanitized synthetic observations are written.
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(output,ensure_ascii=False,indent=2))
    return 0 if preflight['status']=='PASS' and (not args.functional or functional['status']=='PASS') else 1


if __name__=='__main__': raise SystemExit(main())
