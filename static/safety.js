'use strict';
const reasonLabels={refused_ai:'Отказ от общения с AI',change_or_late:'Изменение записи / опоздание',unsupported:'Нестандартный запрос',callback:'Просьба перезвонить',audio_quality:'Проблема со звуком',privacy_withdrawn:'Отзыв согласия'};
const statusLabels={pending:'Ожидает проверки',in_review:'На проверке',resolved:'Решён менеджером'};
function node(tag,text){const item=document.createElement(tag);if(text!==undefined)item.textContent=text;return item;}
async function api(path,options={}){const response=await fetch('/api/safety/'+path,{...options,credentials:'same-origin',signal:AbortSignal.timeout(15000)});const data=await response.json();if(!response.ok)throw new Error(data.detail||'Не удалось получить данные.');return data;}
async function refresh(){
 const button=document.getElementById('refresh');button.disabled=true;
 try{const [status,data]=await Promise.all([api('status'),api('reviews')]);
 document.getElementById('notice').textContent=status.enabled?'Защиты разговора включены. Телефонные действия не выполняются.':'Защиты разговора отключены в настройках сервера.';
 const list=document.getElementById('reviews');list.replaceChildren();if(!data.items.length)list.append(node('p','Запросов пока нет.'));
 for(const item of data.items){const row=node('article');row.className='review-row';row.append(node('h3',reasonLabels[item.reason]||item.reason),node('p','Помощник: '+item.agent_id),node('p','Разговор: '+item.interaction_id));
 const select=node('select');select.setAttribute('aria-label','Статус запроса '+item.id);
 for(const value of Object.keys(statusLabels)){const option=node('option',statusLabels[value]);option.value=value;select.append(option);}select.value=item.status;
 const save=node('button','Сохранить статус');save.className='secondary-button';save.onclick=async()=>{save.disabled=true;try{await api('reviews/'+item.id,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({status:select.value})});document.getElementById('notice').textContent='Статус обновлён. Изменения CRM/календаря и звонок этим действием не выполнялись.';}catch(error){document.getElementById('notice').textContent=error.message;}finally{save.disabled=false;}};
 row.append(select,save);list.append(row);}}
 catch(error){document.getElementById('notice').textContent=error.message;}
 finally{button.disabled=false;}
}
document.getElementById('refresh').onclick=refresh;refresh();
