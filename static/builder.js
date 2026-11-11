let builderStep = 0;
let builderCandidate = null;
let builderBusy = false;
let builderContract = null;
let builderRequirementCatalog = {};
const polarityLabels = {required:'Обязательно',forbidden:'Запрещено',not_requested:'Не требуется',unknown:'Нужно уточнить'};
const builderDays = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];

async function builderApi(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail?.errors?.map(e=>e.message).join('; ') || (typeof data.detail === 'string' ? data.detail : 'Проверьте введённые данные'));
  return data;
}

async function selectAgent(id) {
  if (starting || finishing) { $('#agentSelect').value = selectedAgentId; throw new Error('Дождитесь завершения запуска или остановки разговора'); }
  // Switching assistant ends the current call: requests, playback and the microphone are released and the conversation is saved.
  if (active) await finish(false);
  const item = await builderApi('/api/agents/' + encodeURIComponent(id));
  selectedAgentId = item.id;
  selectedAgentConfig = item.config;
  selectedAgentSource = item.source;
  try {localStorage.setItem('callwiseSelectedAgent', id);}catch(_){}
  $('#agentSelect').value = id;
  updateBusinessPreview();
}

async function loadAgentChoices(preferred) {
  const {items} = await builderApi('/api/agents');
  const enabled = items.filter(a => a.status === 'active');
  $('#agentSelect').innerHTML = enabled.map(a=>`<option value="${escapeHtml(a.id)}">${escapeHtml(a.name)}${a.source === 'demo' ? ' · демо' : ''}</option>`).join('');
  let remembered = null; try {remembered=localStorage.getItem('callwiseSelectedAgent');}catch(_){}
  const candidateId = preferred || selectedAgentId || remembered;
  const id = enabled.some(a=>a.id===candidateId) ? candidateId : enabled.find(a=>a.source==='track1')?.id || enabled.find(a=>a.source==='demo')?.id || enabled[0]?.id;
  if (active || starting || finishing) $('#agentSelect').value = selectedAgentId;
  if (id && !active && !starting && !finishing) await selectAgent(id);
}

async function loadAgentList() {
  const {items} = await builderApi('/api/agents');
  const statuses = {active:'Активен',valid:'Проверен, не активирован',invalid:'Невалиден',draft:'Черновик'};
  $('#agentList').innerHTML = items.map(a=>`<article class="panel agent-entry"><h3>${escapeHtml(a.name)}</h3><p>${statuses[a.status] || escapeHtml(a.status)} · ${a.source === 'demo' ? 'Демо' : a.source === 'track1' ? 'Трек 1 · настроен для веб-теста' : 'Создан в конструкторе'}</p>${a.status==='active' ? `<button class="secondary-button" data-use-agent="${escapeHtml(a.id)}">Выбрать для разговора</button>` : a.status==='valid' ? `<button class="primary-button" data-activate-agent="${escapeHtml(a.id)}">Активировать</button>` : ''}${['builder','track1'].includes(a.source)?`<button class="secondary-button" data-check-agent="${escapeHtml(a.id)}">Проверить агента</button>`:''}${a.source==='track1'?`<button class="secondary-button" data-edit-quick="${escapeHtml(a.id)}">Изменить настройки</button><p>Телефония не подключена. Telegram настраивается отдельно. Проверка сценариев доступна отдельно; она не подтверждает подключение услуги.</p>`:''}</article>`).join('');
  $$('[data-edit-quick]').forEach(b=>b.onclick=()=>editQuickAgent(b.dataset.editQuick).catch(e=>showToast(e.message)));
  $$('[data-check-agent]').forEach(b=>b.onclick=()=>openEvaluation(b.dataset.checkAgent).catch(e=>showToast(e.message)));
  $$('[data-use-agent]').forEach(b=>b.onclick=async()=>{try{await selectAgent(b.dataset.useAgent);showView('call');}catch(e){showToast(e.message);}});
  $$('[data-activate-agent]').forEach(b=>b.onclick=async()=>{try{await builderApi(`/api/agents/${b.dataset.activateAgent}/activate`,{});await loadAgentChoices(b.dataset.activateAgent);await loadAgentList();}catch(e){showToast(e.message);}});
}

