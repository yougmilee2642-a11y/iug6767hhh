document.querySelector('#loginForm').onsubmit=async event=>{
  event.preventDefault();const form=event.target,button=form.querySelector('button');button.disabled=true;
  try{const response=await fetch('/api/access/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:form.elements.password.value})});const data=await response.json();form.elements.password.value='';if(!response.ok)throw new Error(data.detail||'Не удалось войти');location.assign('/#quick');}
  catch(error){document.querySelector('#loginStatus').textContent=error.message;}
  finally{button.disabled=false;}
};
