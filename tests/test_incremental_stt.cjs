const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {IncrementalSTT,wavPCM}=require('../static/incremental-stt.js');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const frame=(value)=>new Float32Array(1600).fill(value);
const frames=async(blob)=>new DataView(await blob.arrayBuffer()).getUint32(40,true)/2;

test('independent PCM WAV has a correct header and no sample truncation',async()=> {
  const bytes=await wavPCM([new Float32Array([-1,0,1]),new Float32Array([0.5])]).arrayBuffer();
  const view=new DataView(bytes);
  assert.equal(Buffer.from(bytes,0,4).toString(),'RIFF');
  assert.equal(view.getUint32(24,true),16000);assert.equal(view.getUint32(40,true),8);
  assert.equal(view.getInt16(44,true),-32768);assert.equal(view.getInt16(48,true),32767);
});

test('recognition begins before finish, only raw ordered parts are assembled',async()=> {
  const calls=[],partials=[];
  const stt=new IncrementalSTT({transcribe:async(blob)=>{calls.push(await frames(blob));return {raw_text:'первая часть',text:'не брать нормализованную часть'};},onPartial:t=>partials.push(t)});
  for(let i=0;i<10;i++)stt.push(frame(.1));
  for(let i=0;i<4;i++)stt.push(frame(0));
  await tick();assert.equal(calls.length,1);assert.deepEqual(partials,['первая часть']);
  for(let i=0;i<10;i++)stt.push(frame(.01)); // Quiet tail still must be sent.
  const parts=await stt.finish();
  assert.equal(calls.length,2);assert.equal(calls.reduce((a,b)=>a+b),24*1600);
  assert.equal(parts.join(' '),'первая часть первая часть'); // Repeated speech is NOT deduplicated.
});

test('continuous speech is never chopped at an arbitrary duration',async()=> {
  let calls=0;
  const stt=new IncrementalSTT({transcribe:async()=>{calls++;return{raw_text:'длинная фраза'};}});
  for(let i=0;i<80;i++)stt.push(frame(.1));
  assert.equal(calls,0);await stt.finish();assert.equal(calls,1);
});

test('backpressure uses one in-flight request and coalesces pending audio without loss',async()=> {
  let release,active=0,maxActive=0;const sizes=[];
  const stt=new IncrementalSTT({transcribe:async(blob)=> {
    active++;maxActive=Math.max(active,maxActive);sizes.push(await frames(blob));
    if(sizes.length===1) await new Promise(resolve=>release=resolve);
    active--;return{raw_text:'часть'};
  }});
  let count=0;
  for(let j=0;j<4;j++) {
    for(let i=0;i<30;i++){stt.push(frame(.1));count++;}
    for(let i=0;i<4;i++){stt.push(frame(0));count++;}
  }
  await tick();assert.equal(sizes.length,1);
  const ending=stt.finish();release();await ending;
  assert.equal(maxActive,1);assert.equal(sizes.length,2);
  assert.equal(sizes.reduce((a,b)=>a+b),count*1600);
});

test('Stop aborts recognition and suppresses late partial text',async()=> {
  let release,signal;const partials=[];
  const stt=new IncrementalSTT({transcribe:async(_,s)=>{signal=s;return new Promise(resolve=>release=resolve);},onPartial:t=>partials.push(t)});
  stt.push(frame(.1));stt.cut();stt.cancel();
  assert.ok(signal.aborted);release({raw_text:'запоздалый ответ'});await tick();
  assert.deepEqual(partials,[]);await assert.rejects(stt.finish(),/отменена/);
});

test('chunk failure is explicit, never accepted as a complete empty transcript',async()=> {
  const stt=new IncrementalSTT({transcribe:async()=>{throw new Error('STT unavailable');}});
  stt.push(frame(.1));stt.cut();await tick();
  await assert.rejects(stt.finish(),/STT unavailable/);
});

test('worklet resamples 48k and 44.1k, flushes tail once, and stays silent at its output',()=> {
  for(const rate of [16000,44100,48000]) {
    let Processor;const messages=[];
    class Base{constructor(){this.port={postMessage:data=>messages.push(data)};}}
    const context={AudioWorkletProcessor:Base,sampleRate:rate,Float32Array,registerProcessor:(_,p)=>Processor=p};
    vm.runInNewContext(fs.readFileSync(require.resolve('../static/pcm-capture-worklet.js'),'utf8'),context);
    const processor=new Processor();
    const input=new Float32Array(rate/5).fill(.125);
    for(let offset=0;offset<input.length;offset+=128)processor.process([[input.slice(offset,offset+128)]]);
    processor.port.onmessage({data:'flush'});
    const values=messages.filter(m=>m!=='flushed');
    assert.equal(values.reduce((n,p)=>n+p.length,0),3200);
    for(const value of values.flatMap(p=>Array.from(p)))assert.ok(Math.abs(value-.125)<1e-5);
    assert.equal(messages.at(-1),'flushed');assert.equal(processor.process([]),false);
  }
});

test('stateful stream sends ordered packets and retains the full quiet tail for final ASR',async()=> {
  const packets=[],partials=[];
  const stt=new IncrementalSTT({streaming:true,transcribe:async(blob,_,meta)=>{
    packets.push({...meta,samples:await frames(blob)});
    return {raw_text:meta.sequence?'полная реплика':'полная',cumulative:true};
  },onPartial:text=>partials.push(text)});
  for(let i=0;i<9;i++)stt.push(frame(.1));
  await tick();
  for(let i=0;i<2;i++)stt.push(frame(.001));
  await stt.finish();
  assert.deepEqual(packets.map(p=>p.sequence),[0,1]);
  assert.equal(packets[0].streamId,packets[1].streamId);
  assert.deepEqual(partials,['полная','полная реплика']);
  assert.equal(await frames(stt.finalBlob()),11*1600);
  const view=new DataView(await stt.finalBlob().arrayBuffer());
  assert.ok(view.getInt16(view.byteLength-2,true)>0);
});
