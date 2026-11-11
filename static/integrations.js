'use strict';
const labels={pending:'Ожидает передачи',confirmed:'Подтверждена календарём',synced:'Передано в CRM',unknown:'Результат неизвестен — нужна сверка',failed:'Ошибка — нужна проверка',not_configured:'CRM не настроена',disabled:'Отключено',configured_unverified:'Настроено, ещё не проверено',credentials_missing:'Не хватает доступа'};
let refreshing=false, enabled=false;
function element(tag,text,className){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(className)node.className=className;return node;}
async function api(path,method='GET'){
  const response=await fetch('/api/integrations/'+path,{method,signal:AbortSignal.timeout(60000),credentials:'same-origin'});
  const data=await response.json();if(!response.ok)throw new Error(data.detail||'Не удалось получить статус.');return data;
}
function badge(value){return element('span',labels[value]||value,'status-label '+(['confirmed','synced'].includes(value)?'available':''));}
async function refresh(){
  if(refreshing)return;refreshing=true;document.getElementById('refresh').disabled=true;
  try{
    const [status,data]=await Promise.all([api('status'),api('bookings')]);
    enabled=status.status==='enabled_unverified';
    document.getElementById('notice').textContent=status.status==='invalid_config'?'Файл подключений содержит ошибку. Проверьте настройки владельца.':enabled?'Облачные интеграции разрешены. Наличие настроек ещё не подтверждает доступ.':'Облачные подключения отключены. Сейчас внешние записи не создаются.';
    const agents=document.getElementById('agents');agents.replaceChildren();
    if(!status.agents.length)agents.append(element('p','Пока ни один бизнес не подключён. Ключи и аккаунты не заданы.'));
    for(const item of status.agents){const row=element('article',undefined,'row');row.append(element('h3',item.agent_id),badge(item.status),element('p','Google Calendar · ресурсов: '+item.resources.length+' · '+(item.crm?'Bitrix24: '+(item.crm_credentials_present?'доступ задан, не проверен':'доступ не задан'):'Без CRM')));agents.append(row);}
    const bookings=document.getElementById('bookings');bookings.replaceChildren();
    if(!data.bookings.length)bookings.append(element('p','Облачных записей пока нет. Здесь не показывается вымышленная успешная синхронизация.'));
    for(const item of data.bookings){const row=element('article',undefined,'row');row.append(element('h3',item.agent_id),badge(item.calendar_status),badge(item.crm_status),element('p','ID: '+item.id,'muted'));
      if(item.error_code)row.append(element('p','Код проверки: '+item.error_code));
      if(item.calendar_status!=='confirmed'||!['synced','not_configured'].includes(item.crm_status)){
        const button=element('button','Сверить и продолжить передачу','secondary-button');button.type='button';button.disabled=!enabled;
        button.onclick=async()=>{button.disabled=true;try{await api('bookings/'+encodeURIComponent(item.id)+'/reconcile','POST');await refresh();}catch(error){document.getElementById('notice').textContent=error.message;button.disabled=!enabled;}};row.append(button);
      }bookings.append(row);
    }
  }catch(error){document.getElementById('notice').textContent=error.message;}
  finally{refreshing=false;document.getElementById('refresh').disabled=false;}
}
document.getElementById('refresh').addEventListener('click',refresh);refresh();
