"""Deterministic KPI over scoped source snapshots. No inference or external calls."""
from datetime import timedelta
from decimal import Decimal, localcontext
import json
import math
from pathlib import Path

from meetings import access, store
from meetings.knowledge.common import aware, iso

TABLES = {'erp_orders', 'support_interactions', 'production_plan'}
THRESHOLDS = json.loads(Path(__file__).with_name('thresholds.json').read_text(encoding='utf-8'))


def status(key, value):
    rule = THRESHOLDS['thresholds'].get(key)
    if value is None: return 'no_data'
    if not rule: return 'informational'
    if rule['direction'] == 'min':
        return 'ok' if value >= rule['ok'] else 'warning' if value >= rule['warning'] else 'critical'
    return 'ok' if value <= rule['ok'] else 'warning' if value <= rule['warning'] else 'critical'


def selected(connection, actor, table, cutoff, warnings, own=None):
    if table not in TABLES: raise ValueError('Unsupported domain table')
    scope, params = access.snapshot_predicate(connection, actor, 's', own_column=own)
    rows = connection.execute('SELECT s.* FROM ' + table + ' s WHERE ' + scope +
                              ' AND julianday(s.as_of)<=julianday(?) ORDER BY s.source_id', [*params,iso(cutoff)])
    result = []
    for raw in rows:
        row = dict(raw)
        try:
            aware(row['as_of'])
            if not row['source_id']: raise ValueError()
            if table == 'support_interactions':
                aware(row['opened_at'])
                if any(not isinstance(row[k],int) or row[k]<0 for k in ('first_response_seconds','sla_seconds')): raise ValueError()
            elif table == 'erp_orders':
                aware(row['accepted_at']); aware(row['promised_at'])
                if row['completed_at']: aware(row['completed_at'])
                if row['defective'] not in (0,1): raise ValueError()
            else:
                if aware(row['period_start']) >= aware(row['period_end']): raise ValueError()
                if row['forecast'] not in (0,1): raise ValueError()
                if any(not isinstance(row[k],(int,float)) or not math.isfinite(row[k]) or row[k]<0 for k in ('available_hours','occupied_hours')): raise ValueError()
        except (ValueError,TypeError,OverflowError):
            warnings.append('Некорректная доступная строка витрины исключена из расчёта.'); continue
        result.append(row)
    return result


