const originalFetch=window.fetch.bind(window);
window.fetch=async(...args)=>{
  const response=await originalFetch(...args);
  if(response.status===401 && String(args[0]).startsWith('/api/') && !String(args[0]).startsWith('/api/miniapp/')) location.assign('/login');
  return response;
};
window.addEventListener('DOMContentLoaded',async()=>{
  try{const response=await fetch('/api/access/status');if(!response.ok)return;const data=await response.json();document.querySelector('#accessNote').textContent=data.mode==='single_owner'?'Кабинет одного владельца защищён паролем.':'Кабинет доступен на этом компьютере. Внешний доступ пока не настроен.';document.querySelector('#ownerLogout').hidden=data.mode!=='single_owner';}catch(_){}
});
document.querySelector('#ownerLogout').onclick=async()=>{await fetch('/api/access/logout',{method:'POST'});location.assign('/login');};
