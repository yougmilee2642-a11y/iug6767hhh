import {requestJSON} from '../mts-shell/local-voice.mjs';
const $=id=>document.getElementById(id);
const cases=[['Короткая реплика',['Где посмотреть баланс?']],
  ['Длинная реплика с паузами',['Подскажите, пожалуйста, где посмотреть баланс.',
  'Ещё хочу узнать, как проверить остаток минут.','И где найти историю платежей?']]];
const syntheticAgent={id:'streaming-qa',name:'Синтетическая проверка STT',company:'Тестовая команда',
  role:'Поддержка клиентов',greeting:'Здравствуйте! Чем могу помочь?',knowledge:'Это синтетическая техническая проверка.',
  qa:[{question:'Где посмотреть баланс, остаток минут и историю платежей?',answer:'Эти сведения можно посмотреть в приложении «Мой МТС».'}]};

async function runCase(title,phrases) {
  const article=document.createElement('article');
  const heading=document.createElement('h2');heading.textContent=title;article.append(heading);$('results').append(article);
  const progress=document.createElement('p');progress.textContent='Подготавливаю синтетическую речь…';article.append(progress);
  const id=(await requestJSON('/api/shell/conversations',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(syntheticAgent)})).interaction_id;
  const context=new AudioContext({sampleRate:48000});
  try {
    await context.resume();
    const buffers=[];
    for (const text of phrases) {
      const response=await fetch('/api/speech',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text})});
      if (!response.ok) throw new Error('Не удалось подготовить синтетический звук');
      buffers.push(await context.decodeAudioData(await response.arrayBuffer()));
    }
    const gaps=phrases.length-1;
    const seconds=buffers.reduce((sum,b)=>sum+b.duration,0)+gaps*.65+1.05;
    const combined=context.createBuffer(1,Math.ceil(seconds*context.sampleRate),context.sampleRate);
    let offset=0;
    for (const buffer of buffers) {
      combined.getChannelData(0).set(buffer.getChannelData(0),offset);
      offset+=buffer.length+Math.round(.65*context.sampleRate);
    }
    const transcribe=async(blob,signal)=> {
      const form=new FormData();form.append('file',blob,'chunk.wav');form.append('interaction_id',id);
      return requestJSON('/api/transcribe',{method:'POST',body:form,signal});
    };
    // Warm up the same CPU recognizer before either timed route.
    const warmContext=new OfflineAudioContext(1,Math.ceil(buffers[0].duration*16000),16000);
    const warmSource=warmContext.createBufferSource();warmSource.buffer=buffers[0];
    warmSource.connect(warmContext.destination);warmSource.start();
    await transcribe(FocusSTT.wavPCM([(await warmContext.startRendering()).getChannelData(0)]));
    let firstPartialAt=null;
    const stream=new FocusSTT.IncrementalSTT({transcribe,onPartial:text=> {
      if (text) {firstPartialAt ??= performance.now();progress.textContent='Уже распознано: '+text;}
    }});
    const source=context.createBufferSource();source.buffer=combined;
    await stream.attach(context,source);
    progress.textContent='Синтетическая речь идёт в реальном времени…';
    const began=performance.now();
    await new Promise(resolve=>{source.onended=resolve;source.start();});
    const recordedAt=performance.now();
    const parts=await stream.finish();
    const assembled=await requestJSON('/api/transcribe/assemble',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({interaction_id:id,parts})});
    const streamingAfterStop=performance.now()-recordedAt;
    // Baseline is the same waveform, same warmed model; only STT is timed.
    const offline=new OfflineAudioContext(1,Math.round(seconds*16000),16000);
    const resampler=offline.createBufferSource();resampler.buffer=combined;resampler.connect(offline.destination);resampler.start();
    const resampled=await offline.startRendering();
    const oldBegan=performance.now();const baseline=await transcribe(FocusSTT.wavPCM([resampled.getChannelData(0)]));
    const batchAfterStop=performance.now()-oldBegan;
    const llmBegan=performance.now();
    const reply=await requestJSON('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({interaction_id:id,text:assembled.text,request_id:crypto.randomUUID()})});
    const llmMs=performance.now()-llmBegan;
    const result={title,audio_seconds:Math.round(seconds*100)/100,parts:parts.filter(Boolean).length,
      first_partial_before_stop:firstPartialAt!==null && firstPartialAt<recordedAt,
      first_partial_ms:firstPartialAt ? Math.round(firstPartialAt-began):null,
      streaming_after_stop_ms:Math.round(streamingAfterStop),batch_after_stop_ms:Math.round(batchAfterStop),
      llm_ms:Math.round(llmMs),streaming_text:assembled.text,batch_text:baseline.text,answer:reply.text,
      chunks:stream.metrics,synthetic:true};
    progress.textContent='Проверка завершена · синтетическая речь, не микрофон.';
    const metrics=document.createElement('div');metrics.className='metric';
    for (const [label,value] of [['После остановки · по частям',result.streaming_after_stop_ms],['После остановки · целиком',result.batch_after_stop_ms]]) {
      const cell=document.createElement('div'),b=document.createElement('b');b.textContent=value+' мс';cell.append(b,label);metrics.append(cell);
    }
    article.append(metrics);
    const details=document.createElement('details'),summary=document.createElement('summary');
    summary.textContent='Расшифровка и подробные измерения';details.append(summary);
    const report=document.createElement('pre');report.dataset.report='true';report.textContent=JSON.stringify(result,null,2);details.append(report);article.append(details);
  } finally {
    await context.close();
    await requestJSON('/api/application',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({interaction_id:id})});
  }
}
$('run').onclick=async()=> {
  $('run').disabled=true;$('results').replaceChildren();
  try {
    const health=await requestJSON('/api/health');
    if (!health.local_only) throw new Error('Требуется полностью локальный режим');
    for (const [title,phrases] of cases) { $('state').textContent=title;await runCase(title,phrases); }
    $('state').textContent='Обе проверки завершены. Цифры относятся только к синтетическим репликам.';
  } catch(error) {$('state').textContent='Ошибка проверки: '+error.message;}
  finally {$('run').disabled=false;}
};
