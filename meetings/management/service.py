import hashlib
import hmac
import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo

from meetings import auth, store
from meetings.auth import MeetError
from meetings.knowledge.common import aware, iso, not_found, utc_now

MINSK = ZoneInfo('Europe/Minsk')
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
STALE_AFTER = timedelta(hours=48)
COUNTERS = ('on_time_orders', 'completed_orders', 'defective_units', 'produced_units',
            'occupied_capacity', 'available_capacity')
RATIOS = (
    ('on_time_orders', 'Заказы в срок', 'on_time_orders', 'completed_orders'),
    ('defect_rate', 'Брак', 'defective_units', 'produced_units'),
    ('capacity_utilization', 'Загрузка производства', 'occupied_capacity', 'available_capacity'),
)


def visible_tasks(connection, actor):
    from meetings.access import predicate
    sql, params = predicate(connection, actor, 'meeting', 'm', model=True)
    return [dict(row) for row in connection.execute(
        'SELECT t.* FROM tasks t JOIN meetings m ON m.id=t.meeting_id WHERE ' + sql + ' ORDER BY t.id', params)]


def overdue(task, day):
    if task['status'] in ('done','cancelled') or not isinstance(task['due'], str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', task['due']):
        return False
    try:
        return date.fromisoformat(task['due']) < day
    except ValueError:
        return False


def metric_rows(connection, actor, cutoff, warnings, department_id=None):
    exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='production_metrics'").fetchone()
    if not exists:
        warnings.append('Производственная витрина не загружена.')
        return []
    from meetings.access import predicate
    sql, params = predicate(connection, actor, 'metric', 'p', model=True)
    if department_id is not None:
        sql += ' AND p.department_id=?'; params.append(department_id)
    rows = connection.execute('SELECT p.* FROM production_metrics p WHERE ' + sql, params)
    latest = {}
    for raw in rows:
        row = dict(raw)
        try:
            stamp, start, end = (aware(row[key]) for key in ('as_of', 'period_start', 'period_end'))
            if stamp > cutoff or start > cutoff:
                continue
            if start >= end or stamp < start or not row['scope'] or not row['source_id']:
                raise ValueError('invalid snapshot period')
            for key in COUNTERS:
                if not isinstance(row[key], (int, float)) or not math.isfinite(row[key]) or row[key] < 0:
                    raise ValueError('invalid counter')
        except (ValueError, TypeError, OverflowError):
            warnings.append('Некорректный доступный снимок витрины исключён из расчёта.')
            continue
        group = (row['scope'], start, end)
        previous = latest.get(group)
        if previous is None or (stamp, row['source_id']) > (aware(previous['as_of']), previous['source_id']):
            latest[group] = row
    if not latest:
        warnings.append('Нет доступных производственных данных на выбранную дату.')
        return []
    # Keep latest snapshots per (scope, period), then select the common period.
    # A late correction to October must not hide an existing November snapshot.
    # ACL filtering precedes even period selection.
    period = max((aware(row['period_start']), aware(row['period_end'])) for row in latest.values())
    selected = [row for row in latest.values() if (aware(row['period_start']), aware(row['period_end'])) == period]
    if len(selected) != len(latest):
        warnings.append('Доступные снимки за другие периоды не включены в показатели текущего периода.')
    return sorted(selected, key=lambda row: row['source_id'])


def microseconds(value):
    delta = value.astimezone(timezone.utc) - EPOCH
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def aggregate_source(key, cutoff, observed, rows, source_at, title):
    payload = json.dumps({'key': key, 'cutoff': iso(cutoff), 'observed_at': iso(observed), 'rows': rows}, ensure_ascii=False,
                         sort_keys=True, separators=(',', ':')).encode()
    # A keyed fingerprint cannot be used to guess private counts offline. It is
    # only an identifier: the resolver still rechecks ACL on every underlying row.
    digest = hmac.new(auth._secret(), payload, hashlib.sha256).hexdigest()
    return {'kind': 'metric', 'id': f'A~{key}~{microseconds(cutoff)}~{microseconds(observed)}~{digest}',
            'title': title, 'source_at': source_at}


def json_number(value):
    """Keep extreme but valid source totals representable in JSON clients."""
    converted = float(value)
    if not math.isfinite(converted):
        return str(value)
    return int(value) if value == value.to_integral_value() else converted


def ratio(rows, numerator, denominator, label, warnings):
    # Summing finite IEEE floats can overflow before division, even when their
    # ratio is exactly 100%. Decimal avoids that intermediate overflow.
    with localcontext() as context:
        context.prec = 64
        top = sum((Decimal(str(row[numerator])) for row in rows), Decimal(0))
        bottom = sum((Decimal(str(row[denominator])) for row in rows), Decimal(0))
        if not bottom:
            warnings.append(f'{label}: значение не рассчитано, знаменатель равен нулю.')
            value = None
        else:
            percentage = top / bottom * 100
            value = float(percentage)
            if not math.isfinite(value):
                value = None
                warnings.append(f'{label}: результат выходит за допустимый числовой диапазон.')
            else:
                value = round(value, 2)
    return value, json_number(top), json_number(bottom)


def build(connection, actor, cutoff, generated):
    warnings, metrics, manifests = [], [], {}
    tasks = visible_tasks(connection, actor)
    open_rows = [task for task in tasks if task['status'] not in ('done','cancelled')]
    late_rows = [task for task in open_rows if overdue(task, cutoff.astimezone(MINSK).date())]
    task_dates = []
    for task in tasks:
        try:
            task_dates.append(aware(task['updated_at']))
        except (ValueError, TypeError):
            warnings.append('У части доступных задач неизвестна дата обновления; счётчики рассчитаны по текущему реестру.')
    # An as_of deadline cutoff is not the observation time of a current registry.
    # Persist the latter in the signed ID so reopening preserves its provenance.
    task_stamp = iso(max(task_dates, default=generated))
    for key, label, rows, formula in (
        ('open_tasks', 'Открытые задачи', open_rows, "count(status NOT IN ('done','cancelled')); текущий реестр"),
        ('overdue_tasks', 'Просроченные задачи', late_rows,
         f"count(status NOT IN ('done','cancelled') AND valid_date(due) < {cutoff.astimezone(MINSK).date().isoformat()}); Europe/Minsk"),
    ):
        # Include all visible tasks in fingerprint: changing a closed task to open
        # must invalidate an old source even if the old result was zero.
        source = aggregate_source(key, cutoff, generated, tasks, task_stamp, label + ': реестр задач')
        metric = {'key': key, 'label': label, 'value': len(rows), 'unit': 'задач', 'formula': formula, 'source': source}
        metrics.append(metric)
        manifests[source['id']] = {'metric': metric, 'tasks': [store.task_out(connection, task) for task in rows],
                                   'evaluated_at': iso(generated), 'deadline_date': cutoff.astimezone(MINSK).date().isoformat()}
    snapshots = metric_rows(connection, actor, cutoff, warnings)
    freshness = min((aware(row['as_of']) for row in snapshots), default=None)
    if freshness is not None and generated - freshness > STALE_AFTER:
        warnings.append('Производственная витрина устарела: самому старому используемому снимку больше 48 часов.')
    if snapshots:
        period = f"[{snapshots[0]['period_start']}, {snapshots[0]['period_end']})"
        for key, label, numerator, denominator in RATIOS:
            value, top, bottom = ratio(snapshots, numerator, denominator, label, warnings)
            source = aggregate_source(key, cutoff, generated, snapshots, iso(freshness), label + ': производственная витрина')
            metric = {'key': key, 'label': label, 'value': value, 'unit': '%',
                      'formula': f'sum({numerator}) / sum({denominator}) × 100; период {period}', 'source': source}
            metrics.append(metric)
            manifests[source['id']] = {'metric': metric, 'numerator': top, 'denominator': bottom,
                                       'period_start': snapshots[0]['period_start'], 'period_end': snapshots[0]['period_end'],
                                       'snapshots': snapshots}
    from meetings.management import domain
    extra_metrics, extra_manifests, extra_warnings, extra_freshness, domain_data = domain.build(
        connection,actor,cutoff,generated,aggregate_source,tasks)
    metrics.extend(extra_metrics); manifests.update(extra_manifests); warnings.extend(extra_warnings)
    if extra_freshness is not None: freshness = min(freshness,extra_freshness) if freshness else extra_freshness
    if extra_metrics:
        import os
        fault = os.getenv('MOCK_CRM_FAULT','')
        if fault=='stale': warnings.append('Данные CRM устарели. Показана сохранённая витрина; проверьте дату источника.')
        elif fault in ('timeout','down'): warnings.append('Источник CRM недоступен. Показана сохранённая витрина; её актуальность не подтверждена.')
        for metric in metrics:
            metric.setdefault('as_of',metric['source']['source_at'])
            metric.setdefault('status',domain.status(metric['key'],metric['value']))
    if cutoff.astimezone(MINSK).date() != generated.astimezone(MINSK).date():
        warnings.append('Статусы задач взяты из текущего реестра; as_of задаёт дату просрочки и срез витрины, а не историю статусов.')
    summary = [{'text': f"{metric['label']}: {metric['value']} {metric['unit']}.", 'sources': [metric['source']]}
               for metric in metrics if metric['value'] is not None]
    result = {'as_of': iso(freshness) if freshness else None, 'generated_at': iso(generated), 'metrics': metrics,
              'overdue_tasks': [store.task_out(connection, task) for task in late_rows], 'summary': summary,
              'warnings': list(dict.fromkeys(warnings)), **domain_data}
    return result, manifests


def overview(actor, as_of, audit):
    generated = utc_now()
    cutoff = parse_cutoff(as_of) if as_of is not None else generated
    with store.db() as connection:
        connection.execute('BEGIN')  # consistent ACL + aggregate snapshot
        result, _ = build(connection, actor, cutoff, generated)
    audit['source_ids'] = [metric['source']['id'] for metric in result['metrics']]
    return result


def parse_cutoff(value):
    try:
        parsed = aware(value).astimezone(timezone.utc)
        if not 1970 <= parsed.year <= 9998:
            raise ValueError('unsupported date')
        return parsed
    except (ValueError, TypeError, OverflowError):
        raise MeetError(422, 'invalid_date', 'as_of должен быть ISO 8601 с часовым поясом.') from None


def source_timestamp(value):
    try:
        return iso(aware(value))
    except (ValueError, TypeError, OverflowError):
        raise MeetError(409, 'invalid_source_date', 'В источнике нет корректной даты. Требуется обновление данных.') from None


def resolve(actor, kind, source_id, audit):
    with store.db() as connection:
        connection.execute('BEGIN')
        if kind == 'insight':
            from meetings.management.advanced import resolve as advanced_source
            from meetings.access import load_user
            result=advanced_source(connection,load_user(connection,actor),source_id)
            audit.update(object_id=source_id,source_ids=[source_id])
            return result
        elif kind in ('document','utterance'):
            from meetings.evidence import resolve as evidence
            from meetings.access import load_user
            result=evidence(connection,load_user(connection,actor),kind,source_id)
            audit.update(object_id=source_id,source_ids=[source_id])
            return result
        elif kind == 'assistant':
            from meetings.assistant.service import source_result
            from meetings.access import load_user
            user = load_user(connection,actor)
            result = source_result(connection,user,source_id)
            audit.update(object_id=source_id,source_ids=[source_id])
            return result
        elif kind == 'call':
            from meetings import calls,access
            key=source_id[1:] if source_id.startswith('C') else source_id
            if not re.fullmatch(r'[1-9]\d{0,17}',key):raise not_found()
            user=access.load_user(connection,actor)
            row=calls.checked(connection,user,int(key))
            source={'kind':'call','id':source_id,'title':'Звонок '+key,'source_at':source_timestamp(row['started_at'])}
            data=calls.analyze(connection,user,row)
            data['meeting']={'id':row['meeting_id'],'title':'Расшифровка звонка','scheduled_at':row['started_at']}
        elif kind == 'meeting':
            if not re.fullmatch(r'[1-9]\d{0,18}', source_id) or int(source_id) > 2**63 - 1:
                raise not_found()
            if not store.can_read_meeting(connection, actor, int(source_id), model=True):
                raise not_found()
            row = connection.execute('SELECT * FROM meetings WHERE id=?', (int(source_id),)).fetchone()
            source = {'kind':'meeting','id':source_id,'title':row['title'],'source_at':source_timestamp(row['created_at'])}
            data = {'meeting':{'id':row['id'],'title':row['title'],'scheduled_at':row['scheduled_at']}}
        elif kind == 'task':
            task_key = source_id[1:] if source_id.startswith('T') else source_id
            if not re.fullmatch(r'[1-9]\d{0,18}', task_key) or int(task_key) > 2**63 - 1:
                raise not_found()
            task = connection.execute('SELECT * FROM tasks WHERE id=?', (int(task_key),)).fetchone()
            if not task or not store.can_read_meeting(connection, actor, task['meeting_id']):
                raise not_found()
            source = {'kind': 'task', 'id': source_id, 'title': task['text'], 'source_at': source_timestamp(task['updated_at']),
                      'quote': task['text'], 'locator': f"meeting:{task['meeting_id']}"}
            data = store.task_out(connection, task)
        elif kind == 'metric':
            if source_id.startswith('A~'):
                match = re.fullmatch(r'A~([a-z_]+)~(\d{1,18})~(\d{1,18})~([0-9a-f]{64})', source_id)
                if not match:
                    raise not_found()
                try:
                    cutoff = EPOCH + timedelta(microseconds=int(match[2]))
                    observed = EPOCH + timedelta(microseconds=int(match[3]))
                except (ValueError, OverflowError, OSError):
                    raise not_found() from None
                _, manifests = build(connection, actor, cutoff, observed)
                data = manifests.get(source_id)
                if data is None:
                    raise not_found()
                source = data['metric']['source']
            else:
                if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='production_metrics'").fetchone():
                    raise not_found()
                from meetings.access import predicate
                sql, params = predicate(connection, actor, 'metric', 'p')
                row = connection.execute('SELECT p.* FROM production_metrics p WHERE p.source_id=? AND ' + sql,
                                         [source_id, *params]).fetchone()
                if not row:
                    raise not_found()
                data = dict(row)
                source = {'kind': 'metric', 'id': row['source_id'], 'title': 'Производственный снимок: ' + row['scope'],
                          'source_at': source_timestamp(row['as_of']), 'locator': f"[{row['period_start']}, {row['period_end']})"}
        else:
            raise not_found()
    audit.update(object_id=source_id, source_ids=[source_id])
    return {'source': source, 'data': data}
