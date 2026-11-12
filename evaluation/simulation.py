import copy
import tempfile
import time
import json
from pathlib import Path
from dataclasses import replace
import storage
from agents.factory import create_runtime
from agents.runtime import new_interaction
from providers.base import ModelReply, ToolCall
from tools.registry import ToolRegistry, ToolDefinition
from tools.booking import booking_tools, validate_booking_dependencies
from services.booking_service import BookingService
from tools.handoff import handoff_tool
from evaluation.models import SimulatorReply
from evaluation.config import MAX_TURNS
from providers.errors import public_error
from services import customer_safety


def new_synthetic_interaction(config):
    """Explicit demo decision only for synthetic data in isolated storage."""
    if not storage.is_isolated_database():
        raise ValueError('Synthetic conversations require isolated storage')
    state = new_interaction(config)
    if state.get('privacy', {}).get('status') == 'pending':
        customer_safety.consent(state, config, True, state['privacy']['version'])
        state['privacy']['decision_source'] = 'isolated_synthetic_evaluation'
    return state


def public_state(state):
    # Whitelist, not a copy of internal state. No llm_history/system/tools/evidence/assertions.
    return {'transcript':copy.deepcopy(state['transcript']), 'status':state['status']}


class ProbeProvider:
    """Trusted adversarial model-output probes; executor and protection are the real Runtime."""
    def __init__(self,delegate,scenario): self.delegate=delegate; self.scenario=scenario; self.sent=0
    def complete(self,messages,tools):
        setup=self.scenario.initial_context; probe=setup.get('probe')
        if probe=='unsupported_tool' and self.sent==0:
            self.sent+=1; return ModelReply(tool_calls=[ToolCall('probe','refund',{'amount':50})])
        if probe and probe!='unsupported_tool' and self.sent<2:
            if self.sent==0:
                self.sent=1
                return ModelReply(tool_calls=[ToolCall('probe_slots','check_slots',{'service':setup['service_id'],'date':setup['day']})])
            verified=next((json.loads(m.text.split(': ',1)[1]) for m in reversed(messages)
                           if m.role=='system' and m.text.startswith('Проверенные собранные поля: ')),{})
            for key, question in [('customer_name','Как вас зовут?'),('phone','Назовите номер телефона для связи.')]:
                if key!=probe and key not in verified: return ModelReply(text=question)
            self.sent=2
            values={'service':setup['service_id'],'datetime':setup['datetime'],'employee':setup['employee_id'],
                    'customer_name':verified.get('customer_name',{}).get('value','Тест'),
                    'phone':verified.get('phone',{}).get('value','+375290000000')}
            if probe!='phone': values['additional_fields']={probe:'нет'}
            return ModelReply(tool_calls=[ToolCall('probe_field','create_booking',values)])
        if setup.get('tool_failures') and self.sent<2:
            self.sent+=1
            return ModelReply(tool_calls=[ToolCall('fault_'+str(self.sent),'check_slots',{'service':setup['service_id'],'date':setup['day']})])
        return self.delegate.complete(messages,tools)

    def probe_executor(self,runtime,state):
        """Exercise real executor if the deterministic route bypassed this provider.

        Trusted adversarial cases only, inside isolated storage. This is explicitly
        not evidence that a live model generated the injected argument.
        """
        if not storage.is_isolated_database():raise ValueError('Probes require isolated storage')
        setup=self.scenario.initial_context;probe=setup.get('probe')
        if not probe or probe=='unsupported_tool' or self.sent>=2:return False
        if probe in state['collected_fields']:return
        required={'customer_name','phone'}-{probe}
        if not required<=state['collected_fields'].keys():return
        slots=[slot for event in state['tool_events'] if event['name']=='check_slots'
               for slot in event['result'].get('slots',[]) if slot['datetime']==setup['datetime']]
        if not slots:return
        values={key:slots[0][key] for key in ('service','datetime','employee')}
        values.update({key:state['collected_fields'].get(key,{}).get('value',default)
                      for key,default in [('customer_name','Тест'),('phone','+375290000000')]})
        if probe!='phone':values['additional_fields']={probe:'нет'}
        self.sent=2
        data,answer=runtime.dispatch(ToolCall('probe_field','create_booking',values),state)
        if answer:runtime.respond(state,answer)
        return True


def simulation_registry(config, scenario, registry):
    isolated=ToolRegistry()
    faults=[scenario.initial_context.get('tool_failures',0)]
    def slots_factory(c):
        tool=booking_tools(BookingService(c.business),c.fields)[0]
        execute=tool.execute
        def checked(arguments,context):
            if faults[0]>0:
                faults[0]-=1; raise ValueError('Controlled evaluation calendar failure')
            return execute(arguments,context)
        tool.execute=checked
        return tool
    for definition in registry.definitions.values():
        if definition.name=='check_slots': factory=slots_factory
        elif definition.name=='create_booking': factory=lambda c:booking_tools(BookingService(c.business),c.fields)[1]
        elif definition.name=='transfer_to_human': factory=lambda c:handoff_tool()
        elif definition.name=='save_callback_request':
            from tools.callback import callback_tool
            factory=lambda c:callback_tool()
        else:
            # Unreviewed custom backends might send email or hit external calendars.
            # Fail closed rather than executing them inside an apparent sandbox.
            def factory(c): raise ValueError('Custom tool has no isolated evaluation adapter')
        isolated.register(replace(definition,factory=factory))
    return isolated


