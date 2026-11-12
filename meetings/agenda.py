"""Live, scoped context for the next agenda. Never confirms a proposed action."""
from datetime import datetime,timezone
import json
from meetings import access,preparation,store
from meetings.auth import has_capability


def context(c,user,meeting):
    extra,_=preparation.department_context(c,user,meeting,[])
    from meetings.management.domain import status
    deviations=[]
    for metric in extra.get('kpi_context',{}).get('metrics',[]):
        if status(metric['key'],metric['value']) in ('warning','critical'):
            deviations.append({'kind':'metric','text':f"{metric['label']}: {metric['value']} {metric['unit']}.",
                               'sources':metric['sources'],'as_of':extra['kpi_context']['as_of']})
    decisions=[]
    from meetings.decisions import visible,basis
    today=datetime.now(timezone.utc).astimezone(store.zone(store.DISPLAY_ZONE)).date().isoformat()
    for control in visible(c,user['id'],model=True):
        if control['department_id']!=meeting['department_id'] or control['status']!='open' or not control['due'] or control['due']>=today:continue
        item,quote,_=basis(c,user,control['protocol_item_id'])
        if not quote:continue
        decisions.append({'kind':'decision','text':'Просрочено решение: '+item['text'],'due':control['due'],
            'sources':[{'kind':'utterance','id':quote['utterance_id'],'title':'Реплика решения','quote':quote['text'],'source_at':control['updated_at']}]})
    series_tasks=[]
    if meeting['series_id']:
        scope,args=access.predicate(c,user['id'],'meeting','m',model=True)
        for task in c.execute("SELECT t.* FROM tasks t JOIN meetings m ON m.id=t.meeting_id WHERE m.series_id=? "
            "AND t.meeting_id!=? AND t.status NOT IN ('done','cancelled') AND "+scope+' ORDER BY t.id LIMIT 50',
            [meeting['series_id'],meeting['id'],*args]):
            series_tasks.append({'kind':'task','text':'Незакрытая задача серии: '+task['text'],
                'sources':[{'kind':'task','id':'T'+str(task['id']),'title':task['text'],'source_at':task['updated_at']}]})
    problems=[];warnings=extra.get('kpi_context',{}).get('warnings',[])
    if has_capability(user,'calls.read'):
        from meetings.calls import week_problems
        result=week_problems(c,user,meeting['department_id'])
        problems=[{'kind':'call','text':p['text'],'sources':p['sources']} for p in result['problems']]
        if result['truncated']:warnings.append('Проблемы звонков рассчитаны по первым500 доступным записям.')
    return {'items':[*series_tasks,*deviations,*decisions,*problems], 'warnings':warnings,'generated_at':store.now(),
            'notice':'Контекст виден только вам по текущим правам. Добавление в локальный проект повестки не рассылает данные другим участникам.'}
