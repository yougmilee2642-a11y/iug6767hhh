let productAgents=[];
function productCards(items){
  if(!items.length)return '<article class="panel empty-state"><b>Помощников пока нет</b><p>Начните с названия и задачи. Услуги, сотрудники и календарь не обязательны.</p><button class="primary-button" data-new-assistant>Создать помощника</button></article>';
  return items.map(a=>`<article class="panel profile-card"><div class="profile-top"><span class="profile-icon">${CallwiseIcons.icon(a.profile==='support'?'book':'phone')}</span><span class="status-label ${a.status==='active'?'available':''}">${a.status==='active'?'Настроен для веб-теста':a.status==='valid'?'Проверен, ожидает активации':'Требует проверки'}</span></div><h3>${escapeHtml(a.company)}</h3><p>${a.profile==='support'?'Справочный помощник':'Секретарь'} · FAQ: ${a.faq_count}</p><p class="muted">Внешний канал не подключён</p><div class="profile-actions"><button class="secondary-button" data-product-edit="${escapeHtml(a.id)}">Изменить</button>${a.status==='active'?`<button class="primary-button" data-product-test="${escapeHtml(a.id)}">Тестовый разговор ${CallwiseIcons.icon('arrow')}</button>`:''}<button class="text-button" data-product-evaluation="${escapeHtml(a.id)}">Проверка сценариев</button></div></article>`).join('');
}
function bindProductActions(container=document){
  container.querySelectorAll('[data-new-assistant]').forEach(b=>b.onclick=()=>newQuickAssistant().catch(e=>showToast(e.message)));
  container.querySelectorAll('[data-product-view]').forEach(b=>b.onclick=()=>showView(b.dataset.productView));
  container.querySelectorAll('[data-product-edit]').forEach(b=>b.onclick=()=>editQuickAgent(b.dataset.productEdit).catch(e=>showToast(e.message)));
  container.querySelectorAll('[data-product-test]').forEach(b=>b.onclick=async()=>{try{await selectAgent(b.dataset.productTest);showView('call');}catch(e){showToast(e.message);}});
  container.querySelectorAll('[data-product-evaluation]').forEach(b=>b.onclick=()=>openEvaluation(b.dataset.productEvaluation).catch(e=>showToast(e.message)));
  CallwiseIcons.fill();
}
// Copy for each server-decided next step. The server owns the decision (state), the browser only words it.
const NEXT_STEPS={
  create:['Начните с понятной роли','Секретарь принимает обращение. Справочный помощник отвечает на вопросы без обязательного сбора контактов.','Создать помощника →','new'],
  finish_draft:['Завершите настройку помощника','Черновик сохранён, но ещё не подтверждён. Проверьте шаги мастера и подтвердите конфигурацию.','Продолжить настройку →','quick'],
  confirm_changes:['Подтвердите изменения','В черновике есть правки, которых нет у действующего помощника. Новые разговоры начнут использовать их только после подтверждения.','Открыть мастер →','quick'],
  activate:['Включите помощника для веб-теста','Настройки сохранены, но помощник ещё не выбран для проверки в браузере.','Открыть помощников →','assistant'],
  test_web:['Проведите первый тестовый разговор','Задайте известный и неизвестный вопрос в веб-проверке, затем посмотрите результат в истории.','Открыть помощников →','assistant'],
  improve_knowledge:['Проверьте историю и уточните знания','Посмотрите неотвеченные вопросы и добавьте ответы владельца. Новые знания применяются к новым разговорам.','Открыть помощников →','assistant']
};
function renderNextStep(step){
  const [title,text,label,view]=NEXT_STEPS[step?.code]||NEXT_STEPS.create;
  $('#nextStepTitle').textContent=title;$('#nextStepText').textContent=text;
  const button=$('#nextStepButton');button.textContent=label;button.dataset.nextView=view;
}
async function refreshProduct(){
  try{
    const data=await quickApi('/api/track1/overview');productAgents=data.agents;
    $('#metricAssistants').previousElementSibling.textContent='Помощники мастера';
    $('#metricConversations').nextElementSibling.textContent='Разговоры помощников мастера';
    for(const [id,key] of [['metricAssistants','assistants'],['metricConversations','conversations'],['metricConfirmed','confirmed'],['metricHuman','human_requests']])$('#'+id).textContent=data.counts[key];
    $('#productAgentList').innerHTML=productCards(productAgents);$('#overviewAgents').innerHTML=productCards(productAgents.slice(0,3));bindProductActions();
    renderNextStep(data.next_step);
    const knowledgeId=$('#knowledgeAgent').value, historyId=$('#historyAgent').value;
    const options=productAgents.map(a=>`<option value="${escapeHtml(a.id)}">${escapeHtml(a.company)}</option>`).join('');
    $('#knowledgeAgent').innerHTML='<option value="">Выберите помощника</option>'+options;
    $('#knowledgeAgent').value=productAgents.some(a=>a.id===knowledgeId)?knowledgeId:productAgents[0]?.id||'';
    $('#historyAgent').innerHTML='<option value="">Все помощники</option>'+options;
    if(productAgents.some(a=>a.id===historyId))$('#historyAgent').value=historyId;
    $('#telegramChannelBadge').textContent=data.local_only?'Отключён локально':'Привязка проверяется отдельно';
    $('#overviewError').textContent='';
  }catch(e){$('#overviewError').textContent='Не удалось загрузить кабинет: '+e.message;throw e;}
}
async function loadKnowledge(){
  const id=$('#knowledgeAgent').value;$('#knowledgeEdit').disabled=!id;
  if(!id){$('#knowledgeContent').innerHTML='<article class="panel empty-state"><b>Сначала создайте помощника</b><p>Здесь появятся подтверждённые факты и ответы.</p></article>';return;}
  const data=await quickApi('/api/track1/agents/'+encodeURIComponent(id)+'/settings');
  $('#knowledgeContent').innerHTML=(data.qa||[]).map(q=>`<article class="panel knowledge-card"><span class="eyebrow">FAQ · ПОДТВЕРЖДЁН ВЛАДЕЛЬЦЕМ</span><h3>${escapeHtml(q.question)}</h3><p>${escapeHtml(q.answer)}</p>${q.source?'<small>'+escapeHtml(q.source)+'</small>':''}</article>`).join('')+`<article class="panel knowledge-card"><span class="eyebrow">ОБЩИЕ ФАКТЫ</span><h3>Основа ответов</h3><p class="track1-facts">${escapeHtml(data.facts||'Факты пока не указаны. Помощник должен признать отсутствие информации.')}</p></article>`;
}
async function refreshProductView(name){await refreshProduct();if(name==='knowledge')await loadKnowledge();}
function shellDrafts(){
  const raw=localStorage.getItem('callwise-mts-shell-v1');if(!raw)return [];
  const saved=JSON.parse(raw);
  if(!Array.isArray(saved.agents)||saved.agents.length>100)throw new Error('Хранилище старого макета повреждено.');
  return saved.agents;
}
window.addEventListener('DOMContentLoaded',()=>{
  const nextButton=$('#nextStepButton');
  if(nextButton)nextButton.onclick=()=>{const view=nextButton.dataset.nextView;if(view==='new')newQuickAssistant().catch(e=>showToast(e.message));else if(view==='quick'){showView('quick');$('#quickRestore').click();}else showView(view||'assistant');};
  const integrationCard=document.createElement('article');integrationCard.className='panel channel-card';
  integrationCard.innerHTML='<span class="channel-symbol">▦</span><span class="status-label">Проверяется отдельно</span><h3>Календарь и CRM</h3><p>Google Calendar и Bitrix24. Проверка времени, подтверждение записи и отдельный статус передачи в CRM. Без доступа бизнеса облачная запись не выполняется.</p><a class="text-button" href="/static/integrations.html">Открыть подключения →</a>';
  document.querySelector('#view-channels .channel-grid').append(integrationCard);
  const reviewLink=document.createElement('a');reviewLink.className='text-button';reviewLink.href='/static/safety.html';reviewLink.textContent='Запросы менеджеру и границы защиты →';
  document.querySelector('#view-channels .privacy-panel').append(reviewLink);
  bindProductActions();refreshProduct().catch(e=>showToast(e.message));
  document.dispatchEvent(new Event('callwise:product-ready'));
  $('#knowledgeAgent').onchange=()=>loadKnowledge().catch(e=>showToast(e.message));
  $('#knowledgeEdit').onclick=async()=>{try{await editQuickAgent($('#knowledgeAgent').value);setQuickStep(2);}catch(e){showToast(e.message);}};
  $('#historyAgent').onchange=loadApplications;$('#historyState').onchange=loadApplications;$('#historySource').onchange=loadApplications;
  document.addEventListener('callwise:updated',()=>refreshProduct().catch(e=>showToast(e.message)));
  document.querySelector('.brand').onclick=event=>{event.preventDefault();showView('overview');};
  try{$('#shellImportOpen').hidden=!shellDrafts().length;}catch(_){}
  $('#shellImportOpen').onclick=()=>{
    try{const items=shellDrafts();$('#shellImportSelect').innerHTML=items.map((a,i)=>`<option value="${i}">${escapeHtml(String(a.name||a.company||'Черновик').slice(0,100))}</option>`).join('');$('#shellImportError').textContent='';$('#shellImportDialog').showModal();}catch(e){showToast(e.message);}
  };
  $('#shellImportCancel').onclick=()=>$('#shellImportDialog').close();
  $('#shellImportBegin').onclick=async()=>{
    try{const data=CallwiseDraftImport.convert(shellDrafts()[Number($('#shellImportSelect').value)]);await newQuickAssistant();fillQuick(data);setQuickStep(0);quickChanged();$('#quickStatus').textContent='Перенесён только черновик. Проверьте компанию, роль, знания и ограничения перед подтверждением.';$('#shellImportDialog').close();}catch(e){$('#shellImportError').textContent=e.message;}
  };
});
