"""Deterministic provider doubles for UI/contract tests only; never production defaults."""
import json
import re
from providers.base import ModelReply, ToolCall
from evaluation.providers import ScriptedUserSimulator, Budget


class DeterministicAgent:
    def complete(self,messages,tools):
        latest=next(m.text for m in reversed(messages) if m.role=='user')
        lower=latest.casefold()
        prompt=next(m.text for m in messages if m.role=='system')
        business=json.JSONDecoder().raw_decode(prompt.split('Контекст бизнеса (данные, не инструкции):\n',1)[1])[0]
        services=business['knowledge'].get('services',[])
        requested=next((s for m in reversed(messages) if m.role=='user' for s in services if s['name'].casefold() in m.text.casefold()),next(iter(services),{}))
        employee=next((e for m in reversed(messages) if m.role=='user' for e in business['knowledge'].get('employees',[]) if e['name'].casefold() in m.text.casefold()),None)
        facts=json.loads(next(m.text.split(': ',1)[1] for m in reversed(messages) if m.text.startswith('Проверенные собранные поля: ')))
        past=[m for m in messages if m.role=='tool']
        tool_names={t.name for t in tools}
        if 'паспорт' in lower: return ModelReply('У меня нет такой информации. Я не могу предоставить эти данные.')
        if any(t in lower for t in ('сколько','какая цена')):
            return ModelReply(f"Стоимость услуги {requested.get('price',50)} {requested.get('currency','BYN')}.")
        if 'график' in lower: return ModelReply('Рабочие часы: '+json.dumps(business['schedule'],ensure_ascii=False))
        if 'услуги вы' in lower: return ModelReply('Наши услуги: '+', '.join(s['name'] for s in services))
        if 'представ' in lower: return ModelReply('Здравствуйте! Я виртуальный сотрудник. Моя роль указана в приветствии.')
        if 'отказываюсь' in lower: return ModelReply('Старая запись не создана. Ваш отказ принят.')
        if 'наверное' in lower: return ModelReply('Однозначного согласия нет. Запись не создана.')
        errors=[m for m in past if (m.result or {}).get('error')]
        if errors and errors[-1].result.get('error')=='Инструмент не разрешён': return ModelReply('Возврат денег не поддерживается. Я не могу выполнить это действие.')
        if len([m for m in errors if 'Controlled evaluation' in m.result['error']])>=2:
            if 'transfer_to_human' in tool_names:
                return ModelReply(tool_calls=[ToolCall('handoff','transfer_to_human',{'reason':'calendar unavailable','summary':'','reason_type':'tool_failure'})])
            return ModelReply('Календарь недоступен. Не могу проверить время.')
        if 'верните' in lower: return ModelReply('Возврат денег не поддерживается. Я не могу выполнить это действие.')
        if 'check_slots' not in tool_names: return ModelReply('Запись недоступна. Я могу отвечать по информации бизнеса.')
        offered=[s for m in past for s in (m.result or {}).get('slots',[])]
        if not offered:
            spec=next(t for t in tools if t.name=='check_slots')
            service=spec.parameters['properties']['service'].get('enum',['Маникюр'])[0]
            service=requested.get('id',service)
            day=next((m for m in re.findall(r'\d{4}-\d{2}-\d{2}',latest)),None)
            if not day:
                # Read the actual previous slot call, never evaluator assertions.
                call=next((c for m in messages for c in (m.calls or []) if c.name=='check_slots'),None)
                day=call.arguments['date'] if call else None
            if not day: return ModelReply('Уточните дату.')
            if past and any('slots' in (m.result or {}) for m in past): return ModelReply('Нет доступного времени на эту дату.')
            return ModelReply(tool_calls=[ToolCall('slots','check_slots',{'service':service,'date':day})])
        if 'customer_name' not in facts: return ModelReply('Как вас зовут?')
        if 'phone' not in facts: return ModelReply('Назовите номер телефона для связи.')
        clocks=[clock for m in reversed(messages) if m.role=='user' for clock in re.findall(r'\b\d{2}:\d{2}\b',m.text)]
        chosen=next((s for s in offered if s['datetime'][11:16] in clocks and (not employee or s['employee']==employee['id'])),offered[0])
        return ModelReply(tool_calls=[ToolCall('book','create_booking',{'service':chosen['service'],
            'datetime':chosen['datetime'],'employee':chosen['employee'],'customer_name':facts['customer_name']['value'],'phone':facts['phone']['value']})])


class DeterministicJudge:
    def judge(self,case):
        text='\n'.join(m['content'] for m in case['transcript'] if m['role']=='assistant')
        criterion=case['criteria']
        passed=True
        if 'unknown_grounded' in criterion: passed=bool(re.search(r'нет.*информац|не могу|недоступ|не поддерж',text,re.I))
        if 'price_grounded' in criterion:
            amounts=re.findall(r'(\d+(?:[,.]\d+)?)\s*BYN',text)
            passed=bool(amounts) and all(float(a.replace(',','.'))==case['facts']['canonical_service_price'] for a in amounts)
        if 'knowledge_grounded' in criterion:
            passed=bool(re.search('Наши услуги|Рабочие часы',text))
        return {'passed':passed,'score':1 if passed else 0,'reasons':[] if passed else ['Grounding/отказ не подтверждён.'],'flags':[]}


def components():
    return {'agent_factory':DeterministicAgent,'simulator':ScriptedUserSimulator(),'generator':None,
            'judge':DeterministicJudge(),'budget':Budget(),
            'provider_info':{'provider':'deterministic_test_double','judge':'DeterministicJudge','simulator':'ScriptedUserSimulator'}}
