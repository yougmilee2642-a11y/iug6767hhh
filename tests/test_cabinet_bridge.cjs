const test=require('node:test');const assert=require('node:assert/strict');const {convert}=require('../static/shell-draft-import.js');
test('legacy shell deep links resolve to one real workspace',async()=>{
 const {cabinetTarget}=await import('../static/cabinet-links.mjs');
 assert.equal(cabinetTarget('#cabinet/agents'),'/#assistant');
 assert.equal(cabinetTarget('#cabinet/history'),'/#applications');
 assert.equal(cabinetTarget('#cabinet/agent/private-id'),'/#assistant');
 assert.equal(cabinetTarget('#cabinet/anything'),'/#overview');
 assert.equal(cabinetTarget('#home/demo'),null);
});
test('import copies only a reviewable draft, without IDs or active state',()=>{
 const input={id:'old',company:'Тестовая компания',role:'Сбор обращений',status:'active',tools:['refund'],voice:'secret',greeting:'Здравствуйте',qa:[{question:'Цена?',answer:'50 BYN',source:'Прайс'}]};
 const data=convert(input);assert.equal(data.role,'secretary');assert.equal(data.qa[0].answer,'50 BYN');
 for(const key of ['id','agent_id','status','tools','voice'])assert.equal(data[key],undefined);
 assert.equal(input.status,'active');
});
test('import rejects excessive context and unsupported roles without truncation',()=>{
 const input={company:'Тест',role:'Поддержка клиентов',qa:[]};
 assert.throws(()=>convert({...input,knowledge:'x'.repeat(3001)}),/лимит/);
 assert.throws(()=>convert({...input,qa:Array.from({length:11},()=>({question:'Q',answer:'A'}))}),/10 вопросов/);
 assert.throws(()=>convert({...input,role:'Продавец'}),/роль/);
 assert.throws(()=>convert({...input,qa:[{question:'Q',answer:'x'.repeat(1201)}]}),/лимит/);
});
test('an incomplete FAQ remains incomplete and cannot be silently auto-approved',()=>{
 const data=convert({company:'Тест',role:'Поддержка клиентов',qa:[{question:'Доставка?',answer:''}]});
 assert.equal(data.qa[0].answer,'');assert.equal(data.role,'support');
});
