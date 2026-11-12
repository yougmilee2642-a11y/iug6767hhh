// Document controls reuse the existing form, panel and preview styles.
export function documentLibrary(h) {
  const {node, makeButton: button, makeInput: input, makeSelect: select, request, runAction: run,
    state, render, dateLabel: date, showNotice, toast, dialog, field, sourceButton, claims} = h;
  let generation = 0;
  let filters = {text:'', classification:'', kind:'', history:false};
  let versionDrafts = new Map();
  const classificationLabel = {public:'Вся компания',internal:'Сотрудники',department:'Отдел',confidential:'Ограниченный доступ',secret:'Закрыт для ассистента'};
  const can = capability => state.capabilities.includes(capability);
  const label = doc => `${doc.title} · версия ${doc.version || 1}`;
  const cancel = id => request(`/confirmations/${encodeURIComponent(id)}/cancel`, {method:'POST'});
  const notice = (parent, warnings) => (warnings || []).forEach(w => parent.append(node('p','access-limited-note',w.message)));
  const reset = () => { generation++; filters = {text:'', classification:'', kind:'', history:false}; versionDrafts.clear(); };
  const partial = (parent,result) => { if(result.partial) parent.append(node('p','access-limited-note','Результат неполный: часть фрагментов пропущена или достигнут лимит. Откройте исходный файл.')); };
  async function reload() {
    const current = generation;
    const result = await request('/documents');
    if (current !== generation) return false;
    state.documents = result.documents || [];
    if (state.page === 'knowledge') render();
    return true;
  }
  function source(parent, cited) {
    parent.append(node('p','',cited.quote), sourceButton(cited));
  }
  async function open(doc, mode, target) {
    const current = generation;
    const result = await request(`/documents/${doc.id}/${mode}`);
    if (generation !== current) return;
    target.replaceChildren(node('h3','',`${mode === 'summary' ? 'Кратко' : 'Версии'}: ${doc.title}`));
    if (mode === 'summary') {
      target.append(node('p','muted-copy',result.notice));
      notice(target, result.warnings);
      partial(target,result);
      if (!result.claims?.length) target.append(node('p','','Недостаточно подходящих фрагментов.'));
      else claims(target, result.claims);
      return;
    }
    const versions = result.versions || [];
    const comparable = versions.filter(v=>v.confidentiality!=='secret');
    const from = select(comparable.map(v=>({value:v.id,label:label(v)})), comparable[0]?.id);
    const to = select(comparable.map(v=>({value:v.id,label:label(v)})), comparable.at(-1)?.id);
    versions.forEach(v=>{
      const row = node('article','panel');
      row.append(node('p','',`${label(v)} · ${date(v.authored_at || v.created_at)}${v.stale ? ' · устарел' : ''}`));
      row.append(button('Открыть источник',()=>h.openDocument(v),'secondary-button'));
      target.append(row);
    });
    if (comparable.length < 2) return;
    const diff = node('section','panel');
    const compare = button('Сравнить версии',async()=>run(compare,async()=>{
      const output = await request(`/documents/${encodeURIComponent(from.value)}/compare/${encodeURIComponent(to.value)}`);
      if (current !== generation) return;
      diff.replaceChildren(node('h3','','Изменения по фрагментам'));
      partial(diff,output);notice(diff,output.warnings);
      if (!output.changes.length) diff.append(node('p','','Текст фрагментов совпадает.'));
      output.changes.forEach(change=>{
        const block = node('article','panel');
        block.append(node('h4','',({insert:'Добавлено',delete:'Удалено',replace:'Заменено'})[change.change]));
        change.before.forEach(cited=>{ block.append(node('b','','Было')); source(block,cited); });
        change.after.forEach(cited=>{ block.append(node('b','','Стало')); source(block,cited); });
        diff.append(block);
      });
    }),'secondary-button');
    target.append(field('Было · версия',from),field('Стало · версия',to),compare,diff);
  }
  async function newVersion(doc) {
    const current = generation;
    const origin = document.activeElement;
    const draft = versionDrafts.get(doc.id);
    const form = node('form','meet-form-grid');
    const file = input({label:'Файл новой версии',type:'file',required:!draft?.file});
    const authored = input({label:'Дата документа (ISO 8601 с часовым поясом)',placeholder:'2026-11-12T10:00:00+03:00',value:draft?.authored || ''});
    const valid = input({label:'Действует до (ISO 8601, необязательно)',placeholder:'2026-12-31T23:59:59+03:00',value:draft?.valid || ''});
    if(draft?.file) form.append(node('p','task-meta',`Ранее выбран файл: ${draft.file.name}. Можно выбрать другой.`));
    form.append(node('p','',`${label(doc)}. Доступ наследуется, прежние цитаты сохранятся.`),file.wrap,authored.wrap,valid.wrap);
    form.addEventListener('submit',event=>event.preventDefault());
    const editor = dialog('Загрузить новую версию',form,async()=>{
      const selected = file.input.files[0] || draft?.file;
      if (!selected) throw new Error('Выберите файл новой версии.');
      const body = new FormData(); body.append('file',selected);
      body.append('authored_at',authored.input.value); body.append('valid_until',valid.input.value);
      const result = await request(`/documents/${doc.id}/versions/preview`,{method:'POST',body});
      if (current !== generation) return;
      versionDrafts.set(doc.id,{file:selected,authored:authored.input.value,valid:valid.input.value});
      editor.close(); editor.addEventListener('close',()=>{
        if (current !== generation) return;
        const content = node('div');
        content.append(node('p','',`${result.preview.title} · версия ${result.preview.version}`),
          node('p','',`Файл: ${result.preview.filename}. Фрагментов: ${result.preview.fragments_count}`),
          node('p','',`Дата документа: ${date(result.preview.authored_at)}`),
          node('p','',`Действует до: ${result.preview.valid_until ? date(result.preview.valid_until) : 'не ограничено'}`),
          node('p','',result.preview.notice));
        const idempotency = crypto.randomUUID();
        dialog('Подтвердить новую версию',content,async()=>{
          await request(`/documents/${doc.id}/versions/confirm`,{method:'POST',body:{confirmation_id:result.confirmation_id,idempotency_key:idempotency}});
          versionDrafts.delete(doc.id);
          if (await reload()) toast('Новая версия сохранена');
        },()=>cancel(result.confirmation_id),'Подтвердить',origin);
      },{once:true});
    },null,'Предпросмотр',origin);
  }
  async function openDocument(doc) {
    const current = generation;
    const result = await request(`/documents/${doc.id}`);
    if (current !== generation) return;
    const first = result.fragments?.[0];
    if (first) await h.openSource('fragment',first.id,first.text);
  }
  function uploadForm(parent) {
    const form=node('form','meet-form-grid');
    const files=input({label:'Добавить документы',type:'file',required:true}); files.input.multiple=true;
    files.input.accept='.txt,.docx,.pdf,.xlsx,.csv,.pptx,.md,.html,.eml';
    const kinds=select(['регламент','договор','план','протокол','письмо','отчёт','реестр','документ'].map(value=>({value,label:value})),'документ');
    const classifications=state.user.level==='employee' ? ['department'] : ['confidential','department','internal','public','secret'];
    const classification=select(classifications.map(value=>({value,label:classificationLabel[value]})));
    const departments=new Map();
    for (const user of [state.user,...state.users]) if (user.department_id) departments.set(String(user.department_id),user.department_name || `Отдел ${user.department_id}`);
    const department=select([{value:'',label:'Мой отдел'},...[...departments].map(([value,label])=>({value,label}))]);
    department.disabled=state.user.level!=='director';
    const authored=input({label:'Дата загружаемых документов (ISO 8601)',placeholder:'2026-11-12T10:00:00+03:00'});
    const valid=input({label:'Срок действия загружаемых документов (ISO 8601, необязательно)'});
    const upload=button('Загрузить документы',null,'secondary-button','submit');
    const result=node('p','task-meta'); result.setAttribute('role','status');
    form.append(files.wrap,field('Отдел документа',department),field('Конфиденциальность при загрузке',classification),field('Тип при загрузке',kinds),authored.wrap,valid.wrap,upload,result);
    form.addEventListener('submit',async event=>{
      event.preventDefault();
      const current=generation;
      const selected=[...files.input.files];
      if (!selected.length) return;
      await run(upload,async()=>{
        let saved=0;
        for (const file of selected) {
          if (current!==generation) return;
          const body=new FormData(); body.append('file',file);
          body.append('confidentiality',classification.value);body.append('doc_type',kinds.value);
          if (department.value) body.append('department_id',department.value);
          body.append('authored_at',authored.input.value);body.append('valid_until',valid.input.value);
          const output=await request('/documents',{method:'POST',body});
          if (current!==generation) return;
          state.documents=[...state.documents.filter(d=>d.id!==output.document.id),output.document];
          result.textContent=`Загружено ${++saved} из ${selected.length}.`;
        }
        if (current===generation) { files.input.value=''; await reload(); toast(`Загружено документов: ${saved}`); }
      });
    });
    parent.append(form);
  }
  function renderLibrary(parent) {
    if (!can('meetings.read')) return;
    const disclosure = node('details','panel');
    disclosure.append(node('summary','','Документы · версии и источники'));
    if (can('documents.upload')) uploadForm(disclosure);
    const controls = node('div','meet-form-grid');
    const text = input({label:'Фильтр документов по названию',value:filters.text});
    const classification = select([{value:'',label:'Все уровни доступа'},...['public','internal','department','confidential','secret'].map(value=>({value,label:classificationLabel[value]}))],filters.classification);
    const kind = select([{value:'',label:'Все типы'},...[...new Set(state.documents.map(d=>d.doc_type))].filter(Boolean).map(value=>({value,label:value}))],filters.kind);
    const history = input({label:'Показать заменённые версии',type:'checkbox'}); history.input.checked=filters.history;
    controls.append(text.wrap,field('Конфиденциальность',classification),field('Тип документа',kind),history.wrap);
    const list=node('div','search-results'), output=node('section','panel');
    const draw=()=>{
      filters={text:text.input.value,classification:classification.value,kind:kind.value,history:history.input.checked};
      list.replaceChildren();
      const docs=state.documents.filter(d=>(filters.history || !d.superseded) && (!filters.classification || filters.classification===d.confidentiality) && (!filters.kind || filters.kind===d.doc_type) && d.title.toLocaleLowerCase('ru').includes(filters.text.toLocaleLowerCase('ru')));
      if (!docs.length) list.append(node('p','empty-copy','Доступных документов по фильтрам нет.'));
      docs.forEach(doc=>{
        const row=node('article','panel');
        row.append(node('h3','',label(doc)),node('p','task-meta',`${doc.doc_type} · ${classificationLabel[doc.confidentiality] || 'Ограниченный доступ'} · ${date(doc.authored_at || doc.created_at)}${doc.stale ? ' · устарел' : ''}`));
        const actions=node('div','inline-actions');
        const addAction=(name,fn)=>{ const b=button(name,()=>run(b,fn),'secondary-button'); actions.append(b); };
        addAction('Открыть источник',()=>openDocument(doc));
        if(doc.confidentiality!=='secret')addAction('Кратко',()=>open(doc,'summary',output));
        addAction('Версии / сравнить',()=>open(doc,'versions',output));
        if (can('documents.upload') && Number(doc.owner_id)===Number(state.user.id) && !doc.superseded) addAction('Новая версия',()=>newVersion(doc));
        row.append(actions); list.append(row);
      });
    };
    [text.input,classification,kind,history.input].forEach(control=>control.addEventListener('input',draw));
    const refresh=button('Обновить документы',()=>run(refresh,reload),'secondary-button');
    disclosure.append(controls,refresh,list,output); draw(); parent.append(disclosure);
  }
  h.openDocument = openDocument;
  return {render:renderLibrary,reset};
}
