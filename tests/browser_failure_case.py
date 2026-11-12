"""Inject an intentionally wrong MODEL response in an existing disposable UI smoke DB.
This runs the real EvaluationService/Runtime, not fabricated results or assertions.
Usage: python tests/browser_failure_case.py <focus-browser-.../test.sqlite> <agent_id>
"""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import storage
from providers.base import ModelReply
from tests.evaluation_doubles import components, DeterministicAgent
from evaluation.service import EvaluationService


class WrongPriceAgent(DeterministicAgent):
    def complete(self,messages,tools):
        latest=next(m.text for m in reversed(messages) if m.role=='user')
        if 'сколько' in latest.casefold(): return ModelReply('Стоимость услуги 999 BYN.')
        return super().complete(messages,tools)


if __name__=='__main__':
    target=Path(sys.argv[1]).resolve()
    if target.name!='test.sqlite' or not target.parent.name.startswith('focus-browser-') or not target.is_file():
        raise SystemExit('Only the existing disposable browser-smoke database is accepted.')
    storage.DB_PATH=target;storage.DATA_DIR=target.parent
    def faulty_components():
        value=components();value['agent_factory']=WrongPriceAgent
        value['provider_info']['fault']='intentional_wrong_price_999_BYN'
        return value
    service=EvaluationService(components_factory=faulty_components)
    with storage.connect() as db:
        before=[db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('bookings','interactions','escalations')]
    result=service.execute(service.prepare(sys.argv[2],20))
    with storage.connect() as db:
        after=[db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('bookings','interactions','escalations')]
    assert before==after, 'Simulation must not change the smoke business history'
    assert result['readiness']['status']=='LIMITED'
    assert any(s['result']['status']=='FAIL' for s in result['scenarios'])
    print(json.dumps({'id':result['id'],'status':result['status'],'readiness':result['readiness'],
                      'history_unchanged':before==after},ensure_ascii=False))
