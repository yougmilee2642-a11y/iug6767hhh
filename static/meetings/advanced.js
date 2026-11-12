// Functional report controls in the existing panels; no automatic business actions.
export function advancedUI(h){
  const {node,makeButton:button,makeInput:input,makeSelect:select,request,runAction:run,state,dateLabel:date,sourceButton,dialog}=h;
  const field=(label,control)=>{control.setAttribute('aria-label',label);const wrap=node('label','meeting-field');wrap.append(node('span','field-label',label),control);return wrap;};
  function mount(parent){
    if(!state.capabilities.includes('overview.read'))return;
    const identity=state.user.id,epoch=state.epoch;
    const section=node('details','panel');section.append(node('summary','','Сезонный радар, качество, ПВЗ и контроль результата'));parent.append(section);
    const current=()=>state.user?.id===identity && state.epoch===epoch && section.isConnected;
    const out=node('section','');
    const load=button('Показать расширенный обзор',()=>void run(load,async()=>{
      const data=await request('/advanced-overview');if(!current())return;out.replaceChildren(node('p','muted-copy',data.notice));
      for(const warning of data.warnings)out.append(node('p','access-limited-note',warning));
      out.append(node('h3','','Сезонный прогноз на 6 недель'));
      if(!data.seasonal_forecast.length)out.append(node('p','','Для доступных участков недостаточно сезонной истории.'));
      for(const f of data.seasonal_forecast){
        const card=node('article','panel');card.append(node('h4','',f.section),node('p','muted-copy',f.method),node('p','',`Среднее 3 недель: ${f.moving_average}%; коэффициент декабря: ${f.december_coefficient}.`));
        for(const point of f.points)card.append(node('p','',`${date(point.start)} — ${date(point.end)}: ${point.value}%; дефицит мощности: ${point.deficit_percent}%.`));
        card.append(sourceButton(f.source));
        if(state.capabilities.includes('meetings.create'))card.append(button('Подготовить встречу по прогнозу',()=>h.propose({kind:'meeting',text:'Проверить прогноз мощности: '+f.section,basis:{kind:'insight',id:f.source.id},calendar_hint:{participant_ids:f.owner_user_id?[f.owner_user_id]:[],range_start:null,range_end:null,duration_minutes:30,timezone:'Europe/Minsk'}}),'secondary-button'));
        out.append(card);
      }
      out.append(node('h3','','Радар качества Premium'));
      const labels={defective_premium_orders:'Заказы Premium с браком',support_defect_cases:'Обращения о браке Premium',defect_calls:'Звонки о браке/переплёте',controlled_decisions:'Решения по качеству на контроле',overdue_tasks:'Просроченные поручения по качеству'};
      for(const [key,value] of Object.entries(data.quality.counts))out.append(node('p','',`${labels[key]}: ${value==null?'нет доступа к источнику':value}`));
      out.append(sourceButton(data.quality.source),node('h3','','Срок хранения в ПВЗ истекает за ≤ 2 дня'));
      if(data.partial)out.append(node('p','access-limited-note','Показаны первые 100 заказов; откройте исходную витрину для полного списка.'));
      if(!data.pickup_orders.length)out.append(node('p','','В доступной витрине заказов по этому условию нет.'));
      for(const order of data.pickup_orders){const card=node('article','panel');card.append(node('p','',`${order.order_no}: до ${date(order.expires_at)}`),sourceButton(order.source));if(state.capabilities.includes('protocol.confirm'))card.append(button('Задача: напомнить клиенту',()=>h.propose(order.proposed_action),'secondary-button'));out.append(card);}
    }));section.append(load,out);
    const weekly=node('form','meet-form-grid');const end=input({label:'Конец недели для дайджеста',type:'date',value:new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Minsk',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date())});
    const submit=button('Предпросмотр недельного дайджеста',null,'secondary-button','submit'),letters=node('div','');weekly.append(end.wrap,submit);
    weekly.addEventListener('submit',event=>{event.preventDefault();void run(submit,async()=>{
      const p=await request('/briefing/weekly/preview',{method:'POST',body:{period_end:end.input.value}});if(!current())return;
      const content=node('div');content.append(node('p','',p.preview.notice));for(const claim of p.preview.claims){content.append(node('p','',claim.text));for(const s of claim.sources)content.append(sourceButton(s));}
      if(p.preview.partial)content.append(node('p','access-limited-note','Дайджест ограничен первыми 100 пунктами.'));
      const key=crypto.randomUUID();dialog('Подтвердить личный недельный дайджест',content,async()=>{
        const result=await request('/briefing/weekly/confirm',{method:'POST',body:{confirmation_id:p.confirmation_id,idempotency_key:key}});if(!current())return;
        const link=node('a','text-button','Скачать письмо .eml');link.href=result.path;link.download='';letters.replaceChildren(node('p','','Письмо в вашей локальной очереди. Внешней отправки нет.'),link);
      },()=>request(`/confirmations/${p.confirmation_id}/cancel`,{method:'POST'}));
    });});section.append(weekly,letters);
    const effects=node('section','');const show=button('Проверки результата решений',()=>void run(show,async()=>{
      const result=await request('/effect-checks');if(!current())return;effects.replaceChildren();
      const statuses={scheduled:'проверка запланирована',waiting_data:'ожидается свежий снимок',evaluated:'сравнение выполнено'};
      for(const row of result.checks){const card=node('article','panel');card.append(node('p','',`Проверка №${row.id}: ${statuses[row.status] || 'требует проверки'}; дата ${date(row.check_at)}.`));if(row.result)card.append(node('p','',row.result.notice));if(row.result?.after!=null)card.append(node('p','',`Было ${row.result.before}%, стало ${row.result.after}%; цель ${row.result.target}%; ${row.result.reached?'числовая цель достигнута':'числовая цель не достигнута'}.`));effects.append(card);}
      if(!result.checks.length)effects.append(node('p','','Назначенных вами проверок нет.'));
      if(!state.capabilities.includes('protocol.confirm'))return;
      const records=await request('/decisions');if(!current())return;
      const form=node('form','meet-form-grid');const decision=select([{value:'',label:'Выберите решение на контроле'},...records.decisions.map(d=>({value:d.protocol_item_id,label:d.text}))]);
      const metric=select([{value:'capacity_utilization',label:'Загрузка мощности'},{value:'on_time_orders',label:'Заказы в срок'},{value:'defect_rate',label:'Брак'}]);
      const target=input({label:'Цель, %',type:'number',value:100});target.input.min='0';target.input.max='1000';target.input.step='0.1';
      const direction=select([{value:'le',label:'Не больше цели'},{value:'ge',label:'Не меньше цели'}]);const days=input({label:'Проверить через дней',type:'number',value:7});days.input.min='1';days.input.max='90';
      const prepare=button('Предпросмотр контроля результата',null,'secondary-button','submit');form.append(field('Решение с подтверждённым источником',decision),field('Метрика отдела',metric),target.wrap,field('Условие цели',direction),days.wrap,prepare);
      form.addEventListener('submit',event=>{event.preventDefault();void run(prepare,async()=>{
        const p=await request('/effect-checks/preview',{method:'POST',body:{protocol_item_id:Number(decision.value),metric_key:metric.value,target_value:Number(target.input.value),direction:direction.value,days:Number(days.input.value)}});if(!current())return;
        const content=node('div');content.append(node('p','',p.notice),node('p','',`Исходное значение: ${p.preview.baseline.value}%; снимок ${date(p.preview.baseline.as_of)}; проверка ${date(p.preview.check_at)}.`));for(const warning of p.preview.baseline.warnings)content.append(node('p','access-limited-note',warning));
        const key=crypto.randomUUID();dialog('Подтвердить проверку метрики',content,async()=>{await request('/effect-checks/confirm',{method:'POST',body:{confirmation_id:p.confirmation_id,idempotency_key:key}});if(current())effects.append(node('p','','Проверка назначена. Для результата нужен свежий снимок после настройки контроля.'));},()=>request(`/confirmations/${p.confirmation_id}/cancel`,{method:'POST'}));
      });});effects.append(form);
    }));section.append(show,effects);
  }
  return {mount};
}
