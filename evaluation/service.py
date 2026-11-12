import logging
import threading
import uuid
from agents.models import AgentConfig
from builder.models import BusinessInput
from services.agent_repository import AgentRepository
from tools.registry import default_registry
from evaluation.config import GENERATOR_VERSION, MAX_REQUESTS, model_names
from evaluation.repository import EvaluationRepository, digest, now
from evaluation.requirements import RequirementAnalyzer
from evaluation.scenarios import ScenarioGenerator, trusted_scenarios
from evaluation.simulation import SimulationEngine
from evaluation.evaluator import EvaluationEngine
from evaluation.readiness import readiness
from evaluation.providers import Budget, GroqScenarioGenerator, GroqJudge, ScriptedUserSimulator, GroqUserSimulator, live_agent_provider
from requirement_contract import RequirementContract, resolve
from evaluation.plan import build_plan
from evaluation.preflight import provider_preflight
from providers.errors import ProviderError, public_error
import os

logger=logging.getLogger('focus.evaluation')
_job_lock=threading.Lock()
_active_job=None
PROCESS_TOKEN=str(uuid.uuid4())


def default_components():
    from providers.local_settings import uses_local_ai
    if uses_local_ai():
        from evaluation.local import local_components
        return local_components()
    budget=Budget()
    models=model_names()
    simulator=GroqUserSimulator(budget,models['simulator']) if os.getenv('SIMULATOR_PROVIDER','scripted')=='groq' else ScriptedUserSimulator()
    return {'agent_factory':lambda:live_agent_provider(budget,models['agent']),'simulator':simulator,
            'generator':GroqScenarioGenerator(budget,models['generator']),'judge':GroqJudge(budget,models['judge']),'budget':budget,
            'preflight':lambda:provider_preflight(budget,models,include_simulator=isinstance(simulator,GroqUserSimulator)),
            'provider_info':{'provider':'Groq','models':models,'fallback':False,'simulator':type(simulator).__name__,'judge':'GroqJudge'}}