function addBuilderService(item = {}) {
  const row = document.createElement('div'); row.className='builder-service-row';
row.innerHTML = `<label>Услуга<input data-service="name" value="${escapeHtml(item.name || '')}" maxlength="100" required></label><label>Цена<input data-service="price" type="number" min="0" step="0.01" value="${escapeHtml(item.price ?? 0)}" required></label><label>Валюта<input data-service="currency" maxlength="3" value="${escapeHtml(item.currency || 'BYN')}" required></label><label>Минут<input data-service="duration_minutes" type="number" min="1" max="1440" value="${escapeHtml(item.duration_minutes || 60)}" required></label><button type="button" class="secondary-button" aria-label="Удалить услугу">×</button>`;
  row.querySelector('button').onclick=()=>{row.remove();persistBuilderForm();};
  const selection = document.createElement('div'); selection.className='builder-service-employees';
  row.append(selection);
  row._employeeSelection = item.employees || [];
  $('#builderServices').append(row);
  refreshBuilderEmployees();
}

function normalizedEmployee(value) {return value.normalize('NFKC').toLocaleLowerCase('ru').replaceAll('ё','е').trim().replace(/\s+/g,' ');}
function refreshBuilderEmployees() {
  const names = [...new Map($('#builderForm').elements.employees.value.split('\n').map(s=>s.trim()).filter(Boolean).map(s=>[normalizedEmployee(s),s])).values()];
  $$('.builder-service-row').forEach(row=>{
    const selected = new Set((row._employeeSelection || []).map(normalizedEmployee));
    const known = new Set(names.map(normalizedEmployee));
    const missing = (row._employeeSelection || []).filter(name=>!known.has(normalizedEmployee(name)));
    row.querySelector('.builder-service-employees').innerHTML = '<span>Сотрудники услуги (не отмечены — все)</span>' + [...names,...missing].map(name=>`<label><input type="checkbox" data-service-employee value="${escapeHtml(name)}" ${selected.has(normalizedEmployee(name))?'checked':''}>${escapeHtml(name)}${known.has(normalizedEmployee(name))?'':' · отсутствует в каталоге'}</label>`).join('');
    row.querySelectorAll('[data-service-employee]').forEach(input=>input.onchange=()=>{
      row._employeeSelection = [...row.querySelectorAll('[data-service-employee]:checked')].map(i=>i.value);
      persistBuilderForm();
    });
  });
}

function readBuilderForm() {
  const form = $('#builderForm'); const f = name=>form.elements[name].value.trim();
  const schedule = {};
  $$('.builder-hours-row').forEach((row,d)=>{schedule[d]=row.querySelector('[data-closed]').checked ? [] : [{start:row.querySelector('[data-start]').value,end:row.querySelector('[data-end]').value}];});
  const services = $$('.builder-service-row').map(row=>({...Object.fromEntries([...row.querySelectorAll('[data-service]')].map(i=>[i.dataset.service,['price','duration_minutes'].includes(i.dataset.service)?Number(i.value):i.value.trim()])),employees:[...row.querySelectorAll('[data-service-employee]:checked')].map(i=>i.value)}));
  return {business_name:f('business_name'),business_type:f('business_type'),city:f('city'),timezone:f('timezone'),description:f('description'),website:f('website'),schedule,services,employees:f('employees').split('\n').map(s=>s.trim()).filter(Boolean),desired_role:f('desired_role'),tasks:f('tasks').split('\n').map(s=>s.trim()).filter(Boolean),notes:f('notes'),escalation_preferences:$$('[name=escalation]:checked').map(i=>i.value)};
}

function persistBuilderForm() { try {localStorage.setItem('callwiseBuilderInput',JSON.stringify(readBuilderForm()));}catch(_){} }
function changeBuilderStep(step) {
  builderStep=step;
  $$('.builder-step').forEach(s=>s.hidden=Number(s.dataset.step)!==step);
$('#builderStepLabel').textContent=`Шаг ${step+1} из 4 · ${['Компания и часы','Роль и задачи','Услуги и сотрудники','Проверка черновика'][step]}`;
  $('#builderBack').hidden=step===0;
  $('#builderNext').hidden=step>=2;
  $('#builderGenerate').hidden=step!==2;
  $('#builderCreate').hidden=step!==3 || !builderCandidate?.validation.valid;
}
function validateBuilderStep() {
  const section = $(`.builder-step[data-step="${builderStep}"]`);
  for (const input of section.querySelectorAll('input,textarea')) {if(!input.checkValidity()){input.reportValidity();return false;}}
  return true;
}

