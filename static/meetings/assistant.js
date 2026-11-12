// Chat uses server-verified claims. The model never controls DOM or confirm buttons.
export function assistantUI(h) {
  const {node,makeButton:button,makeTextarea:textarea,makeSelect:select,makeInput:input,request,runAction:run,state,ui,dateLabel:date,openMeeting,openSource}=h;
  let owner=null,conversation=null,messages=[],draft='';
  const reset=()=>{owner=null;conversation=null;messages=[];draft='';};
  const field=(label,control)=>{control.setAttribute('aria-label',label);const wrap=node('label','meeting-field');wrap.append(node('span','field-label',label),control);return wrap;};
  async function action(card,proposal) {
    const form=node('form','meet-form-grid');
    const text=textarea({label:proposal.kind==='meeting'?'Тема встречи':'Текст поручения',value:proposal.text,rows:3});
    const meeting=select([{value:'',label:'Выберите встречу-основание'},...state.meetings.map(m=>({value:m.id,label:m.title}))],proposal.meeting_id || '');
    const person=select([{value:'',label:'Требует уточнения'},...state.users.filter(p=>p.active!==0 && !['admin','auditor'].includes(p.level)).map(p=>({value:p.id,label:p.name}))],proposal.assignee_user_id || '');
    const due=input({label:'Срок поручения',type:'date',value:proposal.due || ''});
    form.append(text.wrap);
    let taskId,status;
    if(proposal.kind==='task_change'){
      taskId=input({label:'Номер изменяемого поручения',type:'number',value:proposal.task_id || ''});
      status=select([{value:'',label:'Выберите новый статус'},...Object.entries({open:'Открыто',in_progress:'В работе',blocked:'Заблокировано',done:'Готово',cancelled:'Отменено'}).map(([value,label])=>({value,label}))],proposal.status || '');
      form.append(taskId.wrap,field('Новый статус',status));
    }
    if(proposal.kind==='task')form.append(field('Встреча-основание',meeting),field('Ответственный',person),due.wrap);
    if(proposal.requires_clarification?.length)form.append(node('p','gap-state','Уточните: '+proposal.requires_clarification.join(', ')+'.'));
    if(proposal.calendar_hint)form.append(node('p','muted-copy',`Календарь: ${proposal.calendar_hint.range_start?date(proposal.calendar_hint.range_start):'дата требует уточнения'}; участников для подбора: ${proposal.calendar_hint.participant_ids.length}. Это параметры поиска, встреча ещё не назначена.`));
    const preview=button('Предпросмотр',null,'secondary-button','submit');form.append(preview);
    form.addEventListener('submit',event=>{event.preventDefault();void run(preview,async()=>{
      const data={kind:proposal.kind,text:text.input.value,meeting_id:meeting.value?Number(meeting.value):null,
        assignee_user_id:person.value?Number(person.value):null,due:due.input.value || null,task_id:taskId?.input.value?Number(taskId.input.value):null,status:status?.value || null,basis:proposal.basis || null,calendar_hint:proposal.calendar_hint || null};
      const result=await request('/assistant/actions/preview',{method:'POST',body:data});
      const content=node('div');content.append(node('p','',result.preview.text),node('p','',result.preview.origin),node('p','',`Срок: ${result.preview.due || 'требует уточнения'}`));
      if(result.preview.status_after)content.append(node('p','',`Новый статус: ${result.preview.status_after}`));
      if(result.preview._basis_source)content.append(button('Открыть источник действия',()=>void openSource(result.preview.basis.kind,result.preview.basis.id),'citation-chip'));
      if(result.preview._participant_names?.length)content.append(node('p','','Участники проекта: '+result.preview._participant_names.join(', ')));
      const key=crypto.randomUUID();
      ui.dialog('Подтвердить действие ассистента',content,async()=>{
        const saved=await request('/assistant/actions/confirm',{method:'POST',body:{confirmation_id:result.confirmation_id,idempotency_key:key}});
        card.replaceChildren(node('p','',saved.notice),button('Открыть встречу',()=>void openMeeting(saved.meeting_id),'secondary-button'));
        if(saved.calendar_hint)card.append(button('Подобрать время по параметрам',()=>void run(null,async()=>{
          if(await ui.seedCalendar(saved.meeting_id,saved.calendar_hint))await openMeeting(saved.meeting_id,'prep');
        })));
      },()=>request(`/confirmations/${result.confirmation_id}/cancel`,{method:'POST'}));
    });});
    card.append(form);
  }
  function render(parent) {
    if(owner!==state.user.id){reset();owner=state.user.id;}
    const epoch=state.epoch;
    parent.append(node('h1','','Спросить Фокус'));
    const form=node('form','panel meet-form-grid');
    const scope=select([{value:'',label:'Все доступные источники'},...state.meetings.map(m=>({value:m.id,label:m.title}))]);
    const text=textarea({label:'Сообщение ассистенту',value:draft,rows:3,required:true});text.input.maxLength=2000;
    text.input.addEventListener('input',()=>{draft=text.input.value;});
    const send=button('Спросить Фокус',null,'primary-button','submit');
    const list=node('section','panel');list.setAttribute('aria-label','Ответы ассистента');
    const draw=()=>{
      list.replaceChildren();
      for(const message of messages){
        const card=node('article','panel');card.append(node('p','task-meta',message.question || ''),node('p','task-meta',date(message.generated_at)));
        if(message.status==='action_proposed')void action(card,message.proposed_action);
        else if(message.claims?.length)for(const claim of message.claims){
          card.append(node('p','',claim.text));
          for(const source of claim.sources || [])card.append(button(`${source.title} · ${date(source.source_at)}`,()=>void openSource(source.kind,source.id,source.quote,source),'citation-chip'));
        }else card.append(node('p','',message.answer));
        for(const warning of message.warnings || [])card.append(node('p','access-limited-note',warning));
        if(message.message_id)card.append(ui.feedback('assistant_message',message.message_id));
        list.append(card);
      }
    };
    form.addEventListener('submit',event=>{event.preventDefault();void run(send,async()=>{
      const question=text.input.value;
      const result=await request('/assistant/ask',{method:'POST',body:{text:question,meeting_id:scope.value?Number(scope.value):null,conversation_id:conversation}});
      if(epoch!==state.epoch || !parent.isConnected)return;
      conversation=result.conversation_id;messages.push({...result,question});draft='';text.input.value='';draw();
    });});
    const hints=node('div','inline-actions');
    for(const hint of ['Что решили по Premium?','Что просрочено?','Брифинг','Найди время для встречи с логистикой'])hints.append(button(hint,()=>{text.input.value=hint;draft=hint;text.input.focus();},'secondary-button'));
    const history=button('Мои диалоги',()=>void run(history,async()=>{
      const data=await request('/assistant/conversations');if(epoch!==state.epoch || !parent.isConnected)return;
      const choices=node('div');
      for(const item of data.conversations)choices.append(button(date(item.created_at),()=>void run(null,async()=>{
        const result=await request(`/assistant/conversations/${item.id}`);if(epoch!==state.epoch || !parent.isConnected)return;
        conversation=item.id;messages=result.messages;draw();choices.remove();
      }),'secondary-button'));
      form.append(choices);
    }),'secondary-button');
    const fresh=button('Новый диалог',()=>{conversation=null;messages=[];draw();},'secondary-button');
    form.append(field('Контекст ассистента',scope),hints,text.wrap,send,history,fresh);parent.append(form,list);draw();
  }
  function propose(proposal){if(owner!==state.user.id)reset();owner=state.user.id;messages.push({status:'action_proposed',proposed_action:proposal,generated_at:new Date().toISOString()});}
  return {render,reset,propose};
}
