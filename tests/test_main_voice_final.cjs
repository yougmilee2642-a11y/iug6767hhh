const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {wavPCM}=require('../static/incremental-stt.js');

test('main UI sends complete PCM to final ASR with the same question context',async()=>{
  const source=fs.readFileSync(require.resolve('../static/app.js'),'utf8');
  const listen=source.slice(source.indexOf('async function listen()'),source.indexOf('function stopRecording('))
    .replace("await import('/static/incremental-stt.js');",'/* module supplied by browser test */');
  const elements=new Map();
  const uploads=[],sent=[];
  let options;
  const context={Blob,FormData,DOMException,AbortController,performance,
    active:true,media:{},localVoice:true,sessionVersion:1,interactionId:'call',
    sessionAbort:new AbortController(),messages:[{role:'assistant',content:'Назовите номер телефона.'}],
    audioContext:null,recorder:null,analyser:null,recordingStartedAt:0,emptyHearings:0,
    setStatus(){},showToast(){},setError(message){assert.fail(message);},stopVoiceMonitor(){},monitorSilence(){},
    chooseMime:()=> 'audio/webm',isCancel:()=>false,measured:async(_,work)=>work(),
    voiceMetrics:{record(){}},callCard:{classList:{add(){},remove(){}}},
    $:key=>{if(!elements.has(key))elements.set(key,{checked:false});return elements.get(key);},
    AudioContext:class{state='running';async resume(){}createMediaStreamSource(){return{connect(){},disconnect(){}};}createAnalyser(){return{};}},
    MediaRecorder:class{
      state='inactive';start(){this.state='recording';}
      async stop(){this.state='inactive';this.ondataavailable({data:new Blob(['backup'])});await this.onstop();}
    },
    FocusSTT:{IncrementalSTT:class{
      streamId='utterance';constructor(config){options=config;}async attach(){}async finish(){return['неполный текст'];}
      finalBlob(){return wavPCM([new Float32Array(1600).fill(.1),new Float32Array(1600).fill(.001)]);}
      cancel(){}
    }},
    fetch:async(_,request)=>{
      uploads.push(request.body);
      if(request.body.get('file').name!=='utterance.wav'){context.active=false;throw new Error('Unexpected backup: complete PCM path failed');}
      return{ok:true,json:async()=>({text:'375291234567',raw_text:'весь номер',final:true})};
    },
    ask:async text=>{sent.push(text);context.active=false;return false;},
  };
  vm.createContext(context);vm.runInContext(listen,context);
  await context.listen();assert.equal(options.streaming,true);
  await context.recorder.stop();
  assert.deepEqual(sent,['375291234567']);assert.equal(uploads.length,1);
  assert.equal(uploads[0].get('context'),'Назовите номер телефона.');
  assert.equal(uploads[0].get('mode'),'final');assert.equal(uploads[0].get('stream_id'),'utterance');
  assert.equal(uploads[0].get('file').size,44+3200*2);
});
