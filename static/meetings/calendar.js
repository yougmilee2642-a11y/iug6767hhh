// Functional calendar interchange in the existing controls; no external delivery.
export function calendarUI(h) {
  const {node,makeButton:button,makeInput:input,request,runAction:run,state,ui,dateLabel:date,markSaved} = h;
  function panel(parent) {
    if (!state.capabilities.includes('calendar.view')) return;
    const userId=state.user.id, epoch=state.epoch;
    const section=node('details','panel');
    section.append(node('summary','','Мой календарь · ICS и приглашения'));
    parent.append(section);
    const current=()=>state.user?.id===userId && state.epoch===epoch && section.isConnected;
    function link(label,path) {
      const anchor=node('a','text-button',label);anchor.href=path;anchor.download='';return anchor;
    }
    section.append(node('p','muted-copy','Скачивание и подписка только для чтения. Внешние письма не отправляются.'),
      link('Скачать мой календарь .ics','/api/meet/calendar/export.ics'));
    const list=node('div','');
    const load=button('Показать события и приглашения',()=>void run(load,async()=>{
      const [events,outbox]=await Promise.all([request('/calendar/events'),request('/calendar/outbox')]);
      if(!current())return;
      list.replaceChildren();
      if(!events.events.length)list.append(node('p','','Подтверждённых событий нет.'));
      for(const event of events.events) {
        const row=node('p','');row.append(node('span','',`${date(event.start_at)} · ${event.title} `),
          link('Скачать событие .ics',`/api/meet/calendar/export.ics?event_id=${event.id}`));list.append(row);
      }
      for(const invitation of outbox.invitations) {
        const row=node('p','');row.append(link(`Скачать приглашение №${invitation.id} .eml`,
          `/api/meet/calendar/outbox/${invitation.id}/download.eml`));list.append(row);
      }
    }));section.append(load,list);

    const subscription=node('div','');
    const subscribe=button('Создать ссылку подписки',()=>{
      const content=node('div','');content.append(node('p','','Ссылка на 90 дней показывает только время занятости без названий и участников. Предыдущая ссылка будет отозвана. Добавление в Google/Outlook передаст время занятости выбранному сервису.'));
      ui.dialog('Создать подписку календаря',content,async()=>{
        const result=await request('/calendar/subscriptions',{method:'POST'});
        if(!current())return;
        subscription.replaceChildren(node('p','muted-copy',result.notice));
        const url=input({label:'Ссылка подписки (храните как пароль)',value:new URL(result.path,location.origin).href});
        url.input.readOnly=true;subscription.append(url.wrap,node('p','task-meta',`Действует до ${date(result.expires_at)}`));
      },null,'Создать ссылку');
    });
    const revoke=button('Отозвать ссылки подписки',()=>void run(revoke,async()=>{
      const result=await request('/calendar/subscriptions');
      if(!current())return;
      for(const row of result.subscriptions.filter(row=>!row.revoked_at)) {
        await request(`/calendar/subscriptions/${row.id}`,{method:'DELETE'});
        if(!current())return;
      }
      subscription.replaceChildren(node('p','','Ссылки подписки отозваны.'));
    }));section.append(subscribe,revoke,subscription);

    const form=node('form','meet-form-grid');
    const file=input({label:'Импорт занятости (.ics)',type:'file',required:true});file.input.accept='.ics,text/calendar';
    const zone=input({label:'Часовой пояс событий без TZID',value:state.timezone || 'Europe/Minsk',required:true});
    const submit=button('Предпросмотр импорта',null,'secondary-button','submit');
    const status=node('p','');status.setAttribute('role','status');
    form.append(file.wrap,zone.wrap,submit,status);
    form.addEventListener('submit',event=>{
      event.preventDefault();void run(submit,async()=>{
        const body=new FormData();body.append('file',file.input.files[0]);body.append('timezone',zone.input.value.trim());
        const result=await request('/calendar/import/preview',{method:'POST',body});
        if(!current())return;
        const content=node('div','');content.append(node('p','',result.preview.notice),
          node('p','',`Интервалов занятости: ${result.preview.intervals.length}`));
        const rows=node('ul','');
        for(const interval of result.preview.intervals.slice(0,20)) rows.append(node('li','',`${date(interval.start_at)} — ${date(interval.end_at)}`));
        content.append(rows);if(result.preview.intervals.length>20)content.append(node('p','','Показаны первые 20 интервалов.'));
        const key=crypto.randomUUID();
        ui.dialog('Проверить импорт занятости',content,async()=>{
          const done=await request('/calendar/import/confirm',{method:'POST',body:{confirmation_id:result.confirmation_id,idempotency_key:key}});
          if(!current())return;
          status.textContent=`Импортировано интервалов: ${done.interval_count}.${done.unchanged ? ' Повторный файл, изменений нет.' : ''}`;
          markSaved(form);
        },()=>request(`/confirmations/${result.confirmation_id}/cancel`,{method:'POST'}));
      });
    });section.append(form);
  }
  return {panel};
}
