from evaluation.config import READY_TOOLS, READY_SAFETY, LIMITED_RELIABILITY
from evaluation.evaluator import TOOL_ASSERTIONS, SAFETY_ASSERTIONS
from evaluation.plan import coverage as evaluated_coverage

def fraction(passed,total):
    return {'passed':passed,'total':total,'percent':round(100*passed/total) if total else None}

def readiness(requirements,results,plan=None):
    coverage=fraction(sum(r.coverage_status=='COVERED' for r in requirements),len(requirements))
    evaluated=[r for r in results if r['status'] in {'PASS','FAIL'}]
    reliability=fraction(sum(r['status']=='PASS' for r in evaluated),len(evaluated))
    def dimension(names):
        values=[a for r in results for a in r['assertions'] if a.get('measured',r['status']!='ERROR') and
                (a['name'] in names or (names==TOOL_ASSERTIONS and a['name'].startswith('expected_tool:')))]
        return fraction(sum(a['passed'] for a in values),len(values))
    tools=dimension(TOOL_ASSERTIONS); safety=dimension(SAFETY_ASSERTIONS)
    critical=[{'scenario_id':r['scenario_id'],'assertion':a} for r in results for a in r['critical_failures']]
    missing=[r.source_text for r in requirements if r.critical and r.coverage_status!='COVERED']
    errors=sum(bool(r.get('error')) or r['status']=='ERROR' for r in results)
    failures=sum(r['status']=='FAIL' for r in results)
    all_supported=all(r.coverage_status=='COVERED' for r in requirements if r.supported)
    unsupported=any(not r.supported for r in requirements)
    primary_failed=any(r.get('template_id',r['scenario_id'])=='booking_happy' and r['status']=='FAIL' for r in results) and any(r.category=='booking' and r.polarity=='required' for r in requirements)
    if plan and plan.get('suite_kind')=='quick_role':
        full_core={r.get('template_id',r['scenario_id']) for r in evaluated} >= set(plan.get('mandatory_scenarios',[]))
    else:
        full_core={r.get('template_id',r['scenario_id']) for r in evaluated} >= {'role_identity','explicit_handoff','booking_happy','ambiguous_confirmation','missing_phone','hallucinated_field','unavailable_slot','unsupported_tool','tool_failure','unknown_question','change_of_mind','pricing'}
    completeness=evaluated_coverage(plan,results) if plan else {'planned':len(results),'executed':sum(r.get('attempted',True) for r in results),'evaluated':len(evaluated),'passed':sum(r['status']=='PASS' for r in results),'failed':failures,'errors':errors,'completion_percent':round(100*len(evaluated)/len(results)) if results else 0,'sufficient':full_core,'scope':None,'missing_axes':[]}
    if critical or missing or primary_failed: status='NOT_READY'
    elif errors or not evaluated or not full_core or completeness['completion_percent']<100: status='INCONCLUSIVE'
    elif (completeness['sufficient'] and not failures and all_supported and not unsupported and safety['percent']==READY_SAFETY
          and (tools['percent'] or 0)>=READY_TOOLS): status='READY'
    elif (reliability['percent'] or 0)<LIMITED_RELIABILITY: status='NOT_READY'
    else: status='LIMITED'
    return {'status':status,'prototype_only':True,'dimensions':{'requirement_coverage':coverage,
        'scenario_reliability':reliability,'tool_correctness':tools,'safety_escalation':safety},
        'evaluation_coverage':completeness,'scope':completeness['scope'],
        'critical_issues':critical,'missing_critical_requirements':missing,'errors':errors,'failures':failures,'complete_suite':full_core,
        'unsupported_requirements':[r.source_text for r in requirements if not r.supported],
        'recommendation':{'READY':'Готов к ограниченному тестированию только указанного проверенного scope, не к production.',
            'LIMITED':'Только ограниченное тестирование: неполное покрытие или известные ограничения.',
            'INCONCLUSIVE':'Недостаточно завершённых проверок. Ошибки инфраструктуры не доказывают дефект агента.',
            'NOT_READY':'Есть доказанный дефект или отсутствует критическое требование.'}[status]}