function renderBuilderPreview(result) {
  const report=result.validation;
  let html=report.errors.length ? '<h3>Ошибки — создание невозможно</h3>' : '';
  if(result.requirement_contract) html+='<h3>Договор требований</h3><p>Создание агента подтверждает эти требования вместе с конфигурацией.</p><ul>'+result.requirement_contract.entries.map(e=>`<li>${escapeHtml(e.source_text)} → ${escapeHtml(builderRequirementCatalog[e.requirement_id]||e.requirement_id)}: ${polarityLabels[e.polarity]}</li>`).join('')+'</ul>';
  html+=report.errors.map(e=>`<div class="builder-error">${escapeHtml(e.message)}</div>`).join('');
  if(report.warnings.length) html+='<h3>Предупреждения — проверьте перед созданием</h3>';
  html+=report.warnings.map(w=>`<div class="builder-warning">${escapeHtml(w.code === 'declarative_contracts' ? 'Техническая проверка пройдена, но она не оценивает качество общения. Проверьте способности и данные агента.' : w.message)}</div>`).join('');
if(result.preview){const p=result.preview;html+=`<h3>${escapeHtml(p.name)}</h3><p>${escapeHtml(p.business_name)} · ${escapeHtml(p.role)}</p><div class="builder-preview-grid"><div><h3>Что умеет</h3><ul>${p.abilities.map(v=>`<li>${escapeHtml(v)}</li>`).join('')}</ul><h3>Что спросит</h3><ul>${p.fields.map(v=>`<li>${escapeHtml(v.label)}${v.required?' · обязательно':''}: ${escapeHtml(v.question)}</li>`).join('')}</ul><h3>Передача сотруднику</h3><p>${escapeHtml(p.human_request)}</p><p>По инициативе AI: ${p.escalation_reasons.map(v=>({complaint:'жалоба',unsupported_scenario:'неподдерживаемый запрос',tool_failure:'ошибка инструмента'}[v])).join(', ') || 'отключена'}</p></div><div><h3>Рабочие часы</h3><p>${escapeHtml(p.timezone)}</p><ul>${p.hours.map(v=>`<li>${escapeHtml(v)}</li>`).join('')}</ul><h3>Услуги</h3><ul>${p.services.map(s=>`<li>${escapeHtml(s.name)} · ${s.price} ${escapeHtml(s.currency)} · ${s.duration_minutes} мин.</li>`).join('')}</ul><h3>Сотрудники</h3><p>${p.employees.map(e=>escapeHtml(e.name)).join(', ')}</p></div></div>`;}
  if(result.config) html+=`<details><summary>Технические данные (только просмотр)</summary><pre>${escapeHtml(JSON.stringify(result.config,null,2))}</pre></details>`;
  $('#builderPreview').innerHTML=html;
}

async function generateBuilder() {
  if(builderBusy || !validateBuilderStep())return;
  persistBuilderForm(); builderBusy=true; $('#builderGenerate').disabled=true;
  $('#builderStatus').textContent='Формирую и проверяю черновик…';
  try{
    if(!builderContract){
      const resolved=await builderApi('/api/builder/requirements',readBuilderForm());builderContract=resolved.contract;builderRequirementCatalog=resolved.catalog;
      $('#builderRequirements').hidden=false;
      $('#builderRequirements').innerHTML='<h3>Как поняты задачи</h3><p>Проверьте тип и обязательность. Исправьте неоднозначности до сборки агента.</p>'+builderContract.entries.map((e,i)=>`<div class="requirement-review"><p>${escapeHtml(e.source_text)}</p><label>Задача <select data-requirement-id="${i}">${Object.entries(resolved.catalog).map(([id,label])=>`<option value="${id}" ${id===e.requirement_id?'selected':''}>${escapeHtml(label)}</option>`).join('')}</select></label><label>Обязательность <select data-requirement-polarity="${i}">${Object.entries(polarityLabels).map(([id,label])=>`<option value="${id}" ${id===e.polarity?'selected':''}>${label}</option>`).join('')}</select></label></div>`).join('');
      $('#builderGenerate').textContent='Подтвердить требования и сформировать';$('#builderStatus').textContent='Проверьте договор требований выше. Сборка AI ещё не запускалась.';return;
    }
    $$('[data-requirement-id]').forEach(e=>builderContract.entries[Number(e.dataset.requirementId)].requirement_id=e.value);
    $$('[data-requirement-polarity]').forEach(e=>builderContract.entries[Number(e.dataset.requirementPolarity)].polarity=e.value);
    builderCandidate=await builderApi('/api/builder/generate',{...readBuilderForm(),requirement_contract:builderContract});renderBuilderPreview(builderCandidate);changeBuilderStep(3);$('#builderStatus').textContent=builderCandidate.validation.valid?'Черновик прошёл проверку. Проверьте сведения перед созданием.':'Черновик не прошёл проверку. Исправьте данные и попробуйте снова.';
  }
  catch(e){$('#builderStatus').textContent=e.message;}
  finally{builderBusy=false;$('#builderGenerate').disabled=false;}
}

