"""Source-system KPI: known denominators, department scope and replayable evidence."""
from datetime import datetime, timezone
import json
from tests.test_track3_task_controls import env
from meetings import store

AS_OF = '2026-11-11T12:00:00+00:00'


def overview(client, as_of=AS_OF):
    response = client.get('/api/meet/overview',params={'as_of':as_of})
    assert response.status_code==200,response.text
    result = response.json(); return result,{m['key']:m for m in result['metrics']}


def test_known_source_ratios_forecast_and_every_metric_source_opens(env):
    client = env['director']; result,metrics = overview(client)
    assert metrics['support_sla']['value']==92 and metrics['support_sla']['numerator']==368 and metrics['support_sla']['denominator']==400
    assert metrics['mary_resolution']['value']==68 and metrics['mary_resolution']['numerator']==272 and metrics['mary_resolution']['denominator']==400
    assert metrics['capacity_forecast_peak']['value']==111
    assert metrics['capacity_forecast_peak']['numerator']==888 and metrics['capacity_forecast_peak']['denominator']==800
    assert metrics['capacity_forecast_peak']['status']=='critical'
    assert len(result['capacity_forecast'])==4
    assert [r['count'] for r in result['delay_reasons']]==[7,3,2]
    for metric in metrics.values():
        assert metric['formula'] and metric['source']['source_at']
        source = metric['source']
        opened = client.get(f"/api/meet/sources/{source['kind']}/{source['id']}")
        assert opened.status_code==200,opened.text
        assert opened.json()['data']['metric']['value']==metric['value']
    # Frozen source ratios do not drift when wall-clock/selected date advances.
    _,later = overview(client,'2026-11-12T12:00:00+00:00')
    assert later['support_sla']['value']==92 and later['mary_resolution']['denominator']==400
    assert metrics['support_sla']['as_of']=='2026-11-11T09:00:00+00:00'


def test_department_filter_precedes_aggregate_and_freshness(env):
    prod,metrics = overview(env['prod_head'])
    assert 'support_sla' not in metrics and 'mary_resolution' not in metrics
    assert 'capacity_forecast_peak' in metrics
    with store.db() as c:
        c.execute("UPDATE support_interactions SET as_of='2026-11-04T00:00:00+00:00',first_response_seconds=99999999")
    again,changed = overview(env['prod_head'])
    assert prod['as_of']==again['as_of']
    assert {k:m['value'] for k,m in metrics.items()}=={k:m['value'] for k,m in changed.items()}
    assert all('SLA' not in w and 'Mary' not in w for w in again['warnings'])
    _,director = overview(env['director'])
    source = director['support_sla']['source']
    assert env['prod_head'].get(f"/api/meet/sources/metric/{source['id']}").status_code==404


def test_forecast_zero_and_large_finite_counters(env):
    with store.db() as c:
        c.execute('UPDATE production_plan SET available_hours=0 WHERE forecast=1')
    result,metrics = overview(env['director'])
    assert metrics['capacity_forecast_peak']['value'] is None
    assert any('Прогноз' in w and 'знаменатель' in w for w in result['warnings'])
    with store.db() as c:
        c.execute('UPDATE production_plan SET available_hours=1e308,occupied_hours=1e308 WHERE forecast=1')
        # Two sections in the same period overflow a binary-float sum, but ratio is still100%.
        c.execute("INSERT INTO production_plan(source_id,as_of,department_id,section,period_start,period_end,planned_units,produced_units,defective_units,available_hours,occupied_hours,forecast) SELECT source_id||':copy',as_of,department_id,'Дополнительная секция',period_start,period_end,planned_units,produced_units,defective_units,available_hours,occupied_hours,forecast FROM production_plan WHERE forecast=1")
    result,metrics = overview(env['director'])
    assert metrics['capacity_forecast_peak']['value']==100
    json.dumps(result,allow_nan=False)


def test_source_changes_invalidate_only_affected_evidence_and_task_alias(env):
    client = env['director']; _,metrics = overview(client)
    source = metrics['mary_resolution']['source']
    with store.db() as c: c.execute("UPDATE support_interactions SET closed_by='human' WHERE id='mary-00001'")
    assert client.get(f"/api/meet/sources/metric/{source['id']}").status_code==404
    target = env['ids']['meetings']['delay']
    task = env['prod_head'].get(f'/api/meet/meetings/{target}').json()['followup']['open_tasks'][0]
    opened = env['prod_head'].get('/api/meet/sources/task/'+task['source']['id'])
    assert opened.status_code==200 and opened.json()['data']['id']==task['id']
