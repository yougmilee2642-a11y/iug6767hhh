from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from meetings import store
from meetings.management import service
from test_track3_knowledge_support import env, meeting, task, snapshot, audit_rows

CUTOFF = '2026-11-11T09:00:00+00:00'


def overview(env, who='irina', at=CUTOFF):
    response = env[who].get('/api/meet/overview', params={'as_of': at})
    assert response.status_code == 200, response.text
    result = response.json()
    return result, {metric['key']: metric for metric in result['metrics']}


def test_known_formulas_and_all_sources_open(env):
    mid = meeting(env['irina'])
    tid = task(mid)
    task(mid, status='done')
    snapshot()
    result, metrics = overview(env)
    assert metrics['open_tasks']['value'] == metrics['overdue_tasks']['value'] == 1
    assert metrics['on_time_orders']['value'] == 90
    assert metrics['defect_rate']['value'] == 2
    assert metrics['capacity_utilization']['value'] == 75
    assert result['as_of'] == CUTOFF and result['generated_at']
    for metric in metrics.values():
        assert metric['unit'] and metric['formula'] and metric['source']['source_at']
        source = metric['source']
        opened = env['irina'].get(f"/api/meet/sources/{source['kind']}/{source['id']}")
        assert opened.status_code == 200, opened.text
        assert opened.json()['data']['metric']['value'] == metric['value']
    assert env['irina'].get('/api/meet/sources/metric/print-1').json()['data']['on_time_orders'] == 90
    opened = env['irina'].get(f'/api/meet/sources/task/{tid}')
    assert opened.status_code == 200 and opened.json()['data']['id'] == tid
    assert audit_rows('overview.read')[-1]['source_ids']


@pytest.mark.parametrize('numerator', [0, 1])
def test_zero_denominators(env, numerator):
    snapshot(values=(numerator, 0, numerator, 0, numerator, 0))
    result, metrics = overview(env)
    for key, _, _, _ in service.RATIOS:
        assert metrics[key]['value'] is None
    assert len([warning for warning in result['warnings'] if 'знаменатель' in warning]) == 3
    assert len(result['summary']) == 2


@pytest.mark.parametrize('at,expected', [('2026-11-10T20:59:59+00:00', 0),
                                      ('2026-11-10T21:00:00+00:00', 1),
                                      ('2026-11-11T00:00:00+03:00', 1)])
def test_minsk_midnight_strict_due_and_done_exclusion(env, at, expected):
    mid = meeting(env['irina'])
    task(mid, due='2026-11-10')
    task(mid, due='2026-11-11', status='in_progress')
    task(mid, due='2026-11-09', status='done')
    task(mid, due='завтра', due_status='unknown')
    task(mid, due='20261101')
    task(mid, due='2026-02-30')
    task(mid, due=None)
    result, metrics = overview(env, at=at)
    assert metrics['open_tasks']['value'] == 6
    assert metrics['overdue_tasks']['value'] == expected
    assert len(result['overdue_tasks']) == expected


def test_acl_before_every_count_sum_period_selection_and_resolver(env):
    private = meeting(env['irina'])
    shared = meeting(env['irina'], shared=(2,))
    secret_task = task(private, text='SECRET TASK')
    shared_task = task(shared)
    snapshot('private-row', scope='SECRET-SCOPE', values=(0, 900, 0, 900, 0, 900))
    snapshot('shared-row', scope='shared', values=(90, 100, 20, 1000, 60, 80), shared=(2,))
    # A hidden later reporting period must not suppress the reader's visible period.
    snapshot('private-next-period', scope='secret-next', at='2026-11-12T09:00:00+00:00',
             start='2026-11-12T00:00:00+00:00', end='2026-11-13T00:00:00+00:00')
    director, all_metrics = overview(env, at='2026-11-12T10:00:00+00:00')
    reader, own_metrics = overview(env, 'petr', at='2026-11-12T10:00:00+00:00')
    assert all_metrics['open_tasks']['value'] == 2 and own_metrics['open_tasks']['value'] == 1
    assert own_metrics['on_time_orders']['value'] == 90
    assert 'SECRET' not in str(reader) and 'secret-next' not in str(reader)
    for kind, sid in (('task', secret_task), ('metric', 'private-row'), ('metric', 'private-next-period'),
                      ('metric', all_metrics['open_tasks']['source']['id']),
                      ('metric', all_metrics['on_time_orders']['source']['id'])):
        denied = env['petr'].get(f'/api/meet/sources/{kind}/{sid}')
        assert denied.status_code == 404, denied.text
        assert 'SECRET' not in denied.text
    assert env['petr'].get(f'/api/meet/sources/task/{shared_task}').status_code == 200
    assert env['petr'].get('/api/meet/sources/metric/shared-row').status_code == 200


def test_weighted_ratio_instead_of_average_of_percentages(env):
    snapshot('one', scope='one', values=(1, 1, 0, 1, 1, 1))
    snapshot('two', scope='two', values=(0, 9, 0, 1, 0, 9))
    _, metrics = overview(env)
    assert metrics['on_time_orders']['value'] == 10
    assert metrics['capacity_utilization']['value'] == 10