async function createBuilderAgent() {
  if(builderBusy || !builderCandidate?.validation.valid)return;
  builderBusy=true;$('#builderCreate').disabled=true;
  try{
    const saved=await builderApi('/api/agents',{candidate_id:builderCandidate.candidate_id,review_token:builderCandidate.review_token});
    await builderApi(`/api/agents/${saved.id}/activate`,{});
    await loadAgentChoices(saved.id);await loadAgentList();
    $('#builderStatus').textContent='Агент создан и активирован. В списке можно проверить его перед использованием.';
    builderCandidate=null;$('#builderCreate').hidden=true;showToast('AI-сотрудник создан');
  }catch(e){$('#builderStatus').textContent=e.message;}finally{builderBusy=false;$('#builderCreate').disabled=false;}
}

window.addEventListener('DOMContentLoaded',()=>{
  $('#builderHours').innerHTML=builderDays.map((name,d)=>`<div class="builder-hours-row"><b>${name}</b><label><input type="checkbox" data-closed ${d===6?'checked':''}> Выходной</label><input data-start type="time" value="${d===5?'10:00':'09:00'}" aria-label="${name}: начало"><input data-end type="time" value="${d===5?'18:00':'20:00'}" aria-label="${name}: конец"></div>`).join('');
  let stored=null;try{stored=JSON.parse(localStorage.getItem('callwiseBuilderInput'));}catch(_){}
  if(stored){const form=$('#builderForm');for(const [k,v] of Object.entries(stored)){if(['employees','tasks'].includes(k))form.elements[k].value=v.join('\n');else if(form.elements[k]?.type)form.elements[k].value=v;}for(let d=0;d<7;d++){const row=$$('.builder-hours-row')[d],w=stored.schedule?.[d]?.[0];row.querySelector('[data-closed]').checked=!w;if(w){row.querySelector('[data-start]').value=w.start;row.querySelector('[data-end]').value=w.end;}}(stored.services||[]).forEach(addBuilderService);$$('[name=escalation]').forEach(i=>i.checked=(stored.escalation_preferences||[]).includes(i.value));}
  if(!$('.builder-service-row'))addBuilderService();
  changeBuilderStep(0);
  $('#newAgent').onclick=()=>{$('#builderPanel').hidden=false;changeBuilderStep(0);$('#builderPanel').scrollIntoView({behavior:'smooth'});};
  $('#builderAddService').onclick=()=>addBuilderService();
  $('#builderNext').onclick=()=>{if(validateBuilderStep()){persistBuilderForm();changeBuilderStep(builderStep+1);}};
  $('#builderBack').onclick=()=>{if(!builderBusy)changeBuilderStep(builderStep-1);};
  $('#builderGenerate').onclick=generateBuilder;$('#builderCreate').onclick=createBuilderAgent;
  $('#builderForm').onsubmit=e=>e.preventDefault();$('#builderForm').addEventListener('input',e=>{if(e.target.closest('#builderRequirements'))return;if(e.target.name==='employees')refreshBuilderEmployees();persistBuilderForm();builderCandidate=null;builderContract=null;$('#builderRequirements').hidden=true;$('#builderGenerate').textContent='Сформировать черновик';$('#builderCreate').hidden=true;});
  $('#agentSelect').onchange=e=>selectAgent(e.target.value).catch(error=>showToast(error.message));
});
