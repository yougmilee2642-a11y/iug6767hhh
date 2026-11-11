const miniForm=document.querySelector('#registrationForm');
const miniStatus=document.querySelector('#miniStatus');
const miniSubmit=document.querySelector('#registerSubmit');
const telegramApp=window.Telegram?.WebApp;
const rawInit=telegramApp?.initData||'';
let miniBusy=false;

async function miniApi(path,body){
  const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({init_data:rawInit,...body})});
  const data=await response.json();
  if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'Проверьте данные регистрации');
  return data;
}
function renderProfile(profile){
  miniForm.hidden=true;document.querySelector('#miniProfile').hidden=false;
  document.querySelector('#profileDetails').textContent=`${profile.display_name}\n${profile.business_name}`;
  miniForm.elements.display_name.value=profile.display_name;miniForm.elements.business_name.value=profile.business_name;
  miniForm.elements.consent.checked=false;
  miniStatus.textContent='Telegram ID проверен на сервере. Профиль сохранён.';
}
miniForm.onsubmit=async event=>{
  event.preventDefault();if(miniBusy||!rawInit||!miniForm.reportValidity())return;
  miniBusy=true;miniSubmit.disabled=true;
  try{const result=await miniApi('/api/miniapp/register',{display_name:miniForm.elements.display_name.value.trim(),business_name:miniForm.elements.business_name.value.trim(),consent:miniForm.elements.consent.checked});renderProfile(result.profile);}
  catch(error){miniStatus.textContent=error.message;}
  finally{miniBusy=false;miniSubmit.disabled=false;}
};
document.querySelector('#editProfile').onclick=()=>{miniForm.hidden=false;document.querySelector('#miniProfile').hidden=true;miniStatus.textContent='Измените профиль и подтвердите сохранение.';};
async function initializeMini(){
  if(!rawInit){miniStatus.textContent='Локальный предпросмотр. Для регистрации откройте Mini App из Telegram-бота. Без проверенной Telegram-сессии сохранение запрещено.';return;}
  telegramApp.ready();telegramApp.expand();
  try{const result=await miniApi('/api/miniapp/profile',{});miniSubmit.disabled=false;if(result.profile)renderProfile(result.profile);else{miniStatus.textContent='Сессия Telegram проверена. Заполните профиль.';miniForm.elements.display_name.value=result.telegram_name||'';}}
  catch(error){miniStatus.textContent=error.message;}
}
initializeMini();
