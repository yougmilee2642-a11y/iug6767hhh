let telegramLink=null;
let telegramBusy=false;
const workerLabels={ready:'Бот работает',offline:'Бот не запущен',starting:'Запускается',error:'Ошибка бота'};
const tgErrors={invalid_token:'Токен не принят',polling_conflict:'Этот бот уже опрашивается другим процессом',webhook_active:'У бота уже задан webhook. Callwise не отключает его автоматически.',unknown_delivery:'Нет подтверждённого ответа Telegram',forbidden:'Бот заблокирован получателем'};

async function refreshTelegramPanel(){
  const select=$('#telegramAgent');const previous=select.value||selectedAgentId;
  const items=(await builderApi('/api/agents')).items.filter(agent=>agent.source==='track1');
  select.innerHTML='<option value="">Выберите помощника</option>'+items.map(agent=>`<option value="${escapeHtml(agent.id)}">${escapeHtml(agent.name)}</option>`).join('');
  if(items.some(agent=>agent.id===previous))select.value=previous;
  await telegramStatus();
}
async function telegramStatus(){
  const data=await builderApi('/api/telegram/status?agent_id='+encodeURIComponent($('#telegramAgent').value));
  if(data.local_only){
    $('#telegramState').textContent='Telegram намеренно отключён для полностью локальных AI-тестов.';
    $('#telegramRecipient').textContent='Регистрация и исходный бот сохранены в прежнем проекте. Локальная копия не использует его токен.';
    $('#telegramMiniapp').textContent='Mini App недоступен в этом режиме. Здесь тестируем локальные речь и диалог.';
    $('#telegramConnect').disabled=true;$('#telegramDisconnect').hidden=true;
    return;
  }
  $('#telegramState').textContent=!data.configured?'Токен не задан или бот отключён. Добавьте TELEGRAM_BOT_TOKEN в .env и перезапустите Callwise.':`${workerLabels[data.worker]||data.worker}${data.username?' · @'+data.username:''}${data.error?' · '+(tgErrors[data.error]||'Проверьте настройки'):''}`;
  $('#telegramRecipient').textContent=data.connected?`Получатель: ${data.recipient.label} · Telegram ID ${data.recipient.chat_id}`:'Получатель не привязан к этому агенту.';
  $('#telegramMiniapp').textContent=data.miniapp_ready?'HTTPS-адрес Mini App задан. /register покажет кнопку регистрации.':'Mini App пока только локально. Регистрация уже доступна в переписке: /register.';
  $('#telegramConnect').disabled=!$('#telegramAgent').value||data.worker!=='ready'||!data.configured;
  $('#telegramDisconnect').hidden=!data.connected;
}
async function tgAction(fn){
  if(telegramBusy)return;telegramBusy=true;
  for(const button of $('#view-telegram').querySelectorAll('button'))button.disabled=true;
  try{await fn();}catch(error){$('#telegramActionStatus').textContent=error.message;}
  finally{telegramBusy=false;await telegramStatus().catch(()=>{});$('#telegramRefresh').disabled=false;$('#telegramCheck').disabled=false;$('#telegramApprove').disabled=false;$('#telegramDisconnect').disabled=false;}
}
$('#telegramConnect').onclick=()=>tgAction(async()=>{
  telegramLink=await builderApi('/api/telegram/link',{agent_id:$('#telegramAgent').value});
  const anchor=$('#telegramLink');anchor.href=telegramLink.url;anchor.textContent='Открыть бота и нажать Start';anchor.hidden=false;
  $('#telegramCheck').hidden=false;$('#telegramApprove').hidden=true;
  $('#telegramActionStatus').textContent='Ссылка действует 10 минут. Не передавайте её другим. После Start вернитесь сюда и проверьте получателя.';
});
$('#telegramCheck').onclick=()=>tgAction(async()=>{
  if(!telegramLink)return;
  const data=await builderApi('/api/telegram/link/status',{agent_id:$('#telegramAgent').value,link_id:telegramLink.link_id});
  $('#telegramActionStatus').textContent=data.pending_recipient?`Проверьте: ${data.pending_recipient.label} · Telegram ID ${data.pending_recipient.chat_id}. Подтверждение разрешит отправлять обращения этому получателю.`:'Ожидаем Start по одноразовой ссылке.';
  $('#telegramApprove').hidden=!data.pending_recipient;
});
$('#telegramApprove').onclick=()=>tgAction(async()=>{
  if(!telegramLink)return;
  await builderApi('/api/telegram/link/approve',{agent_id:$('#telegramAgent').value,link_id:telegramLink.link_id});
  telegramLink=null;$('#telegramLink').hidden=true;$('#telegramCheck').hidden=true;$('#telegramApprove').hidden=true;
  $('#telegramActionStatus').textContent='Привязка подтверждена. Только новые подтверждённые обращения пойдут в очередь. Старые не отправляются.';
});
$('#telegramDisconnect').onclick=()=>tgAction(async()=>{await builderApi('/api/telegram/disconnect',{agent_id:$('#telegramAgent').value});$('#telegramActionStatus').textContent='Получатель отключён. Ожидающие отправки отменены. Уже отправленные сообщения не удаляются.';});
$('#telegramRefresh').onclick=()=>tgAction(()=>refreshTelegramPanel());
$('#telegramAgent').onchange=()=>{telegramLink=null;$('#telegramLink').hidden=true;$('#telegramCheck').hidden=true;$('#telegramApprove').hidden=true;telegramStatus().catch(error=>$('#telegramActionStatus').textContent=error.message);};
