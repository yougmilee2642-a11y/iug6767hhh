// Explicit choice before microphone capture. No preselected consent or silent acceptance.
export function askPrivacy(privacy, signal) {
  return new Promise((resolve) => {
    if(signal?.aborted){resolve(false);return;}
    const dialog=document.createElement('dialog');
    dialog.setAttribute('aria-labelledby','callwisePrivacyTitle');
    dialog.style.cssText='max-width:620px;width:calc(100% - 32px);border:1px solid #ddd;border-radius:18px;padding:28px;color:#202026;background:white;font:15px/1.6 Segoe UI,Arial,sans-serif';
    const title=document.createElement('h2');title.id='callwisePrivacyTitle';title.textContent='До начала разговора';
    const notice=document.createElement('p');notice.textContent=privacy.notice;
    const note=document.createElement('small');note.textContent='Версия уведомления: '+privacy.version;
    const actions=document.createElement('div');actions.style.cssText='display:flex;gap:12px;flex-wrap:wrap;margin-top:22px';
    const no=document.createElement('button');no.type='button';no.className='secondary-button';no.textContent='Не согласен — завершить';
    const yes=document.createElement('button');yes.type='button';yes.className='primary-button';yes.textContent='Согласен — начать демо';
    for(const button of [no,yes])button.style.cssText='padding:12px 16px;border-radius:10px;border:1px solid #ccc;cursor:pointer';
    yes.style.background='#e30611';yes.style.color='white';
    actions.append(no,yes);dialog.append(title,notice,note,actions);document.body.append(dialog);
    let settled=false;
    function finish(value){if(settled)return;settled=true;signal?.removeEventListener('abort',abort);dialog.close();dialog.remove();resolve(value);}
    function abort(){finish(false);}
    no.onclick=()=>finish(false);yes.onclick=()=>finish(true);
    dialog.addEventListener('cancel',event=>{event.preventDefault();finish(false);});
    signal?.addEventListener('abort',abort,{once:true});dialog.showModal();no.focus();
  });
}
