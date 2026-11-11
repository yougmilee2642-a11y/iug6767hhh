from fastapi import APIRouter, HTTPException
from pydantic import Field
from agents.models import StrictModel
from typing import Literal
from evaluation.service import EvaluationService
from evaluation.config import DEFAULT_SCENARIOS, MIN_SCENARIOS, MAX_SCENARIOS
from fastapi.responses import HTMLResponse
from evaluation.report import explain, report_html


class RunRequest(StrictModel):
    agent_id: str = Field(min_length=1,max_length=100)
    count: int = Field(default=DEFAULT_SCENARIOS,ge=MIN_SCENARIOS,le=MAX_SCENARIOS)
    seed: int = Field(default=0,ge=0,le=2147483647)
    mode: Literal['CORE','STANDARD','DEEP'] = 'CORE'


def router(service_factory):
    api=APIRouter()
    @api.get('/api/evaluation/options')
    def options():
        from evaluation.local import evaluation_options
        return evaluation_options()
    @api.post('/api/evaluations',status_code=202)
    def create(payload:RunRequest):
        try: return service_factory().launch(payload.agent_id,payload.count,payload.seed,payload.mode)
        except LookupError as exc: raise HTTPException(404,str(exc))
        except ValueError as exc: raise HTTPException(422,str(exc))
    @api.get('/api/agents/{agent_id}/evaluations')
    def history(agent_id:str): return {'items':service_factory().repository.list(agent_id)}
    @api.get('/api/evaluations/{run_id}')
    def get(run_id:str):
        run=service_factory().repository.get(run_id, details=True)
        if not run: raise HTTPException(404,'Проверка не найдена')
        for scenario in run.get('scenarios', []):
            if scenario.get('result'):
                result = scenario['result']
                result['explanation'] = explain(scenario, result, run.get('config_snapshot'))
                result.pop('trace', None)
        return run
    @api.get('/api/evaluations/{run_id}/report', response_class=HTMLResponse)
    def report(run_id:str, compare_with:str | None = None):
        run=service_factory().repository.get(run_id, details=True)
        if not run: raise HTTPException(404,'Проверка не найдена')
        previous=None
        if compare_with:
            previous=service_factory().repository.get(compare_with, details=True)
            if not previous: raise HTTPException(404,'Исходный прогон для сравнения не найден')
            if previous['agent_id'] != run['agent_id']:
                raise HTTPException(422,'Для сравнения выберите прогоны одного агента')
        return HTMLResponse(report_html(run, previous), headers={'Content-Disposition': 'inline'})
    @api.get('/api/evaluations/{run_id}/scenarios/{scenario_id}')
    def detail(run_id:str,scenario_id:str):
        result=service_factory().repository.result(run_id,scenario_id)
        if not result: raise HTTPException(404,'Сценарий ещё не выполнен или не найден')
        return result
    return api