class EvaluationService:
    def __init__(self,repository=None,components_factory=None,registry=None):
        self.repository=repository or EvaluationRepository()
        self.components_factory=components_factory or default_components
        self.registry=registry or default_registry()
    def prepare(self,agent_id,count=20,seed=0,mode='CORE'):
        from evaluation.config import MIN_SCENARIOS,MAX_SCENARIOS
        from builder.models import BusinessInput
        if not MIN_SCENARIOS<=count<=MAX_SCENARIOS: raise ValueError('Число сценариев: 12–40')
        if mode not in {'CORE','STANDARD'}: raise ValueError('DEEP ещё не реализован. Выберите CORE или STANDARD.')
        agent=AgentRepository().get(agent_id)
        if not agent: raise LookupError('Агент не найден')
        candidate=AgentRepository().candidate(agent['candidate_id']) if agent.get('candidate_id') else None
        config=AgentConfig.model_validate(agent['config'])
        quick_profile=config.business.knowledge.get('track1_profile') if agent.get('source')=='track1' and candidate and candidate.get('kind')=='track1_quick' else None
        if quick_profile in {'secretary','support'}:
            if agent.get('source') != 'track1' or not candidate or candidate.get('kind') != 'track1_quick' or not candidate.get('input'):
                raise ValueError('Не найдена подтверждённая версия короткого мастера. Сохраните помощника заново.')
            from evaluation.quick import quick_requirements, quick_plan, QUICK_SUITE_VERSION
            from services.track1_service import QuickInput
            quick_input=QuickInput.model_validate(candidate['input']).model_dump()
            if digest(candidate.get('config')) != digest(config.model_dump()):
                raise ValueError('Конфигурация отличается от подтверждённого кандидата. Сохраните настройки через мастер.')
            business=config.business  # Preserve absent city/hours; do not invent Builder input.
            requirements=quick_requirements(config)
            plan=quick_plan(config,count,seed,mode)
            contract={'source':'quick_profile','confirmed':True,'profile':quick_profile,'version':QUICK_SUITE_VERSION}
            business_hash=digest(quick_input)
            quick_input_hash=business_hash
        else:
            if not candidate or not candidate.get('business_input'):
                raise ValueError('У legacy демо нет исходного BusinessInput. Создайте агента через Builder.')
            business=BusinessInput.model_validate(candidate['business_input'])
            if not candidate.get('requirement_contract'):
                candidate['requirement_contract']=resolve(business.tasks,'legacy_inferred').model_dump()
                AgentRepository().save_candidate(candidate)
            contract=RequirementContract.model_validate(candidate['requirement_contract'])
            if contract.raw_tasks != business.tasks:
                raise ValueError('Задачи изменены после review. Обновите договор в Builder, evaluation не переинтерпретирует текст.')
            requirements=RequirementAnalyzer(self.registry).analyze(business,config,contract)
            plan=build_plan(business,config,requirements,count,seed,mode)
            quick_input_hash=None
            business_hash=digest(business.model_dump())
        run={'id':str(uuid.uuid4()),'agent_id':agent_id,'status':'pending','config_snapshot':config.model_dump(),
            'business_snapshot':business.model_dump(),'config_hash':digest(config.model_dump()),'business_hash':business_hash,
            'generator_version':GENERATOR_VERSION,'seed':seed,'count':count,'started_at':now(),'completed_at':None,
            'requirements':[r.model_dump() for r in requirements],'readiness':None,'progress':0,'provider_info':{},'errors':[],'requests':0}
        run['infrastructure_errors']=[]
        run.update(mode=mode,requirement_contract=contract if isinstance(contract,dict) else contract.model_dump(),contract_hash=digest(contract if isinstance(contract,dict) else contract.model_dump()),
            plan=plan,generator_status='NOT_REQUESTED' if mode=='CORE' or quick_profile else 'pending',
            warnings=(['Legacy требования выведены однократно; подтвердите их в Builder перед использованием.'] if getattr(contract,'source',None)=='legacy_inferred' else (['Короткий мастер: проверка ограничена подтверждёнными знаниями и действиями роли; услуги, расписание и сотрудники не предполагаются.'] if quick_profile else [])))
        if quick_profile:
            run.update(evaluation_profile='quick_role',quick_profile=quick_profile,quick_input_hash=quick_input_hash)
        run['process_token']=PROCESS_TOKEN
        self.repository.save_run(run)
        return run
    def execute(self,run):
        from evaluation.models import Requirement, EvaluationScenario
        config=AgentConfig.model_validate(run['config_snapshot'])
        business=(config.business if run.get('evaluation_profile')=='quick_role' else BusinessInput.model_validate(run['business_snapshot']))
        requirements=[Requirement.model_validate(r) for r in run['requirements']]
        results=[]; components={}
        run['status']='running'; self.repository.save_run(run)
        logger.info('evaluation_started run=%s',run['id'])
        # The mandatory suite exists even if the optional language generator is unavailable.
        scenarios=[EvaluationScenario.model_validate(s) for s in run['plan']['scenarios']]
        self.repository.save_scenarios(run['id'],scenarios)
        try:
            components=self.components_factory(); run['provider_info']=components.get('provider_info',{})
            if components.get('preflight'):
                run['provider_health']=components['preflight']()
                self.repository.save_run(run)
                if run['provider_health']['status']!='PASS':
                    safe=run['provider_health'].get('error',{})
                    error=ProviderError(safe.get('model',run['provider_info'].get('models',{}).get('agent')),'preflight',
                        safe.get('category','unknown'),safe.get('status_code'),False,safe.get('diagnostics'))
                    error.request_count=run['provider_health']['request_count']
                    error.retry_count=run['provider_health']['retry_count']
                    raise error
            else:
                run['provider_health']={'status':'NOT_REQUIRED','purpose':'local_deterministic_not_live',
                    'provider':run['provider_info'].get('provider','local'),'probes':{}}
            simulator=ScriptedUserSimulator() if run['mode']=='CORE' else components['simulator']
            run['provider_info']['simulator']=type(simulator).__name__
            engine=SimulationEngine(components['agent_factory'],simulator,self.registry)
            evaluator=EvaluationEngine(self.registry,components.get('judge'),quality_preview=components.get('provider_info',{}).get('quality_independent') is False)
            interrupted=None
            def execute_cases(cases):
              nonlocal interrupted
              for scenario in cases:
                if interrupted:
                    trace={'tool_events':[],'steps':[],'bookings':[],'escalations':[],'transcript':[],
                        'collected_fields':{},'action_provenance':{},'final_state':{},'duration_seconds':0,
                        'stop_reason':'not_run','error':interrupted}
                else: trace=engine.run(config,scenario)
                result=evaluator.evaluate(config,scenario,trace)
                results.append(result); self.repository.save_result(run['id'],result)
                error=result.get('error')
                if error and error.get('role')=='judge' and error.get('status_code')==429:
                    evaluator.judge=None
                    run['errors'].append({'role':'judge','type':error['type'],'status_code':429,'message':'Judge 429: качество последующих сценариев не проверено. Safety-проверки продолжаются.'})
                elif error and error.get('role')!='judge' and (error.get('status_code')==429 or error.get('type')=='RuntimeError'):
                    interrupted=error
                    if not run['errors']:
                        run['errors']=[{'role':'agent','type':error['type'],'status_code':error.get('status_code'),
                            'message':'Лимит API (429): проверка остановлена. Остальные сценарии не запускались.' if error.get('status_code')==429
                            else 'Проверка остановлена: ошибка провайдера или исчерпан бюджет запросов.'}]
                run['progress']=len(results); run['requests']=getattr(components.get('budget'),'requests',0)
                self.repository.save_run(run)
            execute_cases(scenarios)
            if run['mode']=='STANDARD' and run['plan']['optional_variants'] and not interrupted and run.get('evaluation_profile')!='quick_role':
                try:
                    variants=ScenarioGenerator(components.get('generator')).generate(business,config,requirements,12+run['plan']['optional_variants'],run['seed'])[12:]
                    if not components.get('generator'): raise ValueError('generator_not_configured')
                    scenarios += variants
                    self.repository.save_scenarios(run['id'],scenarios)
                    run['generator_status']='completed'
                    execute_cases(variants)
                except Exception as exc:
                    run['generator_status']='failed'
                    run['errors'].append({**public_error(exc,'generator'),'message':'Необязательные языковые варианты недоступны; trusted core выполнен отдельно.'})
            elif run['mode']=='STANDARD':
                run['generator_status']='not_run' if interrupted else 'NOT_REQUESTED'
            run['readiness']=readiness(requirements,results,run['plan'])
            if run['provider_info'].get('quality_independent') is False:
                run['readiness']['quality_independent']=False
                run['warnings'].append('Текст оценивает та же локальная модель. Это предварительная оценка; проверьте ответы вручную.')
                if run['readiness']['status']=='READY':
                    run['readiness'].update(status='LIMITED',recommendation='Действия и сценарии прошли, но качество текста оценено той же моделью. Нужна ручная проверка ответов.')
            if not contract_confirmed(run) and run['readiness']['status']=='READY':
                run['readiness']['status']='LIMITED'
                run['readiness']['recommendation']='Требования legacy агента выведены однократно, но ещё не подтверждены пользователем.'
            run['status']='partial' if run['errors'] or any(r['status']=='ERROR' for r in results) else 'completed'
        except Exception as exc:
            run['status']='failed'
            run['errors']=[{**public_error(exc,'preflight' if run.get('provider_health',{}).get('status')=='FAIL' else 'agent'),
                            'message':'Лимит провайдера исчерпан.' if getattr(exc,'status_code',None)==429 else 'Проверка не завершена: ошибка генерации или провайдера.'}]
            existing_ids={r['scenario_id'] for r in results}
            for scenario in scenarios:
                if scenario.id in existing_ids: continue
                trace={'tool_events':[],'steps':[],'bookings':[],'escalations':[],'transcript':[],
                       'collected_fields':{},'action_provenance':{},'final_state':{},'duration_seconds':0,
                       'stop_reason':'not_run','error':{**public_error(exc),'code':'evaluation_interrupted'}}
                result=EvaluationEngine(self.registry).evaluate(config,scenario,trace)
                results.append(result); self.repository.save_result(run['id'],result)
            run['progress']=len(results)
            run['readiness']=readiness(requirements,results,run['plan'])
            logger.warning('evaluation_failed run=%s type=%s',run['id'],type(exc).__name__)
        finally:
            run['infrastructure_errors']=list(run['errors'])
            for result in results:
                error=result.get('error')
                if not error: continue
                role=error.get('role','agent')
                if not any(e.get('role')==role and e.get('type')==error['type'] and e.get('status_code')==error.get('status_code') for e in run['infrastructure_errors']):
                    run['infrastructure_errors'].append({**error,'role':role,'message':'Проверка не завершена: '+error.get('category',error['type'])})
            run['requests']=getattr(components.get('budget'),'requests',0)
            run['completed_at']=now(); self.repository.save_run(run)
        logger.info('evaluation_finished run=%s status=%s',run['id'],run['status'])
        return self.repository.get(run['id'])
    def launch(self,agent_id,count=20,seed=0,mode='CORE'):
        global _active_job
        with _job_lock:
            if _active_job:
                existing=self.repository.get(_active_job)
                if existing and existing['agent_id']==agent_id: return existing
                raise ValueError('Уже выполняется проверка другого агента. Дождитесь завершения.')
            run=self.prepare(agent_id,count,seed,mode); _active_job=run['id']
        def work():
            global _active_job
            try: self.execute(run)
            finally:
                with _job_lock: _active_job=None
        threading.Thread(target=work,name='focus-evaluation',daemon=True).start()
        return run


def contract_confirmed(run):
    return run.get('requirement_contract',{}).get('confirmed',False)
