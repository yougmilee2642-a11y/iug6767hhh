// Functional mock CRM controls using the existing confirmation dialogs/styles.
export function crmUI(h) {
  const {node,makeButton:button,makeInput:input,request,state,ui,dateLabel,runAction:run} = h;
  const current = (id,epoch) => state.user?.id===id && state.epoch===epoch;
  async function review(draft,onDone) {
    const identity=state.user.id,epoch=state.epoch;
    const data=await request('/crm/preview',{method:'POST',body:draft});
    if (!current(identity,epoch)) return;
    const view=data.preview, fields=view.fields, content=node('div','');
    content.append(node('p','muted-copy',view.notice));
    if (view.warning) content.append(node('p','notice',view.warning));
    if (draft.action==='task.create') {
      content.append(node('p','',fields.text),node('p','task-meta',`Ответственный в CRM: ${fields.assignee_name}`),
        node('p','task-meta',`Срок: ${fields.due ? dateLabel(fields.due) : 'Не указан'}`),
        node('p','task-meta',`Приоритет: ${{low:'Низкий',normal:'Обычный',high:'Высокий',urgent:'Срочный'}[fields.priority]}`),
        node('p','',`Основание · ${fields.source_quote.utterance_id || 'ручное поручение'}: ${fields.source_quote.text}`));
      content.append(ui.sourceButton({kind:fields.source_quote.utterance_id?'utterance':'task',id:fields.source_quote.utterance_id || 'T'+fields.task_id,quote:fields.source_quote.text,
        source_at:fields.source_at,title:fields.source_quote.utterance_id?'Открыть реплику-основание':'Ручное подтверждённое поручение'}));
    } else {
      content.append(node('p','',fields.title),node('p','task-meta',`Получатель: ${fields.entity_ref}`));
      for (const item of fields.items) content.append(node('p','',item.text),node('p','task-meta',item.quotes.map(q=>`${q.utterance_id || 'Ручное поручение'}: ${q.text}`).join('\n')));
    }
    content.append(node('p','task-meta',`Дата источника: ${dateLabel(view.freshness.as_of)}`));
    const key=crypto.randomUUID();
    ui.dialog(view.mode==='mock'?'Что уйдёт в Битрикс24 · mock':'Что уйдёт в Битрикс24',content,async()=>{
      await request('/crm/confirm',{method:'POST',body:{confirmation_id:data.confirmation_id,idempotency_key:key}});
      if (current(identity,epoch)) await onDone();
    },async()=>{
      try { await request(`/confirmations/${data.confirmation_id}/cancel`,{method:'POST'}); }
      catch (error) { if (error.code!=='already_confirmed') throw error; }
    });
  }
  async function exportTask(task,onDone) { await review({action:'task.create',object_id:task.id},onDone); }
  async function status(task) {
    const result=await request(`/crm/tasks/${task.id}`),content=node('div','');
    const names={sent:result.mode==='mock'?'Отправлено в локальную имитацию':'Отправлено в Битрикс24',uncertain:'Результат неизвестен. Повторная отправка заблокирована; нужна проверка.',failed:'Отправка не выполнена. Нужна проверка перед новым действием.'};
    content.append(node('p','',names[result.outbox?.status] || 'Отправки ещё не было.'));
    if (result.external) content.append(node('p','task-meta',`Статус задачи CRM: ${{open:'Открыта',done:'Выполнена',cancelled:'Отменена'}[result.external.status] || result.external.status}`),
      node('p','task-meta',`Дата источника: ${dateLabel(result.external.as_of)}`));
    ui.dialog(result.mode==='mock'?'Отправка в Битрикс24 · mock':'Отправка в Битрикс24',content,async()=>{},null,'Закрыть');
  }
  async function attachProtocol(meeting,onDone) {
    const identity=state.user.id,epoch=state.epoch;
    const data=await request(`/crm/targets?meeting_id=${meeting.id}`);
    if (!current(identity,epoch)) return;
    const form=node('div',''),select=node('select','');select.setAttribute('aria-label','Получатель протокола');
    for (const target of data.targets) { const option=node('option','',target.label);option.value=target.ref;select.append(option); }
    form.append(node('p','muted-copy','Будут отправлены только подтверждённые пункты с цитатами.'),select);
    if (!data.targets.length) { form.append(node('p','notice','Доступных задач и сделок CRM пока нет. Сначала отправьте задачу.'));ui.dialog('Получатель протокола',form,async()=>{},null,'Закрыть');return; }
    let editor;
    editor=ui.dialog('Получатель протокола',form,async()=>{
      const ref=select.value;editor.close();
      await review({action:'protocol.attach',object_id:meeting.id,entity_ref:ref},onDone);
    },null,'Предпросмотр');
  }
  async function openOrder(orderNo) {
    const identity=state.user.id,epoch=state.epoch;
    const data=await request(`/crm/orders/${encodeURIComponent(orderNo)}`);
    if (!current(identity,epoch)) return;
    const order=data.order,content=node('div','');
    if (data.warning) content.append(node('p','notice',data.warning));
    content.append(node('p','',`Заказ ${order.order_no}`),node('p','task-meta',`Статус: ${order.status} · Перевозчик: ${order.carrier_code}`),
      node('p','task-meta',`Стоимость: ${(order.amount_minor/100).toFixed(2)} ${order.currency}`),
      node('p','task-meta',`Дата источника: ${dateLabel(order.as_of)} · ${order.source_id}`),
      node('p','',`Доступных обращений: ${data.interactions.length}`));
    for (const event of order.events) content.append(node('p','task-meta',`${dateLabel(event.at)} · ${event.status}`));
    ui.dialog('Заказ · ERP mock',content,async()=>{},null,'Закрыть');
  }
  async function renderIntegrations(app) {
    const identity=state.user.id,epoch=state.epoch,section=node('section','panel v2-functional-panel');
    section.append(node('h1','','Интеграции'));app.append(section);
    try {
      const data=await request('/integrations');if (!current(identity,epoch)||!section.isConnected) return;
      for (const connector of data.connectors) section.append(node('p','',`${connector.name} · локальная имитация`),
        node('p','muted-copy',connector.notice),node('p','task-meta',`Последняя подтверждённая отправка: ${connector.last_export_at ? dateLabel(connector.last_export_at) : 'Не было'}`),
        node('p','task-meta',`Проверка соединения: ${connector.last_checked_at ? dateLabel(connector.last_checked_at) : 'Не проводилась'}`));
      section.append(node('p','',`Сопоставлено сотрудников: ${data.mapped_employees}`));
      const result=node('p','');result.setAttribute('role','status');
      const check=button('Проверить соединение',()=>void run(check,async()=>{
        const data=await request('/integrations/check',{method:'POST'});
        if (current(identity,epoch)&&section.isConnected) result.textContent=`SQLite-имитация доступна. Отделов: ${data.departments}.${data.stale ? ' Данные устарели.' : ''}`;
      }));section.append(check,result);
    } catch (error) { if(current(identity,epoch)&&section.isConnected) section.append(node('p','notice',error.message)); }
  }
  return {exportTask,attachProtocol,status,openOrder,renderIntegrations};
}
