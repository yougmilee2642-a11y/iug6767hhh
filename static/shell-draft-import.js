// Explicit, draft-only conversion. Never imports active state, IDs or tool policy.
(function(root){
  function bounded(value,label,max){const text=String(value??'').trim();if(text.length>max)throw new Error(label+': превышен лимит '+max+' символов. Сократите исходный черновик.');return text;}
  function convert(agent){
    if(!agent||typeof agent!=='object')throw new Error('Черновик не найден');
    const roles={'Сбор обращений':'secretary','Поддержка клиентов':'support','Информация об услугах':'support'};
    const role=roles[agent.role];if(!role)throw new Error('Эта роль требует ручной настройки в мастере.');
    const qa=agent.qa??[];if(!Array.isArray(qa)||qa.length>10)throw new Error('Мастер принимает до 10 вопросов. Сократите исходный черновик.');
    const data={business_name:bounded(agent.company,'Компания',100),business_type:'Компания',city:'',role,
      greeting:bounded(agent.greeting,'Приветствие',450),facts:bounded(agent.knowledge,'Факты',3000),
      tone:({'Дружелюбный':'friendly','Деловой':'formal','Нейтральный':'brief'})[agent.tone]||'brief',
      timezone:'Europe/Minsk',routing_preference:'unspecified',
      qa:qa.map(q=>({question:bounded(q.question,'Вопрос',240),answer:bounded(q.answer,'Ответ',1200),source:bounded(q.source,'Источник',200)}))};
    if(data.business_name.length<2)throw new Error('Укажите название компании минимум из двух символов.');
    if(data.facts.length+data.qa.reduce((n,q)=>n+q.question.length+q.answer.length+q.source.length,0)>6500)throw new Error('Сократите совокупные знания до 6500 символов.');
    return data;
  }
  if(typeof module==='object'&&module.exports)module.exports={convert};else root.CallwiseDraftImport={convert};
})(typeof window==='object'?window:globalThis);
