from datetime import datetime, timezone

import pytest

from meetings import store
from meetings.management import service
from test_track3_knowledge_support import env, meeting, task, snapshot


def test_aggregate_source_cannot_be_reinterpreted_by_changing_cutoff(env):
    task(meeting(env['irina']), due='2026-11-11')
    response = env['irina'].get('/api/meet/overview', params={'as_of': '2026-11-11T09:00:00Z'})
    source = next(m['source'] for m in response.json()['metrics'] if m['key'] == 'overdue_tasks')
    parts = source['id'].split('~')
    parts[2] = str(int(parts[2]) + 86400 * 1_000_000)
    changed = env['irina'].get('/api/meet/sources/metric/' + '~'.join(parts))
    assert changed.status_code == 404, changed.text


def test_empty_registry_source_preserves_original_timestamp_when_reopened(env, monkeypatch):
    monkeypatch.setattr(service, 'utc_now', lambda: datetime(2026, 11, 11, 9, tzinfo=timezone.utc))
    result = env['irina'].get('/api/meet/overview').json()
    source = result['metrics'][0]['source']
    monkeypatch.setattr(service, 'utc_now', lambda: datetime(2026, 11, 12, 9, tzinfo=timezone.utc))
    opened = env['irina'].get('/api/meet/sources/metric/' + source['id'])
    assert opened.status_code == 200, opened.text
    assert opened.json()['source'] == source


def test_historical_deadline_cutoff_does_not_backdate_an_empty_registry(env, monkeypatch):
    observed = datetime(2026, 11, 11, 9, tzinfo=timezone.utc)
    monkeypatch.setattr(service, 'utc_now', lambda: observed)
    response = env['irina'].get('/api/meet/overview', params={'as_of': '2026-11-01T00:00:00Z'})
    assert response.status_code == 200
    source = response.json()['metrics'][0]['source']
    assert source['source_at'] == observed.isoformat()
    monkeypatch.setattr(service, 'utc_now', lambda: datetime(2026, 11, 12, 9, tzinfo=timezone.utc))
    reopened = env['irina'].get('/api/meet/sources/metric/' + source['id'])
    assert reopened.status_code == 200 and reopened.json()['source'] == source


def test_old_task_with_unknown_update_date_does_not_break_registry_counts(env):
    tid = task(meeting(env['irina']))
    with store.db() as connection:
        connection.execute("UPDATE tasks SET updated_at='unknown' WHERE id=?", (tid,))
    response = env['irina'].get('/api/meet/overview')
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['metrics'][0]['value'] == 1
    assert any('дат' in warning for warning in result['warnings'])


@pytest.mark.parametrize('values,expected', [((0, 0, 0, 0, 1e308, 1e308), 100),
                                           ((0, 0, 0, 0, 1e308, 1e-308), None)])
def test_extreme_finite_counter_values_never_produce_invalid_json(env, values, expected):
    snapshot('one', scope='one', values=values)
    snapshot('two', scope='two', values=values)
    response = env['irina'].get('/api/meet/overview', params={'as_of': '2026-11-11T10:00:00Z'})
    assert response.status_code == 200, response.text
    metric = next(m for m in response.json()['metrics'] if m['key'] == 'capacity_utilization')
    assert metric['value'] == expected
    opened = env['irina'].get('/api/meet/sources/metric/' + metric['source']['id'])
    assert opened.status_code == 200, opened.text


def test_empty_explicit_cutoff_is_invalid(env):
    response = env['irina'].get('/api/meet/overview', params={'as_of': ''})
    assert response.status_code == 422


@pytest.mark.parametrize('kind', ['metric', 'task'])
def test_opened_sources_never_invent_or_return_invalid_source_dates(env, kind):
    if kind == 'task':
        source_id = str(task(meeting(env['irina'])))
        with store.db() as connection:
            connection.execute("UPDATE tasks SET updated_at='unknown' WHERE id=?", (int(source_id),))
    else:
        snapshot()
        source_id = 'print-1'
        with store.db() as connection:
            connection.execute("UPDATE production_metrics SET as_of='unknown' WHERE source_id=?", (source_id,))
    response = env['irina'].get(f'/api/meet/sources/{kind}/{source_id}')
    assert response.status_code == 409 and response.json()['code'] == 'invalid_source_date'
