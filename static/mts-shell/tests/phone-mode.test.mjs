import test from 'node:test';
import assert from 'node:assert/strict';
import { LocalVoiceSession } from '../local-voice.mjs';
import { SEED_AGENTS } from '../adapter.mjs';
const reply=data=>new Response(JSON.stringify(data),{headers:{'Content-Type':'application/json'}});
const health={local_only:true,ai_provider:'Ollama',llm_ready:true,local_speech:{stt_weights:true}};

test('phone-style demo acquires microphone once and listens after each answer', async(t)=>{
  const events=[];
  t.mock.method(globalThis,'fetch',async(path)=>{
    if(path==='/api/health')return reply(health);
    if(path==='/api/shell/conversations')return reply({interaction_id:'id',greeting:'Приветствие'});
    if(path==='/api/chat')return reply({text:'Ответ',complete:false});
    return reply({status:'stopped'});
  });
  const session=new LocalVoiceSession(SEED_AGENTS[0]);
  t.mock.method(session,'acquireMicrophone',async()=>{assert.equal(session.privacyReady,true);events.push('microphone');session.autoListen=true;});
  t.mock.method(session,'speak',async(text)=>events.push('speak:'+text));
  t.mock.method(session,'listen',async()=>{assert.equal(session.busy,false);events.push('listen');});
  await session.start();await session.send('Вопрос');
  assert.deepEqual(events,['microphone','speak:Приветствие','listen','speak:Ответ','listen']);
  await session.end();
});

test('text mode never acquires microphone, even after an answer',async(t)=>{
  t.mock.method(globalThis,'fetch',async(path)=>path==='/api/health'?reply(health):path==='/api/shell/conversations'?reply({interaction_id:'id',greeting:'Привет'}):reply({text:'Ответ',complete:false}));
  const session=new LocalVoiceSession(SEED_AGENTS[0]);session.sound=false;
  t.mock.method(session,'acquireMicrophone',()=>assert.fail('text mode must not request microphone'));
  t.mock.method(session,'listen',()=>assert.fail('text mode must not record'));
  await session.start({voice:false});await session.send('Вопрос');await session.end();
});

function consentUI(t) {
  const elements=[];
  const previous=globalThis.document;
  globalThis.document={body:{append(){}},createElement(tag){
    const element={tag,append(){},setAttribute(){},addEventListener(){},remove(){},close(){},focus(){},showModal(){},style:{}};
    elements.push(element);return element;
  }};
  t.after(()=>{if(previous===undefined)delete globalThis.document;else globalThis.document=previous;});
  return async(accepted)=>{
    for(let index=0;index<30 && !elements.some(item=>item.textContent==='Согласен — начать демо');index++)
      await new Promise(resolve=>setImmediate(resolve));
    const button=elements.find(item=>item.textContent===(accepted?'Согласен — начать демо':'Не согласен — завершить'));
    assert.ok(button,'explicit consent dialog shown');button.onclick();
  };
}

for(const accepted of [true,false])test('automatic microphone respects explicit consent: '+accepted,async(t)=>{
  const choose=consentUI(t),events=[];
  t.mock.method(globalThis,'fetch',async(path,options)=>{
    if(path==='/api/health')return reply(health);
    if(path==='/api/shell/conversations')return reply({interaction_id:'id',greeting:'Уведомление',privacy:{status:'pending',version:'v1',notice:'Вымышленный тест'}});
    if(path==='/api/conversations/id/consent'){
      assert.equal(JSON.parse(options.body).accepted,accepted);events.push('consent');
      return reply({accepted,greeting:accepted?'Приветствие':'Отказ'});
    }
    return reply({status:'stopped'});
  });
  const session=new LocalVoiceSession(SEED_AGENTS[0]);session.sound=false;
  t.mock.method(session,'acquireMicrophone',async()=>{events.push('microphone');session.autoListen=true;});
  t.mock.method(session,'listen',async()=>events.push('listen'));
  const starting=session.start();
  await choose(accepted);
  assert.equal(events.includes('microphone'),false);
  await starting;
  assert.deepEqual(events,accepted?['consent','microphone','listen']:['consent']);
  assert.equal(session.completed,!accepted);
  await session.end();
});