def test_latest_per_scope_temporal_cutoff_and_periods_not_double_counted(env):
    snapshot('old', values=(1, 2, 0, 1, 1, 2), at='2026-11-10T09:00:00+00:00')
    snapshot('current', values=(9, 10, 0, 1, 1, 2))
    snapshot('future', values=(0, 10, 0, 1, 0, 2), at='2026-11-12T09:00:00+00:00')
    _, metrics = overview(env)
    assert metrics['on_time_orders']['value'] == 90
    _, historical = overview(env, at='2026-11-10T10:00:00+00:00')
    assert historical['on_time_orders']['value'] == 50
    snapshot('older-period', scope='old-scope', at='2026-10-31T09:00:00+00:00',
             start='2026-10-01T00:00:00+03:00', end='2026-11-01T00:00:00+03:00')
    result, metrics = overview(env)
    assert metrics['on_time_orders']['value'] == 90
    assert any('другие периоды' in warning for warning in result['warnings'])


def test_snapshot_freshness_is_source_timestamp_not_generation(env, monkeypatch):
    snapshot(at='2026-11-01T09:00:00+00:00')
    monkeypatch.setattr(service, 'utc_now', lambda: datetime(2026, 11, 11, 9, tzinfo=timezone.utc))
    result, metrics = overview(env)
    assert result['as_of'] == '2026-11-01T09:00:00+00:00'
    assert result['generated_at'] == CUTOFF
    assert metrics['on_time_orders']['source']['source_at'] == result['as_of']
    assert any('устарела' in warning for warning in result['warnings'])


def test_empty_missing_and_only_hidden_snapshots(env):
    result, metrics = overview(env)
    assert len(metrics) == 2 and result['as_of'] is None and result['warnings']
    assert metrics['open_tasks']['value'] == 0
    snapshot()
    result, metrics = overview(env, 'petr')
    assert len(metrics) == 2 and 'print' not in str(result)
    with store.db() as connection:
        connection.execute('DROP TABLE production_metric_access')
        connection.execute('DROP TABLE production_metrics')
    result, metrics = overview(env)
    assert len(metrics) == 2 and any('не загружена' in warning for warning in result['warnings'])


def test_aggregate_resolver_rechecks_revoked_acl_and_tampering(env):
    snapshot(shared=(2,))
    _, metrics = overview(env, 'petr')
    sid = metrics['on_time_orders']['source']['id']
    assert env['petr'].get('/api/meet/sources/metric/' + sid).status_code == 200
    with store.db() as connection:
        connection.execute('DELETE FROM production_metric_access WHERE user_id=2')
    assert env['petr'].get('/api/meet/sources/metric/' + sid).status_code == 404
    assert env['petr'].get('/api/meet/sources/metric/print-1').status_code == 404
    assert env['irina'].get('/api/meet/sources/metric/' + sid[:-1] + ('0' if sid[-1] != '0' else '1')).status_code == 404
    assert audit_rows('source.read')[-1]['result'] == 'denied'


def test_task_source_invalidates_on_change_and_acl_revocation(env):
    mid = meeting(env['irina'], shared=(2,))
    tid = task(mid)
    _, metrics = overview(env, 'petr')
    sid = metrics['open_tasks']['source']['id']
    with store.db() as connection:
        connection.execute("UPDATE tasks SET status='done' WHERE id=?", (tid,))
    assert env['petr'].get('/api/meet/sources/metric/' + sid).status_code == 404
    with store.db() as connection:
        connection.execute('DELETE FROM meeting_access WHERE user_id=2')
    assert env['petr'].get('/api/meet/sources/task/' + str(tid)).status_code == 404


@pytest.mark.parametrize('value', ['2026-11-11', '2026-11-11T12:00:00', 'garbage', '9999-11-11T00:00:00Z'])
def test_invalid_or_naive_as_of_rejected(env, value):
    response = env['irina'].get('/api/meet/overview', params={'as_of': value})
    assert response.status_code == 422 and response.json()['code'] == 'invalid_date'


def test_auth_and_unsupported_resolver_kind(env):
    anon = TestClient(env['app'])
    assert anon.get('/api/meet/overview').status_code == 401
    assert anon.get('/api/meet/sources/task/1').status_code == 401
    for path in ('document/F1', 'utterance/U1', 'task/-1', 'metric/A~bad', 'task/' + '9' * 60, 'task/' + '9' * 19):
        assert env['irina'].get('/api/meet/sources/' + path).status_code == 404


def test_default_cutoff_sources_reopen_and_invalid_snapshots_are_excluded(env):
    snapshot()
    response = env['irina'].get('/api/meet/overview')
    assert response.status_code == 200, response.text
    for metric in response.json()['metrics']:
        assert env['irina'].get('/api/meet/sources/metric/' + metric['source']['id']).status_code == 200
    with store.db() as connection:
        connection.execute("UPDATE production_metrics SET completed_orders=-1 WHERE source_id='print-1'")
    result, metrics = overview(env)
    assert len(metrics) == 2 and any('Некорректный' in warning for warning in result['warnings'])