def build(connection, actor, cutoff, generated, source_factory, tasks):
    user = access.load_user(connection,actor)
    if not user or not user.get('level'):
        return [],{},[],None,{}
    metrics, manifests, warnings, stamps = [],{},[],[]
    extras = {}

    def emit(key,label,value,unit,formula,rows,top=None,bottom=None,**data):
        stamp = min((aware(r['as_of']) for r in rows if r.get('as_of')), default=generated)
        stamp_text = iso(stamp)
        if rows:
            stamps.append(stamp)
            if generated-stamp>timedelta(hours=48): warnings.append(label+': источник старше 48 часов.')
        source = source_factory(key,cutoff,generated,rows,stamp_text,label+' · витрина')
        metric = {'key':key,'label':label,'value':value,'unit':unit,'formula':formula,'source':source,
                  'as_of':stamp_text if rows else None,'status':status(key,value),
                  'numerator':top,'denominator':bottom}
        metrics.append(metric)
        manifests[source['id']] = {'metric':metric,'numerator':top,'denominator':bottom,
                                   'evaluated_at':iso(generated),'snapshots':rows,**data}
        return metric

    # Registry counts are observed now, separately from source snapshot periods.
    active = [t for t in tasks if t['status'] not in ('done','cancelled')]
    for key,label,predicate in [('missing_assignee','Задачи без владельца',lambda t:not (t['assignee'] or '').strip()),
                                ('missing_due','Задачи без даты срока',lambda t:not t['due'])]:
        chosen = [t for t in active if predicate(t)]
        source = source_factory(key,cutoff,generated,tasks,iso(generated),label+' · текущий реестр')
        metric = {'key':key,'label':label,'value':len(chosen),'unit':'задач','formula':"count(active AND missing field); текущий реестр",
                  'source':source,'as_of':iso(generated),'status':'warning' if chosen else 'ok'}
        metrics.append(metric); manifests[source['id']] = {'metric':metric,'tasks':[store.task_out(connection,t) for t in chosen]}

    from meetings.decisions import visible as visible_decisions
    controls = visible_decisions(connection,actor,model=True)
    current = [r for r in controls if r['status']=='open']
    def is_late(row):
        try:
            from meetings.management.service import MINSK
            from datetime import date
            return bool(row['due']) and date.fromisoformat(row['due'])<cutoff.astimezone(MINSK).date()
        except ValueError: return False
    for key,label,chosen in [('open_decisions','Открытые решения на контроле',current),
                             ('overdue_decisions','Просроченные решения',[r for r in current if is_late(r)])]:
        last_update = max((r['updated_at'] for r in controls),default=iso(generated))
        source = source_factory(key,cutoff,generated,controls,last_update,label+' · текущий реестр')
        metric = {'key':key,'label':label,'value':len(chosen),'unit':'решений',
                  'formula':"count(status='open'"+(' AND due < cutoff_date' if key=='overdue_decisions' else '')+'); текущий реестр; Europe/Minsk',
                  'source':source,'as_of':iso(generated),'status':'warning' if key=='overdue_decisions' and chosen else 'informational'}
        metrics.append(metric); manifests[source['id']] = {'metric':metric,'decisions':chosen,'evaluated_at':iso(generated)}
    extras['decision_controls'] = [{**row,'source_quote':json.loads(row['source_quote'])} for row in controls]

    interactions = selected(connection,actor,'support_interactions',cutoff,warnings,own='agent_user_id')
    if interactions:
        # A frozen snapshot keeps its own period: advancing the wall clock cannot
        # silently remove its earliest records and alter an old snapshot's ratio.
        anchor = max(aware(r['as_of']) for r in interactions); begin = anchor-timedelta(days=42)
        interactions = [r for r in interactions if begin<=aware(r['opened_at'])<=anchor]
        for key,label,test,formula in [
            ('support_sla','Ответ в SLA',lambda r:r['first_response_seconds']<=r['sla_seconds'],
             'count(first_response_seconds <= sla_seconds) / count(interactions) × 100'),
            ('mary_resolution','Обращения, закрытые Mary',lambda r:r['closed_by']=='mary',
             "count(closed_by = 'mary') / count(interactions) × 100")]:
            top,bottom = sum(test(r) for r in interactions),len(interactions)
            value = round(top/bottom*100,2) if bottom else None
            if not bottom: warnings.append(label+': знаменатель равен нулю.')
            emit(key,label,value,'%',formula+f'; [{iso(begin)}, {iso(anchor)}]',interactions,top,bottom,
                 period_start=iso(begin),period_end=iso(anchor))

    orders = selected(connection,actor,'erp_orders',cutoff,warnings)
    if orders:
        anchor = max(aware(r['as_of']) for r in orders)
        orders = [r for r in orders if aware(r['accepted_at'])<=anchor]
        for key,label,chosen,formula in [
            ('moderation_queue','Очередь модерации',[r for r in orders if r['status']=='moderation'],"count(status = 'moderation')"),
            ('unclaimed_pickup','Невостребованные заказы в ПВЗ',[r for r in orders if r['status']=='unclaimed'],"count(status = 'unclaimed')")]:
            emit(key,label,len(chosen),'заказов',formula,orders,len(chosen),None,orders=chosen)
        completed = [r for r in orders if r['completed_at'] and aware(r['completed_at'])<=anchor]
        late = [r for r in completed if aware(r['completed_at'])>aware(r['promised_at'])]
        reasons = []
        for reason in sorted({r['delay_reason'] or 'не указана' for r in late}):
            count = sum((r['delay_reason'] or 'не указана')==reason for r in late)
            reasons.append({'reason':reason,'count':count,'total_late':len(late),'percent':round(count/len(late)*100,2) if late else None})
        cause_metric = emit('late_order_causes','Просроченные завершённые заказы',len(late),'заказов',
                            'count(completed_at > promised_at); завершённые заказы снимка',orders,len(late),len(completed),reasons=reasons,orders=late)
        extras['delay_reasons'] = [{**reason,'source':cause_metric['source']} for reason in reasons]

    plan = selected(connection,actor,'production_plan',cutoff,warnings)
    forecast = [r for r in plan if r['forecast']==1 and aware(r['period_end'])>cutoff]
    if forecast:
        periods = sorted({r['period_start'] for r in forecast},key=aware)[:4]
        forecast = [r for r in forecast if r['period_start'] in periods]
        points = []
        for period in periods:
            rows = [r for r in forecast if r['period_start']==period]
            from meetings.management.service import json_number
            with localcontext() as decimal_context:
                decimal_context.prec = 64
                top_decimal = sum((Decimal(str(r['occupied_hours'])) for r in rows),Decimal(0))
                bottom_decimal = sum((Decimal(str(r['available_hours'])) for r in rows),Decimal(0))
                value = float(top_decimal/bottom_decimal*100) if bottom_decimal else None
                if value is not None and not math.isfinite(value):
                    value = None; warnings.append('Прогноз мощности: результат вне числового диапазона.')
                if value is not None: value = round(value,2)
                top,bottom = json_number(top_decimal),json_number(bottom_decimal)
            points.append({'period_start':period,'period_end':max((r['period_end'] for r in rows),key=aware),
                           'occupied_hours':top,'available_hours':bottom,'value':value})
        peak = max((p for p in points if p['value'] is not None),key=lambda p:p['value'],default=None)
        if any(not p['available_hours'] for p in points): warnings.append('Прогноз мощности: знаменатель равен нулю у части периодов.')
        emit('capacity_forecast_peak','Пик прогноза мощности',peak['value'] if peak else None,'%',
             'max(sum(occupied_hours) / sum(available_hours) × 100); первые 4 доступных будущих периода',forecast,
             peak['occupied_hours'] if peak else 0,peak['available_hours'] if peak else 0,forecast=points,
             peak_period=peak['period_start'] if peak else None)
        extras['capacity_forecast'] = points
    return metrics,manifests,warnings,min(stamps) if stamps else None,extras
