export function operationsUI(h) {
  const {node,makeButton:button,makeInput:input,request,runAction:run,state,ui,dateLabel:date,openMeeting,navigate}=h;
  function preview(title,result,confirm){
    const content=node('div');
    if(result.notice)content.append(node('p','',result.notice));
    const labels={audio_after_confirm:'Удаление аудио после подтверждения',transcript_days:'Расшифровки, дней',chat_days:'Ответы, дней',audit_days:'Журнал, дней',reminder_minutes:'Напоминание, минут',email_enabled:'E-mail',telegram_enabled:'Telegram',bitrix_enabled:'Битрикс24',documents:'Документы',meetings:'Встречи',tasks:'Поручения',utterances:'Реплики',user_id:'Пользователь',request_id:'Запрос'};
    for(const [name,value] of Object.entries(result.preview || {})){
      if(name==='delivery'){
        for(const [channel,info] of Object.entries(value || {}))content.append(node('p','',`${channel==='telegram'?'Telegram':'Битрикс24'}: ${info.enabled?'получатель '+info.recipient+'; ссылка '+info.url:'только локальная очередь; отправка не настроена'}`));
      }else content.append(node('p','',`${labels[name] || name}: ${typeof value==='boolean'?(value?'да':'нет'):typeof value==='object'?JSON.stringify(value):value}`));
    }
    const key=crypto.randomUUID();
    ui.dialog(title,content,()=>confirm({confirmation_id:result.confirmation_id,idempotency_key:key}),()=>request(`/confirmations/${result.confirmation_id}/cancel`,{method:'POST'}));
  }
  async function notifications(parent){
    const epoch=state.epoch;parent.append(node('h1','','Уведомления'));
    const data=await request('/notifications');if(epoch!==state.epoch || !parent.isConnected)return;
    const settings=node('form','panel meet-form-grid');const controls={};
    for(const [name,label] of [['email','E-mail'],['telegram','Telegram'],['bitrix','Битрикс24']]){
      const field=input({label:`Уведомления: ${label}`,type:'checkbox'});field.input.checked=Boolean(data.settings[name+'_enabled']);controls[name+'_enabled']=field.input;settings.append(field.wrap);
    }
    const reminder=input({label:'Напомнить о встрече за минут (0 — выключено)',type:'number',value:data.settings.reminder_minutes ?? 15});reminder.input.min='0';reminder.input.max='1440';settings.append(reminder.wrap);
    settings.append(node('p','muted-copy','По умолчанию — внутренняя и файловая очередь. Внешние каналы требуют настройки сервера и вашего подтверждения получателя.'));
    const save=button('Предпросмотр настроек',null,'secondary-button','submit');settings.append(save);
    settings.addEventListener('submit',event=>{event.preventDefault();void run(save,async()=>{
      const result=await request('/notification-settings/preview',{method:'POST',body:{...Object.fromEntries(Object.entries(controls).map(([k,v])=>[k,v.checked])),reminder_minutes:Number(reminder.input.value)}});
      preview('Подтвердить каналы уведомлений',result,body=>request('/notification-settings/confirm',{method:'POST',body}));
    });});parent.append(settings);
    if(!data.notifications.length)parent.append(node('p','empty-copy','Доступных уведомлений нет.'));
    for(const notice of data.notifications){
      const card=node('article','panel');card.append(node('p','',notice.message),node('p','task-meta',date(notice.created_at)));
      card.append(button('Открыть',()=>void run(null,async()=>{
        await request(`/notifications/${notice.id}/read`,{method:'POST'});
        if(notice.object_type==='task'){
          const source=await request(`/sources/task/T${notice.object_id}`);await openMeeting(source.data.meeting_id,'tasks');
        }else if(notice.object_type==='meeting')await openMeeting(Number(notice.object_id));
        else navigate('briefing');
      }),'secondary-button'));parent.append(card);
    }
  }
  async function retention(parent){
    const epoch=state.epoch;parent.append(node('h1','','Хранение данных'));
    const data=await request('/retention');if(epoch!==state.epoch || !parent.isConnected)return;
    const form=node('form','panel meet-form-grid');const controls={};
    for(const [name,label] of [['transcript_days','Срок хранения расшифровок, дней'],['chat_days','Срок хранения ответов, дней'],['audit_days','Срок хранения журнала, дней']]){
      const field=input({label,type:'number',value:data.policy[name]});field.input.min='1';controls[name]=field.input;form.append(field.wrap);
    }
    const audio=input({label:'Удалять аудио после подтверждения всего протокола',type:'checkbox'});audio.input.checked=Boolean(data.policy.audio_after_confirm);form.append(audio.wrap);
    const save=button('Предпросмотр политики',null,'secondary-button','submit');form.append(save);
    form.addEventListener('submit',event=>{event.preventDefault();void run(save,async()=>{
      const result=await request('/retention/policy/preview',{method:'POST',body:{...Object.fromEntries(Object.entries(controls).map(([k,v])=>[k,Number(v.value)])),audio_after_confirm:audio.input.checked}});
      preview('Подтвердить сроки хранения',result,body=>request('/retention/policy/confirm',{method:'POST',body}));
    });});parent.append(form);
    const cleanup=button('Очистить тестовые данные',()=>void run(cleanup,async()=>{
      const result=await request('/retention/cleanup/preview',{method:'POST'});
      preview('Подтвердить очистку тестовых данных',result,body=>request('/retention/cleanup/confirm',{method:'POST',body}));
    }),'secondary-button');parent.append(cleanup);
    parent.append(node('h2','','Запросы на удаление'));
    for(const row of data.requests){
      const card=node('article','panel');card.append(node('p','',`Запрос ${row.id} · пользователь ${row.user_id} · ${({pending:'ожидает проверки',confirmed:'подтверждён'})[row.status] || row.status} · ${date(row.requested_at)}`));
      if(row.status==='pending')card.append(button('Проверить удаление',()=>void run(null,async()=>{
        const result=await request(`/privacy/delete-requests/${row.id}/preview`,{method:'POST'});
        preview('Подтвердить удаление данных пользователя',result,body=>request(`/privacy/delete-requests/${row.id}/confirm`,{method:'POST',body}));
      }),'secondary-button'));parent.append(card);
    }
  }
  async function comments(card,tid){
    const epoch=state.epoch;const result=await request(`/tasks/${tid}/comments`);if(epoch!==state.epoch || !card.isConnected)return;
    const panel=node('details','panel');panel.open=true;panel.append(node('summary','','Комментарии и история'));
    for(const row of result.comments)panel.append(node('p','',`${date(row.created_at)} · ${row.text}`));
    const labels={status:'Статус',assignee_user_id:'Ответственный',due:'Срок',priority:'Приоритет'};
    const values={open:'открыто',in_progress:'в работе',blocked:'заблокировано',done:'готово',cancelled:'отменено',low:'низкий',normal:'обычный',high:'высокий',urgent:'срочный'};
    for(const row of result.history){
      const before=JSON.parse(row.before_json),after=JSON.parse(row.after_json);
      const describe=(k,v)=>k==='assignee_user_id'?(state.users.find(u=>u.id===v)?.name || 'не уточнён'):(values[v] || v || 'не уточнён');
      for(const key of Object.keys(before))if(before[key]!==after[key])panel.append(node('p','task-meta',`${date(row.created_at)} · ${labels[key] || key}: ${describe(key,before[key])} → ${describe(key,after[key])}`));
    }
    const form=node('form');const text=input({label:'Комментарий к задаче'});text.input.maxLength=2000;
    const save=button('Добавить комментарий',null,'secondary-button','submit');form.append(text.wrap,save);
    form.addEventListener('submit',event=>{event.preventDefault();void run(save,async()=>{
      await request(`/tasks/${tid}/comments`,{method:'POST',body:{text:text.input.value}});panel.remove();await comments(card,tid);
    });});panel.append(form);card.append(panel);
  }
  return {notifications,retention,comments};
}
