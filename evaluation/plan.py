"""Persisted bounded coverage policy; no resampling when reading history."""
import random
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from evaluation.scenarios import trusted_scenarios, booking_context, service_context
from evaluation.models import EvaluationScenario, ClientPersona
from evaluation.config import MAX_REQUESTS, MAX_TURNS

def build_plan(business, config, requirements, count, seed, mode):
    rng = random.Random(seed)
    services = config.business.knowledge.get('services', [])
    employees = config.business.knowledge.get('employees', [])
    selected = services if len(services) <= 8 else sorted(rng.sample(services, min(5,len(services))), key=lambda s:s['id'])
    selected_employees = employees if len(employees)<=8 else sorted(rng.sample(employees,5),key=lambda e:e['id'])
    booking = any(r.category=='booking' and r.polarity=='required' for r in requirements)
    if not booking: selected_employees = []
    pricing = any(r.category=='pricing' and r.polarity=='required' for r in requirements)
    cases = trusted_scenarios(business, config, requirements)
    desired = []
    def mark(case, context, operation, suffix=None, boundary='ordinary', profile=''):
        case = case.model_copy(deep=True)
        if suffix: case.id = case.template_id + ':' + suffix
        case.initial_context = context
        case.client.known_data = {'service':context['service_name']} if operation=='pricing' else case.client.known_data
        if operation=='booking':
            case.client.known_data.update(service=context['service_name'], time=context['clock'], employee=context['employee_id'])
        name = next((e['name'] for e in employees if e['id']==context.get('employee_id')), '')
        case.title += ' · '+context['service_name']+((' · '+name+' · '+boundary+(' · профиль '+profile if profile else '')) if operation=='booking' else '')
        case.client.opening = (f"Хочу записаться на {context['service_name']} {context['day']} в {context['clock']} к сотруднику {name}."
                              if operation=='booking' else f"Сколько стоит {context['service_name']}?")
        case.coverage_axes = {'operation':operation,'service':context['service_id']}
        if operation=='booking': case.coverage_axes.update(employee=context['employee_id'], boundary=boundary, schedule_profile=profile)
        return case
    profiles = {}
    for day, windows in config.business.schedule.items():
        if windows: profiles.setdefault(str(windows), int(day))
    profiles = list(profiles.values())
    happy, price = cases[2], cases[11]
    for index, service in enumerate(selected):
        for operation,base in [('booking',happy),('pricing',price)]:
            if not (booking if operation=='booking' else pricing): continue
            desired.append({'axis':'service_'+operation, 'entity':service['id']})
            context = (booking_context(business,config,service['id']) if operation=='booking'
                       else service_context(business,config,service['id']))
            if not context: continue  # Missing knowledge remains explicitly uncovered, never a fabricated slot.
            new = mark(base, context, operation, service['id'],
                       profile=str(next((d for d in profiles if config.business.schedule[str(d)]==config.business.schedule.get(str(date.fromisoformat(context['day']).weekday()))),'')) if operation=='booking' else '')
            if index==0: cases[2 if operation=='booking' else 11] = new
            else: cases.append(new)
    if booking and selected:
        seen = {s.coverage_axes.get('employee') for s in cases}
        for employee in selected_employees:
            eligible = next((s for s in selected if employee['id'] in s['employees']),None)
            desired.append({'axis':'employee','entity':employee['id']})
            if eligible and employee['id'] not in seen:
                context=booking_context(business,config,eligible['id'],employee['id'])
                if context: cases.append(mark(happy,context,'booking','employee_'+employee['id'])); seen.add(employee['id'])
        for profile in profiles:
            desired.append({'axis':'schedule_profile','entity':str(profile)})
            context=booking_context(business,config,selected[0]['id'],weekday=profile)
            if context: cases.append(mark(happy,context,'booking','schedule_'+str(profile),profile=str(profile)))
        context=booking_context(business,config,selected[0]['id'],boundary='near_closing')
        desired += [{'axis':'boundary','entity':'near_closing'}, {'axis':'boundary','entity':'unavailable'}]
        if context: cases.append(mark(happy,context,'booking','near_closing',boundary='near_closing'))
        cases[6].coverage_axes={'boundary':'unavailable'}
        closed=next((int(d) for d in map(str,range(7)) if not config.business.schedule.get(d)),None)
        desired.append({'axis':'boundary','entity':'closed' if closed is not None else 'outside_hours'})
        context=booking_context(business,config,selected[0]['id'])
        if context:
            if closed is not None:
                today=datetime.now(ZoneInfo(config.business.timezone)).date()
                context['day']=(today+timedelta(days=(closed-today.weekday())%7 or 7)).isoformat()
            context['clock']='00:00';context['datetime']=datetime.combine(date.fromisoformat(context['day']),datetime.min.time(),ZoneInfo(config.business.timezone)).isoformat()
            case=mark(happy,context,'booking','closed',boundary='closed' if closed is not None else 'outside_hours')
            case.assertions=['no_unconfirmed_write','user_provenance','allowed_tools','no_booking','slots_grounded']
            case.expected_state=None;case.expected_tools=['check_slots'];case.client.behavior='one_turn'
            case.expected_behavior='Не бронировать запрошенное нерабочее время. Слоты должны соответствовать расписанию.'
            case.title='Нерабочее время · '+context['service_name']
            cases.append(case)
    seen_requirements=set()
    for requirement in requirements:
        if requirement.polarity=='required' and requirement.category in {'faq','opening_hours'}:
            if requirement.category in seen_requirements: continue
            seen_requirements.add(requirement.category)
            question = 'Какие услуги вы предлагаете?' if requirement.category=='faq' else 'Какой у вас график работы?'
            cases.append(EvaluationScenario(id='requirement:'+requirement.category,template_id=requirement.category,
                requirement_id=requirement.id,scenario_type='HAPPY_PATH',category=requirement.category,title=question,
                expected_behavior='Ответить по фактам сохранённого бизнес-каталога, не отказывать при наличии информации.',
                client=ClientPersona(opening=question,goal=question,behavior='one_turn'), assertions=['knowledge_grounded','allowed_tools'],
                coverage_axes={'requirement':requirement.id}))
            desired.append({'axis':'requirement','entity':requirement.id})
    # Mandatory coverage wins over optional language variation. Cap is explicit, never hidden.
    all_cases = cases
    cases = all_cases[:count]
    for case in cases:
        if not case.template_id: case.template_id=case.id
    per_case=MAX_TURNS*6+(MAX_TURNS-1 if mode=='STANDARD' else 0)
    theoretical=6+len(cases)*per_case*2 + sum(bool(set(c.assertions)&{'role_identity','price_grounded','unknown_grounded','failure_handled','knowledge_grounded'}) for c in cases)
    variants = min(count-len(cases), 4) if mode=='STANDARD' else 0
    return {'version':'coverage-2','mode':mode,'seed':seed,'requested_count':count,
        'policy':{'small_catalog_limit':8,'large_sample':5,'services':'full' if len(services)<=8 else 'sampled',
            'employees':'full' if len(employees)<=8 else 'sampled','case_cap':count},
        'selected_services':[s['id'] for s in selected], 'selected_employees':[e['id'] for e in selected_employees],
        'selected_service_names':[s['name'] for s in selected], 'selected_employee_names':[e['name'] for e in selected_employees],
        'catalog_services':len(services),'catalog_employees':len(employees),'desired_axes':desired,
        'excluded_scenarios':[c.id for c in all_cases[count:]], 'optional_variants':variants,
        'max_calls_estimate':min(MAX_REQUESTS,theoretical+variants*(per_case+1)+(2 if variants else 0)),
        'theoretical_calls_upper_bound':theoretical+variants*(per_case+1)+(2 if variants else 0),
        'request_budget':MAX_REQUESTS,'scenarios':[s.model_dump() for s in cases]}

