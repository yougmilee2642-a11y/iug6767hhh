// Functional document history/preview controls; existing components and no CSS.
export function documentsUI(h) {
  const {node,makeButton:button,makeInput:input,request,runAction:run,state,ui,dateLabel:date,markSaved}=h;
  const current=(id,epoch)=>state.user?.id===id && state.epoch===epoch;
  const classification={public:'Вся компания',internal:'Сотрудники',department:'Отдел',confidential:'Ограниченный доступ',secret:'Закрыт для ассистента'};
  const status=(doc)=>`${doc.superseded ? ' · Заменён' : ''}${doc.expired ? ' · Срок действия истёк' : ''}`;
  function warnings(parent,data) {
    for(const warning of data.warnings || [])parent.append(node('p','gap-state',warning.message));
    if(data.partial)parent.append(node('p','gap-state','Результат неполный: некоторые фрагменты пропущены или достигнут лимит. Откройте исходный файл.'));
  }
  function download(doc) {
    const a=node('a','download-link','Открыть исходный файл');a.href=`/api/meet/documents/${doc.id}/download`;return a;
  }
  async function summary(doc) {
    const id=state.user.id,epoch=state.epoch;
    const data=await request(`/documents/${doc.id}/summary`);if(!current(id,epoch))return;
    const content=node('div','');content.append(node('p','muted-copy',data.notice));warnings(content,data);
    if(!data.claims.length)content.append(node('p','','Подходящих выдержек не найдено. Откройте исходный файл.'));
    for(const claim of data.claims){content.append(node('p','',claim.text));for(const s of claim.sources)content.append(ui.sourceButton(s));}
    content.append(download(doc));ui.dialog(`Кратко · ${doc.title}`,content,async()=>{},null,'Закрыть');
  }
  async function history(doc) {
    const id=state.user.id,epoch=state.epoch;
    const data=await request(`/documents/${doc.id}/versions`);if(!current(id,epoch))return;
    const content=node('div','');
    content.append(node('p','muted-copy','Показаны версии, доступные вам сейчас. Привязки встреч к версии сохраняются.'));
    for(const v of data.versions)content.append(node('p','',`Версия ${v.version} · ${date(v.authored_at || v.created_at)}${status(v)}`),download(v));
    const allowed=data.versions.filter(v=>v.confidentiality!=='secret');
    if(allowed.length<2){ui.dialog('Версии документа',content,async()=>{},null,'Закрыть');return;}
    const picks=[];
    for(const [label,chosen] of [['Исходная версия',allowed[0].id],['Новая версия',allowed.at(-1).id]]){
      const wrap=node('label','meeting-field'),select=node('select','');select.setAttribute('aria-label',label);
      for(const v of allowed){const option=node('option','',`Версия ${v.version} · ${date(v.authored_at || v.created_at)}`);option.value=v.id;option.selected=v.id===chosen;select.append(option);}
      wrap.append(node('span','field-label',label),select);content.append(wrap);picks.push(select);
    }
    let modal;
    modal=ui.dialog('Версии документа',content,async()=>{
      // Resolve before replacing the dialog so failures preserve the selection.
      const a=picks[0].value,b=picks[1].value;
      const data=await request(`/documents/${a}/compare/${b}`);
      if(!current(id,epoch))return;
      modal.close();showComparison(data);
    },null,'Сравнить');
  }
  function showComparison(data) {
    const content=node('div','');content.append(node('p','muted-copy',data.notice));warnings(content,data);
    if(!data.changes.length)content.append(node('p','','В подходящих фрагментах различий нет.'));
    for(const change of data.changes){const block=node('article','claim-item');
      for(const [label,key] of [['Было','before'],['Стало','after']]){
        block.append(node('h3','',label));
        if(!change[key].length)block.append(node('p','muted-copy','Нет фрагмента'));
        for(const s of change[key])block.append(node('p','',s.quote),ui.sourceButton(s));
      }content.append(block);
    }ui.dialog('Сравнение версий',content,async()=>{},null,'Закрыть');
  }
  function versionForm(parent,doc,onDone) {
    const details=node('details',''),form=node('form','upload-form');details.append(node('summary','','Новая версия'));
    const file=input({label:'Файл новой версии',type:'file',required:true});
    file.input.accept='.txt,.docx,.pdf,.xlsx,.csv,.pptx,.md,.html,.eml';
    const authored=input({label:'Дата документа · Минск (необязательно)',type:'datetime-local'});
    const until=input({label:'Действует до · Минск (необязательно)',type:'datetime-local'});
    const submit=button('Предпросмотр новой версии',null,'secondary-button','submit');
    form.append(file.wrap,authored.wrap,until.wrap,submit);
    form.addEventListener('submit',event=>{event.preventDefault();if(!file.input.files[0])return;
      const id=state.user.id,epoch=state.epoch;
      void run(submit,async()=>{
        const payload=new FormData();payload.append('file',file.input.files[0]);
        if(authored.input.value)payload.append('authored_at',ui.zonedISO(authored.input.value,'Europe/Minsk'));
        if(until.input.value)payload.append('valid_until',ui.zonedISO(until.input.value,'Europe/Minsk'));
        const data=await request(`/documents/${doc.id}/versions/preview`,{method:'POST',body:payload});
        if(!current(id,epoch)||!form.isConnected)return;
        const view=data.preview,content=node('div','');
        content.append(node('p','',`${view.title} · версия ${view.version}`),node('p','',view.filename),
          node('p','task-meta',`Дата документа: ${date(view.authored_at)} · Действует до: ${view.valid_until ? date(view.valid_until) : 'Не ограничено'}`),
          node('p','task-meta',`Фрагментов: ${view.fragments_count}`),node('p','muted-copy',view.notice));
        const key=crypto.randomUUID();
        ui.dialog('Подтвердить новую версию',content,async()=>{
          await request(`/documents/${doc.id}/versions/confirm`,{method:'POST',body:{confirmation_id:data.confirmation_id,idempotency_key:key}});
          if(current(id,epoch)){markSaved(form);await onDone();}
        },()=>request(`/confirmations/${data.confirmation_id}/cancel`,{method:'POST'}));
      });
    });details.append(form);parent.append(details);
  }
  function controls(parent,doc,onDone) {
    const actions=node('div','inline-actions');
    for(const [label,action] of [['Кратко',()=>summary(doc)],['Версии',()=>history(doc)]]){
      if(label==='Кратко' && doc.confidentiality==='secret')continue;
      const b=button(label,()=>void run(b,action));actions.append(b);
    }parent.append(actions);
    if(doc.owner_id===state.user.id && ui.can('documents.upload') && !doc.superseded)versionForm(parent,doc,onDone);
  }
  function panel(parent) {
    const id=state.user.id,epoch=state.epoch,details=node('details','panel');
    details.append(node('summary','','Документы · версии и выдержки'));
    const content=node('div','');details.append(content);parent.append(details);
    let loaded=false;
    async function load(){
      const data=await request('/documents');if(!current(id,epoch)||!details.isConnected)return;
      state.documents=data.documents || [];loaded=true;content.replaceChildren();
      const filter=input({label:'Название документа',placeholder:'Фильтр по названию'});
      const history=input({label:'Показать заменённые версии',type:'checkbox'});
      const list=node('div','');content.append(node('p','muted-copy','Поиск и ответы используют актуальную доступную версию. Файлы и ссылки встреч сохраняются.'),filter.wrap,history.wrap,list);
      function draw(){list.replaceChildren();
        const docs=state.documents.filter(d=>(history.input.checked || !d.superseded) && (d.title || d.filename || '').toLowerCase().includes(filter.input.value.toLowerCase()));
        if(!docs.length)list.append(node('p','empty-copy','Документов по фильтру нет.'));
        for(const doc of docs){const card=node('article','claim-item');
          card.append(node('h3','',doc.title || doc.filename),node('p','task-meta',`Версия ${doc.version || 1} · ${classification[doc.confidentiality] || 'Ограниченный доступ'}${status(doc)}`),
            node('p','task-meta',`Дата документа: ${date(doc.authored_at || doc.created_at)}`),download(doc));
          controls(card,doc,load);list.append(card);
        }
      }filter.input.addEventListener('input',draw);history.input.addEventListener('change',draw);draw();
    }
    details.addEventListener('toggle',()=>{if(details.open && !loaded){loaded=true;void load().catch(error=>{
      if(current(id,epoch)&&details.isConnected){loaded=false;content.replaceChildren(node('p','notice',error.message));}
    });}});
  }
  return {panel,controls};
}