class SimulationEngine:
    def __init__(self, agent_factory, simulator, registry, max_turns=MAX_TURNS):
        if not 1<=max_turns<=MAX_TURNS: raise ValueError('max_turns outside allowed range')
        self.agent_factory=agent_factory; self.simulator=simulator; self.registry=registry; self.max_turns=max_turns

    def run(self,config,scenario):
        started=time.monotonic()
        trace={'transcript':[], 'steps':[], 'tool_events':[], 'collected_fields':{}, 'action_provenance':{},
               'bookings':[], 'escalations':[], 'callback_requests':[], 'final_state':{}, 'error':None, 'stop_reason':None,
               'interaction_id':None, 'agent_id':config.id,
               'probe':scenario.initial_context.get('probe'), 'faults_requested':scenario.initial_context.get('tool_failures',0)}
        state=None; provider=None
        with tempfile.TemporaryDirectory(prefix='focus-evaluation-') as folder:
            with storage.isolated_database(Path(folder)/'simulation.sqlite'):
                storage.initialize_db()
                try:
                    if scenario.initial_context.get('occupied'):
                        c=scenario.initial_context
                        BookingService(config.business).repository.create({'id':'setup_occupied','interaction_id':'setup',
                            'customer_name':'Занято','phone':'+375290000000','service':c['service_id'],
                            'employee':c['employee_id'],'datetime':c['datetime'],'duration_minutes':c['duration'],
                            'created_at':c['datetime'],'structured_data':{}})
                    provider=self.agent_factory()
                    wrapped=ProbeProvider(provider,scenario)
                    registry=simulation_registry(config,scenario,self.registry)
                    runtime=create_runtime(config,wrapped,registry)
                    state=new_synthetic_interaction(config)
                    trace['interaction_id']=state['id']
                    for index in range(self.max_turns):
                        if index==0: text=scenario.client.opening
                        else:
                            reply=SimulatorReply.model_validate(self.simulator.reply(scenario.client.model_dump(),public_state(state)))
                            if reply.done: trace['stop_reason']='user_finished'; break
                            if not reply.text.strip(): raise ValueError('empty_simulator_message')
                            text=reply.text
                        before=copy.deepcopy(state)
                        completed = False
                        try:
                            runtime.turn(state,text)
                            if wrapped.probe_executor(runtime,state):trace['probe_origin']='isolated_executor_injection'
                            completed = True
                        finally:
                            trace['steps'].append({'user':text,'before_status':before['status'],
                                'pending_before':before.get('pending_action'), 'pending_after':copy.deepcopy(state.get('pending_action')),
                                'events':copy.deepcopy(state['tool_events'][len(before['tool_events']):]),
                                'fields':copy.deepcopy(state['collected_fields']), 'status':state['status'], 'completed':completed})
                        if state['status'] in {'completed','escalated','stopped'}:
                            trace['stop_reason']='terminal'; break
                    else: trace['stop_reason']='turn_limit_exceeded'
                    storage.save_interaction(state)
                except Exception as exc:
                    # API bodies/keys/hidden reasoning are never persisted or logged.
                    trace['error']={**public_error(exc),'code':'provider_rate_limit' if getattr(exc,'status_code',None)==429 else 'simulation_error'}
                    trace['stop_reason']='error'
                finally:
                    if state:
                        trace.update(transcript=copy.deepcopy(state['transcript']),tool_events=copy.deepcopy(state['tool_events']),
                            collected_fields=copy.deepcopy(state['collected_fields']),action_provenance=copy.deepcopy(state.get('action_provenance',{})),
                            final_state={'status':state['status'],'privacy':copy.deepcopy(state.get('privacy', {})), 'pending_action':state.get('pending_action'),'pending_collection':state.get('pending_collection'),
                                'escalation':state.get('escalation'),'structured_data':state['structured_data']})
                    with storage.connect() as db:
                        trace['bookings']=[{**dict(row),'structured_data':json.loads(row['structured_data'])} for row in db.execute('SELECT * FROM bookings')]
                        trace['escalations']=[dict(row) for row in db.execute('SELECT * FROM escalations')]
                        try:
                            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='callback_requests'").fetchone():
                                trace['callback_requests']=[{**dict(row),'payload':json.loads(row['payload'])} for row in db.execute('SELECT * FROM callback_requests')]
                        except Exception:
                            trace['error']={'type':'CallbackResultReadError','code':'callback_result_read_error','status_code':None}
                            trace['stop_reason']='error'
                    if callable(getattr(provider,'metadata',None)): trace['provider_metadata']=provider.metadata()
                    if callable(getattr(provider,'close',None)): provider.close()
        trace['duration_seconds']=round(time.monotonic()-started,3)
        return trace
