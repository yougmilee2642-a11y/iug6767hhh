let quickCandidate=null, quickAgentId=null, quickSavedId=null, quickBusy=false;
let quickStep=0, draftRevision=0, draftReady=false, draftConflict=false;
let draftQueue=Promise.resolve(), draftTimer=null, draftInitialization=null, draftDirty=false;
const KL=window.FocusKnowledgeLimits;
function setFieldError(el,message){
  let note=el.parentElement.querySelector(':scope > .field-error');
  if(message){
    if(!note){note=document.createElement('small');note.className='field-error';el.parentElement.append(note);}
    note.textContent=message;el.setAttribute('aria-invalid','true');
    note.id=note.id||'err-'+Math.random().toString(36).slice(2,9);el.setAttribute('aria-describedby',(el.name==='facts'?'knowledgeCounter ':'')+note.id);
  }else{
    note?.remove();el.removeAttribute('aria-invalid');
    if(el.name!=='facts')el.removeAttribute('aria-describedby');else el.setAttribute('aria-describedby','knowledgeCounter');
  }
}
// Shows the shared knowledge counter and explains every limit next to its field. Never edits the text.
function renderKnowledgeLimits(){
  const data=quickData(),found=KL.problems(data),usage=KL.usage(data);
  $('#knowledgeCounter').textContent=KL.counterText(data);
  $('#knowledgeCounter').classList.toggle('over',usage.remaining<0);
  const byTarget=new Map(),rows=[...$('#quickFAQ').children],form=$('#quickForm'),summary=[];
  for(const item of found){
    let el=null;
    if(item.field==='facts')el=form.elements.facts;
    else if(item.index!==null&&rows[item.index])el=rows[item.index].querySelector('[data-faq="'+item.field+'"]');
    if(el)byTarget.set(el,item.message);else summary.push(item.message);
  }
  setFieldError(form.elements.facts,byTarget.get(form.elements.facts)||'');
  rows.forEach(row=>row.querySelectorAll('[data-faq]').forEach(el=>setFieldError(el,byTarget.get(el)||'')));
  $('#knowledgeErrors').textContent=summary.join(' ');
  return {found,byTarget};
}
function firstKnowledgeProblem(){
  const {found,byTarget}=renderKnowledgeLimits();
  if(!found.length)return null;
  const first=[...byTarget.keys()][0]||$('#quickAddFAQ');
  return {message:found[0].message,element:first};
}
const quickNames=['business_name','business_type','city','greeting','facts','role','tone','timezone','routing_preference'];
async function quickApi(path,body,method='POST') {
  const response=await fetch(path,body===undefined?{}:{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data=await response.json();
  if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:data.detail?.map?.(e=>e.msg).join('; ')||'Проверьте поля мастера');
  return data;
}
function quickData(){
  const form=$('#quickForm'), data=Object.fromEntries(quickNames.map(name=>[name,form.elements[name].value.trim()]));
  data.business_type||='Компания';
  data.qa=[...$('#quickFAQ').children].map(row=>Object.fromEntries(['question','answer','source'].map(key=>[key,row.querySelector('[data-faq="'+key+'"]').value.trim()])));
  if(quickAgentId)data.agent_id=quickAgentId;return data;
}
function setQuickBusy(value){quickBusy=value;for(const input of $('#quickForm').elements)input.disabled=value;$('#quickRestore').disabled=value;$$('[data-quick-step]').forEach(b=>b.disabled=value);}
function clearQuickReview(){
  quickCandidate=null;quickSavedId=null;$('#quickPreview').hidden=true;$('#quickSave').hidden=true;$('#quickTest').hidden=true;
  $('#quickLifecycle').textContent='Черновик';$('#quickPreviewButton').hidden=quickStep!==4;
}
function quickChanged(){
  clearQuickReview();updateQuickRole();$('#quickStatus').textContent='Изменения применятся после проверки и подтверждения.';
  renderKnowledgeLimits();draftDirty=true;
  clearTimeout(draftTimer);$('#draftSaveStatus').textContent='Есть несохранённые изменения';
  draftTimer=setTimeout(()=>persistQuickDraft().catch(e=>{$('#draftSaveStatus').textContent=e.message;}),600);
}
function updateQuickRole(){
  const data=quickData(),support=data.role==='support';
  $('#quickRoleDescription').textContent=support?'Отвечает по FAQ. Обычный вопрос не требует имени и телефона. Запрос человека фиксируется локально.':'Собирает имя, телефон и причину обращения. Сохраняет обращение после подтверждения клиента.';
  $('#greetingSample').textContent=data.greeting||`Здравствуйте! Я AI-помощник ${data.business_name||'вашей компании'}. ${support?'Чем могу помочь?':'Приму ваше обращение. Как к вам обращаться?'}`;
}
function addQuickFAQ(item={}){
  if($('#quickFAQ').children.length>=10){showToast('Можно добавить до 10 вопросов');return false;}
  const row=document.createElement('div');row.className='faq-editor';
  row.innerHTML=`<label>Вопрос<input data-faq="question" aria-label="Вопрос" required value="${escapeHtml(item.question||'')}" placeholder="Что часто спрашивают клиенты?"></label><label>Ваш ответ<textarea data-faq="answer" aria-label="Ваш ответ" required rows="3" placeholder="Точный ответ для помощника">${escapeHtml(item.answer||'')}</textarea></label><label>Источник или пояснение<input data-faq="source" aria-label="Источник или пояснение" value="${escapeHtml(item.source||'')}" placeholder="Например: утверждённый прайс"></label><button type="button" class="text-button" aria-label="Удалить вопрос из черновика">Удалить вопрос</button>`;
  row.querySelector('button').onclick=()=>{row.remove();quickChanged();};$('#quickFAQ').append(row);return true;
}
function fillQuick(data={}){
  $('#quickForm').reset();$('#quickFAQ').replaceChildren();
  for(const name of quickNames)if(data[name]!==undefined)$('#quickForm').elements[name].value=data[name];
  for(const item of data.qa||[])addQuickFAQ(item);
  quickAgentId=data.agent_id||null;clearQuickReview();updateQuickRole();renderKnowledgeLimits();$('#quickTitle').textContent=quickAgentId?'Изменить помощника':'Ваш новый помощник';
}
function quickValid(step=quickStep){
  for(const input of $('[data-stage="'+step+'"]').querySelectorAll('input,textarea,select'))if(!input.reportValidity())return false;
  if(step===2){const problem=firstKnowledgeProblem();if(problem){$('#quickStatus').textContent=problem.message+' Введённый текст сохранён в форме.';problem.element.focus();return false;}}
  return true;
}
function setQuickStep(step){
  quickStep=step;$$('[data-stage]').forEach(panel=>panel.hidden=Number(panel.dataset.stage)!==step);
  $$('[data-quick-step]').forEach(button=>{button.classList.toggle('active',Number(button.dataset.quickStep)===step);button.setAttribute('aria-current',Number(button.dataset.quickStep)===step?'step':'false');button.setAttribute('aria-label',['1 Компания и роль','2 Приветствие','3 Знания','4 Границы и каналы','5 Проверка настроек'][Number(button.dataset.quickStep)]);});
  $('#quickBack').hidden=step===0;$('#quickNext').hidden=step===4;$('#quickPreviewButton').hidden=step!==4||!!quickCandidate;
  $('#quickSave').hidden=step!==4||!quickCandidate||$('#quickLifecycle').textContent==='Настроен для веб-теста';
  $('#quickTest').hidden=step!==4||$('#quickLifecycle').textContent!=='Настроен для веб-теста';
}
async function initializeQuickDraft(){
  if(!draftInitialization)draftInitialization=quickApi('/api/track1/draft').then(current=>{draftRevision=current.revision;draftReady=true;$('#quickRestore').hidden=!current.data;$('#draftSaveStatus').textContent=current.data?'Есть сохранённый черновик':'Черновик ещё не сохранён';}).catch(e=>{draftInitialization=null;throw e;});
  return draftInitialization;
}
function persistQuickDraft(){
  clearTimeout(draftTimer);const snapshot=quickData();
  const task=draftQueue.catch(()=>{}).then(async()=>{
    if(!draftReady)await initializeQuickDraft();if(draftConflict)throw new Error('Черновик изменён в другой вкладке. Загрузите свежую версию');
    let response;
    try{response=await fetch('/api/track1/draft',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_revision:draftRevision,data:snapshot})});}
    catch{throw new Error('Нет связи с сервером. Изменения остались в форме, но не записаны; не закрывайте страницу.');}
    const data=await response.json();
    if(!response.ok){if(response.status===409){draftConflict=true;$('#quickRestore').hidden=false;$('#quickKeepMine').hidden=false;}throw new Error(typeof data.detail==='string'?data.detail:'Не удалось сохранить черновик');}
    draftRevision=data.revision;$('#quickRestore').hidden=false;$('#quickKeepMine').hidden=true;
    if(JSON.stringify(quickData())===JSON.stringify(snapshot))draftDirty=false;
    $('#draftSaveStatus').textContent=draftDirty?'Есть несохранённые изменения':'Черновик сохранён на этом компьютере';return data;
  });draftQueue=task;return task;
}
async function editQuickAgent(id){
  if(active||starting||finishing)throw new Error('Завершите разговор перед изменением помощника');
  clearTimeout(draftTimer);await draftQueue.catch(()=>{});
  if(draftDirty&&!confirm('Открыть настройки другого помощника? Несохранённые поля будут заменены.'))return;
  fillQuick(await quickApi('/api/track1/agents/'+encodeURIComponent(id)+'/settings'));setQuickStep(0);showView('quick');
  $('#quickStatus').textContent='Вы редактируете копию настроек. Действующие разговоры сохраняют свою версию.';
}
async function newQuickAssistant(){if(draftDirty&&!confirm('Начать нового помощника? Несохранённые поля этой формы будут заменены.'))return;if(active||starting||finishing)throw new Error('Завершите текущий разговор');clearTimeout(draftTimer);await draftQueue.catch(()=>{});fillQuick();setQuickStep(0);showView('quick');$('#quickStatus').textContent='';}
async function addQuestionFromHistory(id,question,interactionId){await editQuickAgent(id);if(addQuickFAQ({question,source:'Вопрос из веб-теста '+interactionId})){setQuickStep(2);quickChanged();}}
window.addEventListener('DOMContentLoaded',()=>{
  $('#quickForm').noValidate=true;
  window.addEventListener('beforeunload',event=>{if(draftDirty){event.preventDefault();event.returnValue='';}});
  setQuickStep(0);updateQuickRole();renderKnowledgeLimits();initializeQuickDraft().catch(e=>{$('#draftSaveStatus').textContent=e.message;});
  $('#quickForm').addEventListener('input',quickChanged);$('#quickAddFAQ').onclick=()=>{if(addQuickFAQ())quickChanged();};
  $('#quickNext').onclick=()=>{if(quickValid())setQuickStep(Math.min(4,quickStep+1));};$('#quickBack').onclick=()=>setQuickStep(Math.max(0,quickStep-1));
  $$('[data-quick-step]').forEach(button=>button.onclick=()=>{const step=Number(button.dataset.quickStep);if(step<=quickStep||quickValid())setQuickStep(step);});
  $('#quickReset').onclick=()=>newQuickAssistant().catch(e=>showToast(e.message));
  $('#quickRestore').onclick=async()=>{
    if(quickBusy)return;if(active||starting||finishing){showToast('Завершите текущий разговор');return;}
    if(!confirm('Загрузить сохранённый черновик с сервера? Все текущие поля формы'+(draftDirty?', включая несохранённые изменения,':'')+' будут заменены.'))return;
    clearTimeout(draftTimer);await draftQueue.catch(()=>{});
    try{const current=await quickApi('/api/track1/draft');draftRevision=current.revision;draftConflict=false;$('#quickKeepMine').hidden=true;draftReady=true;fillQuick(current.data||{});draftDirty=false;setQuickStep(0);$('#quickStatus').textContent='Загружен серверный черновик. Несохранённые поля заменены.';$('#draftSaveStatus').textContent='Сохранённый черновик загружен';}catch(e){showToast(e.message);}
  };
  // Two tabs edited the draft. Keep what is typed here: adopt the server revision, then write this form over it.
  $('#quickKeepMine').onclick=async()=>{
    if(quickBusy)return;
    if(!confirm('Заменить сохранённый на сервере черновик содержимым этой вкладки? Правки из другой вкладки будут перезаписаны.'))return;
    try{
      clearTimeout(draftTimer);await draftQueue.catch(()=>{});
      const current=await quickApi('/api/track1/draft');draftRevision=current.revision;draftConflict=false;draftReady=true;
      await persistQuickDraft();$('#quickStatus').textContent='Ваша версия сохранена поверх черновика из другой вкладки.';
    }catch(e){$('#quickStatus').textContent=e.message;}
  };
  $('#quickForm').onsubmit=async event=>{
    event.preventDefault();if(quickBusy)return;
    for(let step=0;step<4;step++){setQuickStep(step);if(!quickValid(step))return;}setQuickStep(4);setQuickBusy(true);clearQuickReview();
    try{
      const draft=await persistQuickDraft();quickCandidate=await quickApi('/api/track1/preview',{...quickData(),draft_revision:draft.revision});
      const config=quickCandidate.config,knowledge=config.business.knowledge;
      $('#quickPreview').innerHTML=`<h3>${escapeHtml(config.name)}</h3><p>${escapeHtml(config.role.name)} · канал не подключён</p><h4>Приветствие</h4><p>${escapeHtml(config.greeting)}</p><h4>Знания</h4><p class="track1-facts">${escapeHtml(knowledge.notes||'Общие факты не указаны.')}</p>${(knowledge.qa||[]).map(q=>`<p><b>${escapeHtml(q.question)}</b><br>${escapeHtml(q.answer)}${q.source?'<br><small>'+escapeHtml(q.source)+'</small>':''}</p>`).join('')}<h4>Действия и ограничения</h4><p>${config.fields.length?'Имя, телефон, причина обращения. Сохранение только после подтверждения клиента.':'Ответы по знаниям. Контакты для обычного вопроса не требуются.'}</p><p>Неизвестный ответ нельзя выдумывать. Запрос человека фиксируется локально. Реального соединения, телефонии и календаря нет.</p>`;
      $('#quickPreview').hidden=false;$('#quickSave').hidden=false;$('#quickPreviewButton').hidden=true;$('#quickLifecycle').textContent='Готов к проверке';$('#quickStatus').textContent='Сервер проверил конфигурацию. Проверьте содержание и подтвердите сохранение.';
      const details=document.createElement('p'),input=quickData();
      details.textContent=`Сфера: ${input.business_type}. Город: ${input.city||'не указан'}. Часовой пояс: ${input.timezone}. Стиль: ${{brief:'кратко',friendly:'доброжелательно',formal:'официально'}[input.tone]}. Будущий маршрут: ${{unspecified:'не выбран',voice:'голос',chat_requested:'чат после уточнения МТС'}[input.routing_preference]}. Канал этим выбором не подключается.`;
      $('#quickPreview').append(details);
    }catch(e){$('#quickStatus').textContent=e.message;}finally{setQuickBusy(false);}
  };
  $('#quickSave').onclick=async()=>{
    if(quickBusy||!quickCandidate)return;if(active||starting||finishing){showToast('Завершите текущий разговор');return;}setQuickBusy(true);
    try{
      const saved=await quickApi('/api/track1/agents',{candidate_id:quickCandidate.candidate_id,review_token:quickCandidate.review_token});quickSavedId=saved.id;quickAgentId=saved.id;
      await builderApi('/api/agents/'+encodeURIComponent(saved.id)+'/activate',{});await loadAgentChoices(saved.id);await loadAgentList();
      $('#quickLifecycle').textContent='Настроен для веб-теста';$('#quickStatus').textContent='Можно проверить голосом или текстом в браузере. Внешний канал не подключён.';$('#quickSave').hidden=true;$('#quickTest').hidden=false;document.dispatchEvent(new Event('focus:updated'));
      await persistQuickDraft().catch(e=>{$('#draftSaveStatus').textContent='Помощник сохранён, но черновик не обновлён: '+e.message;});
    }catch(e){$('#quickStatus').textContent=(quickSavedId?'Настройки сохранены, но веб-тест ещё не активирован. Можно повторить. ':'')+e.message;}finally{setQuickBusy(false);}
  };
  $('#quickTest').onclick=async()=>{try{if(quickSavedId)await selectAgent(quickSavedId);showView('call');}catch(e){showToast(e.message);}};
  $('#startText').onclick=()=>{if(!active&&!starting&&!finishing)startCall(false);else showToast('Сначала завершите текущий разговор');};
});