def coverage(plan, results):
    completed = {r['scenario_id']:r for r in results if r['status'] in {'PASS','FAIL'} and r.get('agent_completed',True)}
    actual=set()
    for case in plan['scenarios']:
        result=completed.get(case['id'])
        if not result: continue
        axes=case['coverage_axes']
        if axes.get('operation'): actual.add(('service_'+axes['operation'], axes['service']))
        if axes.get('scenario'): actual.add(('scenario', axes['scenario']))
        for axis in ('employee','boundary','schedule_profile','requirement'):
            if axes.get(axis): actual.add((axis,axes[axis]))
    missing=[a for a in plan['desired_axes'] if (a['axis'],a['entity']) not in actual]
    evaluated=sum(r['status'] in {'PASS','FAIL'} for r in results)
    return {'planned':len(plan['scenarios'])+plan['optional_variants'],
        'executed':sum(r.get('attempted',True) for r in results),'evaluated':evaluated,
        'passed':sum(r['status']=='PASS' for r in results),'failed':sum(r['status']=='FAIL' for r in results),
        'errors':sum(r['status']=='ERROR' for r in results),'completion_percent':round(100*evaluated/(len(plan['scenarios'])+plan['optional_variants'])) if plan['scenarios'] else 0,
        'covered_axes':[{'axis':a,'entity':e} for a,e in sorted(actual)], 'missing_axes':missing,
        'sufficient':not missing and not plan['excluded_scenarios'],
        'scope':{'services':plan['selected_services'],'employees':plan['selected_employees'],'policy':plan['policy']}}
