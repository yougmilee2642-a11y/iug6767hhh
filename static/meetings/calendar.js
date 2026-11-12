// Calendar interchange; external SMTP requires a second explicit confirmation.
export function calendarUI(h) {
  const {node,makeButton:button,makeInput:input,makeSelect:select,request,runAction:run,state,ui,dateLabel:date,markSaved,openMeeting} = h;
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
    section.append(node('p','muted-copy','Скачивание и подписка только для чтения. SMTP требует отдельного предпросмотра и подтверждения.'),
      link('Скачать мой календарь .ics','/api/meet/calendar/export.ics'));
    const list=node('div','');
    const load=button('Показать события и приглашения',()=>void run(load,async()=>{
      const [events,outbox,delivery,smtp]=await Promise.all([request('/calendar/events'),request('/calendar/outbox'),request('/delivery-status'),request('/smtp-outbox')]);
      if(!current())return;
      list.replaceChildren();
      if(!events.events.length)list.append(node('p','','Событий нет.'));
      for(const event of events.events) {
        const status={confirmed:'Подтверждено',pending_external:'Ожидает внешнего календаря',uncertain:'Результат требует проверки',failed:'Не создано',cancelled:'Отменено'};
        const row=node('p','');row.append(node('span','',`${date(event.start_at)} · ${event.title} · ${status[event.status] || 'Требует проверки'} `),
          link('Скачать событие .ics',`/api/meet/calendar/export.ics?event_id=${event.id}`));list.append(row);
      }
      for(const invitation of outbox.invitations) {
        const row=node('p','');row.append(link(`Скачать приглашение №${invitation.id} .eml`,
          `/api/meet/calendar/outbox/${invitation.id}/download.eml`));
        const deliveryRow=smtp.outbox.find(item=>item.invitation_id===invitation.id);
        if(deliveryRow)row.append(node('span','',` SMTP: ${({pending:'в очереди',sending:'отправляется',sent:'отправлено',uncertain:'результат неизвестен, проверьте вручную',failed:'отклонено',cancelled:'отменено'})[deliveryRow.status] || 'проверьте статус'}.`));
        else if(delivery.smtp && state.capabilities.includes('calendar.invite'))row.append(button('Проверить SMTP-отправку',()=>void run(null,async()=>{
          const p=await request(`/calendar/outbox/${invitation.id}/smtp/preview`,{method:'POST'});if(!current())return;
          const content=node('div');content.append(node('p','',p.notice),node('p','',`От: ${p.preview.sender}; кому: ${p.preview.recipient}`),node('p','',p.preview.subject),node('pre','',p.preview.text),node('p','',`Вложение: ${p.preview.attachment}`));
          const key=crypto.randomUUID();ui.dialog('Подтвердить внешнюю отправку приглашения',content,async()=>{
            await request(`/calendar/outbox/${invitation.id}/smtp/confirm`,{method:'POST',body:{confirmation_id:p.confirmation_id,idempotency_key:key}});if(current())row.append(node('p','','Письмо в SMTP-очереди. Статус можно обновить кнопкой «Показать события и приглашения».'));
          },()=>request(`/confirmations/${p.confirmation_id}/cancel`,{method:'POST'}));
        }),'secondary-button'));
        list.append(row);
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
    if(state.capabilities.includes('meetings.create') && state.capabilities.includes('calendar.invite')){
      const series=node('details','panel');series.append(node('summary','','Повторяющиеся встречи'));
      series.append(node('p','muted-copy','Конечная серия в локальном календаре: от 2 до 30 встреч. Все даты проверяются до подтверждения. Для внешнего календаря каждое событие согласуется отдельно.'));
      const sf=node('form','meet-form-grid');
      const title=input({label:'Название серии',required:true});
      const start=input({label:'Первое время с часовым поясом (ISO)',value:new Date(Date.now()+7*86400000).toISOString(),required:true});
      const tz=input({label:'Часовой пояс серии',value:'Europe/Minsk',required:true});
      const freq=select([{value:'weekdays',label:'По рабочим дням'},{value:'daily',label:'Каждый день'},{value:'weekly',label:'Каждую неделю'}]);
      const freqLabel=node('label','meeting-field');freqLabel.append(node('span','field-label','Повторение'),freq);
      const count=input({label:'Количество встреч',type:'number',value:5});count.input.min='2';count.input.max='30';
      const duration=input({label:'Длительность, минут',type:'number',value:30});duration.input.min='15';duration.input.max='480';
      const smart=input({label:'Учитывать смены, перерывы и буфер',type:'checkbox'});smart.input.checked=true;
      const people=select(state.users.filter(u=>u.active!==0 && !['admin','auditor'].includes(u.level)).map(u=>({value:u.id,label:u.name})));
      people.multiple=true;people.setAttribute('aria-label','Участники серии');people.size=5;
      for(const option of people.options)option.selected=false;
      const pl=node('label','meeting-field');pl.append(node('span','field-label','Участники серии (можно несколько)'),people);
      const save=button('Предпросмотр всех дат серии',null,'secondary-button','submit');
      const output=node('div','');sf.append(title.wrap,start.wrap,tz.wrap,freqLabel,count.wrap,duration.wrap,smart.wrap,pl,save);
      sf.addEventListener('submit',event=>{event.preventDefault();void run(save,async()=>{
        const result=await request('/calendar/series/preview',{method:'POST',body:{title:title.input.value,start_at:start.input.value,timezone:tz.input.value,frequency:freq.value,count:Number(count.input.value),duration_minutes:Number(duration.input.value),smart:smart.input.checked,participant_ids:[...people.selectedOptions].map(o=>Number(o.value))}});
        if(!current())return;
        const preview=node('div');preview.append(node('p','',result.notice),node('p','',result.preview.participants.map(p=>p.name).join(', ')));
        for(const item of result.preview.occurrences)preview.append(node('p','',date(item.start_at)+' — '+date(item.end_at)));
        for(const warning of result.preview.warnings)preview.append(node('p','access-limited-note',warning));
        const key=crypto.randomUUID();ui.dialog('Проверить всю серию',preview,async()=>{
          const done=await request('/calendar/series/confirm',{method:'POST',body:{confirmation_id:result.confirmation_id,idempotency_key:key}});
          if(!current())return;output.replaceChildren(node('p','',`Создано встреч: ${done.meeting_ids.length}. Приглашения в локальной очереди.`));markSaved(sf);
        },()=>request(`/confirmations/${result.confirmation_id}/cancel`,{method:'POST'}));
      });});series.append(sf,output);
      const show=button('Показать доступные серии',()=>void run(show,async()=>{
        const result=await request('/calendar/series');if(!current())return;output.replaceChildren();
        for(const item of result.series){output.append(node('h3','',item.title));for(const meeting of item.meetings)output.append(button(date(meeting.scheduled_at),()=>void openMeeting(meeting.id),'text-button'));}
      }));series.append(show);section.append(series);
    }
  }
  return {panel};
}
