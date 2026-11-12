// Basic call list/import/analysis; all writes use the existing confirmation dialog.
export function callsUI(h) {
  const {node,makeButton:button,makeInput:input,makeTextarea:textarea,makeSelect:select,request,runAction:run,state,ui,openMeeting,openSource,propose}=h;
  async function render(parent) {
    const identity=state.user?.id,epoch=state.epoch;
    const section=node('section','panel');section.append(node('h1','','Звонки'));parent.append(section);
    const current=()=>state.user?.id===identity && state.epoch===epoch && section.isConnected;
    if(!state.capabilities.includes('calls.read'))return;
    const from=input({label:'Период с (ISO с часовым поясом)',value:new Date(Date.now()-7*86400000).toISOString()}),
      to=input({label:'Период до (ISO с часовым поясом)',value:new Date().toISOString()});
    const list=node('div','');
    async function load(){
      const data=await request('/calls?'+new URLSearchParams({date_from:from.input.value,date_to:to.input.value}));if(!current())return;
      list.replaceChildren(node('p','',`Звонков: ${data.count}; с риском: ${data.risk_calls}; весь чек-лист найден: ${data.checklist_pass_percent==null?'нет данных':data.checklist_pass_percent+'%'}.`));
      if(data.truncated)list.append(node('p','gap-state','Показаны первые500 звонков. Сузьте период.'));
      for(const topic of data.top_topics.slice(0,5))list.append(node('p','',`${topic.title}: ${topic.count}`));
      for(const agent of data.agents)list.append(node('p','task-meta',`Сотрудник ${agent.agent_user_id}: ${agent.calls} звонков, ${agent.risk_calls} с сигналом риска.`));
      if(!data.calls.length)list.append(node('p','','Звонков за период нет.'));
      for(const call of data.calls)list.append(button(`${call.started_at} · Звонок ${call.id}${call.order_no?' · '+call.order_no:''}`,()=>void run(null,()=>detail(call.id))));
    }
    async function detail(id){
      const data=await request('/calls/'+id);if(!current())return;
      const content=node('div','');content.append(node('p','muted-copy',data.notice));
      for(const topic of data.topics)content.append(node('h3','',topic.title));
      function sources(items){for(const s of items || [])content.append(button(`${s.id}: ${s.quote}`,()=>{ui.reset();void openSource('utterance',s.id,s.quote,s);},'citation-chip'));}
      if(!data.speaker_mapping_complete)content.append(node('p','gap-state','Оператор не сопоставлен: проверьте метки говорящих во встрече.'));
      for(const item of data.checklist){content.append(node('p','',`${item.passed?'Найдено':'Не найдено'}: ${item.title}`));sources(item.sources);}
      for(const trigger of data.triggers){content.append(node('p','',`Триггер: ${trigger.text}`));sources(trigger.sources);}
      content.append(node('p','',data.risk.flag?'Есть сигнал риска, нужна проверка человеком.':'Явные сигналы риска по правилам не найдены.'));sources(data.risk.sources);
      content.append(node('p','',`Доля речи оператора: ${data.talk_percent==null?'нет таймкодов':data.talk_percent+'%'}.`));
      if(data.model_topics_enabled) {
        const refined=node('div','');
        const refine=button('Предложить темы моделью',()=>void run(refine,async()=>{
          const result=await request(`/calls/${id}/topics`);if(!current() || !content.isConnected)return;
          refined.replaceChildren(node('p','muted-copy',result.notice || 'Подходящие темы не найдены.'));
          for(const topic of result.suggestions){refined.append(node('p','',topic.title));for(const s of topic.sources)refined.append(button(`${s.id}: ${s.quote}`,()=>{ui.reset();void openSource('utterance',s.id,s.quote,s);},'citation-chip'));}
        }));content.append(refine,refined);
      }
      for(const step of data.next_steps){content.append(node('p','',step.text));sources(step.sources);content.append(button('Предложить поручение',()=>{ui.reset();propose(step.action);}));}
      content.append(button('Открыть расшифровку и запись',()=>{ui.reset();void openMeeting(data.call.meeting_id,'materials');}));
      ui.dialog('Анализ звонка',content,async()=>{},null,'Закрыть');
    }
    const reload=button('Показать за период',()=>void run(reload,load));section.append(from.wrap,to.wrap,reload,list);
    if(state.capabilities.includes('calls.analyze')) {
      const form=node('form','meet-form-grid');
      const people=await request('/calendar/participants');if(!current())return;
      const agent=select(people.participants.map(p=>({value:String(p.id),label:p.name})),String(state.user.id));agent.setAttribute('aria-label','Сотрудник звонка');
      const started=input({label:'Начало звонка (ISO с часовым поясом)',value:new Date().toISOString(),required:true});
      const text=textarea({label:'Расшифровка: Оператор: текст / Клиент: текст',rows:8});text.input.required=true;
      const consent=node('label','record-consent'),box=node('input','');box.type='checkbox';box.required=true;consent.append(box,node('span','','Участники согласны на обработку записи и расшифровки.'));
      const direction=select([{value:'in',label:'Входящий'},{value:'out',label:'Исходящий'}],'in');direction.setAttribute('aria-label','Направление звонка');
      const submit=button('Проверить импорт звонка',null,'secondary-button','submit');
      form.append(node('h2','','Импорт текстового звонка'),agent,direction,started.wrap,text.wrap,consent,submit);
      form.addEventListener('submit',event=>{event.preventDefault();void run(submit,async()=>{
        const segments=text.input.value.split(/\r?\n/).filter(s=>s.trim()).map(line=>{const split=line.indexOf(':');return {speaker:split>0?line.slice(0,split).trim():'Неизвестный',text:split>0?line.slice(split+1).trim():line.trim()};});
        const p=await request('/calls/preview',{method:'POST',body:{direction:direction.value,agent_user_id:Number(agent.value),started_at:started.input.value,consent:box.checked,segments}});if(!current())return;
        const content=node('div','');content.append(node('p','',p.notice),node('p','',`Сотрудник: ${p.preview.agent_name}; реплик: ${p.preview.segments.length}.`));
        for(const s of p.preview.segments)content.append(node('p','',`${s.speaker}: ${s.text}`));
        const key=crypto.randomUUID();ui.dialog('Импорт звонка',content,async()=>{await request('/calls/confirm',{method:'POST',body:{confirmation_id:p.confirmation_id,idempotency_key:key}});if(current()){text.input.value='';to.input.value=new Date(Math.max(Date.now(),Date.parse(to.input.value)||0,(Date.parse(started.input.value)||0)+1)).toISOString();await load();}},()=>request(`/confirmations/${p.confirmation_id}/cancel`,{method:'POST'}));
      });});section.append(form);
    }
    await run(reload,load);
  }
  return {render};
}
