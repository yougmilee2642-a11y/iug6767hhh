// Functional recording upload/review/playback in the existing panels.
export function mediaUI(h) {
  const {node,makeButton:button,makeInput:input,makeSelect:select,request,runAction:run,state,ui,refreshMeeting}=h;
  const statuses={queued:'В очереди',diarizing:'Определяются говорящие',transcribing:'Распознаётся речь',extracting:'Проверяется черновик',done:'Готово к проверке',failed:'Не обработано'};
  function audio(parent,asset,startMs=0) {
    const player=node('audio','');player.controls=true;player.preload='metadata';
    player.src=`/api/meet/media-assets/${asset}/audio`;
    player.addEventListener('loadedmetadata',()=>{player.currentTime=Math.min(startMs/1000,player.duration || startMs/1000);},{once:true});
    parent.append(player);return player;
  }
  async function source(parent,utterance,isCurrent=()=>true) {
    if(!utterance.media_job_id || utterance.start_ms==null)return;
    const identity=state.user?.id,epoch=state.epoch;
    const result=await request(`/media-jobs/${utterance.media_job_id}`);
    if(state.user?.id!==identity || state.epoch!==epoch || !parent.isConnected || !isCurrent())return;
    parent.append(node('p','task-meta',`Таймкод: ${(utterance.start_ms/1000).toFixed(1)} сек.`));
    if(result.job.asset_id)audio(parent,result.job.asset_id,utterance.start_ms);
    else parent.append(node('p','muted-copy','Исходное аудио удалено по политике хранения.'));
  }
  function mount(parent,meeting) {
    const identity=state.user?.id,epoch=state.epoch;
    const section=node('section','panel');section.append(node('h2','','Загрузить запись с согласия'));
    parent.append(section);
    const current=()=>state.user?.id===identity && state.epoch===epoch && section.isConnected;
    if(state.capabilities.includes('transcript.edit')){
      const mode=input({label:'Режим переговорной: показывать подсказки без действий',type:'checkbox'});
      const live=node('div','');live.setAttribute('aria-live','polite');section.append(mode.wrap,live);
      let timer=null;
      const active=()=>current() && mode.input.checked && state.voiceCapture?.recording && String(state.voiceCapture.meetingId)===String(meeting.id);
      async function poll(){
        if(!current() || !mode.input.checked)return;
        if(!active())live.replaceChildren(node('p','muted-copy','Подсказки включатся во время записи с согласием участников.'));
        else try{
          const drafts=(state.voiceDrafts[meeting.id] || []).filter(d=>!d.saved && !d.loading && d.text).slice(-10).map(d=>d.text.slice(0,2000));
          const result=await request(`/meetings/${meeting.id}/room-hints`,{method:'POST',body:{consent:true,drafts}});
          if(!active())return;
          live.replaceChildren(node('p','muted-copy',result.notice));
          for(const hint of result.hints){const row=node('article','claim-item');row.append(node('p','',hint.text),node('p','task-meta',hint.verified_transcript?'Сохранённая реплика':'Непроверенный фрагмент ASR'),node('blockquote','',hint.source.quote));live.append(row);}
          if(!result.hints.length)live.append(node('p','','По текущим правилам уточнений нет.'));
        }catch(error){if(active())live.replaceChildren(node('p','gap-state',error.message || 'Подсказки недоступны.'));}
        if(current() && mode.input.checked)timer=setTimeout(poll,5000);
      }
      mode.input.addEventListener('change',()=>{clearTimeout(timer);if(mode.input.checked)void poll();else live.replaceChildren();});
    }
    const jobs=node('div','');
    async function load() {
      const data=await request(`/meetings/${meeting.id}/audio`);if(!current())return;
      jobs.replaceChildren();
      if(!data.jobs.length)jobs.append(node('p','muted-copy','Загруженных записей нет.'));
      for(const job of data.jobs) {
        const row=node('article','claim-item');row.append(node('h3','',`Запись ${job.id} · ${statuses[job.status] || 'Требует проверки'} · ${job.progress}%`));
        if(job.error_message)row.append(node('p','gap-state',job.error_message));
        if(job.asset_id)audio(row,job.asset_id);
        else row.append(node('p','muted-copy','Исходное аудио удалено.'));
        if(job.imported_at)row.append(node('p','','Реплики добавлены в стенограмму.'));
        if(state.capabilities.includes('transcript.edit') && !job.imported_at && job.asset_id) {
          if(job.status==='failed' || job.status==='done') {
            const retry=button('Повторить обработку',()=>void run(retry,async()=>{await request(`/media-jobs/${job.id}/retry`,{method:'POST'});if(current())await load();}));row.append(retry);
          }
          if(job.status==='done') {
            const maps=new Map();
            for(const label of new Set(job.segments.map(s=>s.speaker_label))) {
              const wrap=node('label','field');wrap.append(node('span','',label));
              const field=select([{value:'',label:'Неизвестный участник'},...(meeting.participants || []).map(name=>({value:name,label:name}))],'');
              field.setAttribute('aria-label',`Участник: ${label}`);maps.set(label,field);wrap.append(field);row.append(wrap);
            }
            const review=button('Проверить импорт реплик',()=>void run(review,async()=>{
              const speaker_map=Object.fromEntries([...maps].filter(([,field])=>field.value).map(([label,field])=>[label,field.value]));
              const p=await request(`/media-jobs/${job.id}/import/preview`,{method:'POST',body:{speaker_map}});if(!current())return;
              const content=node('div','');content.append(node('p','',p.preview.notice));
              for(const s of p.preview.segments)content.append(node('p','',`${(s.start_ms/1000).toFixed(1)}–${(s.end_ms/1000).toFixed(1)} · ${speaker_map[s.speaker_label] || s.speaker_label}: ${s.text}`));
              const key=crypto.randomUUID();
              ui.dialog('Добавить проверенную расшифровку',content,async()=>{
                await request(`/media-jobs/${job.id}/import/confirm`,{method:'POST',body:{confirmation_id:p.confirmation_id,idempotency_key:key}});
                if(current())await refreshMeeting(meeting.id);
              },()=>request(`/confirmations/${p.confirmation_id}/cancel`,{method:'POST'}));
            }));row.append(review);
          }
        }
        for(const segment of job.segments) {
          const play=button(`${(segment.start_ms/1000).toFixed(1)} сек. · ${segment.speaker_label}: ${segment.text}`,()=>{
            const player=row.querySelector('audio');if(player){player.currentTime=segment.start_ms/1000;void player.play().catch(()=>{});}
          },'text-button');play.disabled=!job.asset_id;row.append(play);
        }
        jobs.append(row);
      }
    }
    const refresh=button('Обновить записи и прогресс',()=>void run(refresh,load));section.append(refresh);
    if(state.capabilities.includes('transcript.edit')) {
      const form=node('form','meet-form-grid');
      const file=input({label:'Аудиофайл WAV/MP3/M4A/OGG/WebM',type:'file',required:true});file.input.accept='.wav,.mp3,.m4a,.ogg,.webm';
      const consent=node('label','record-consent'),checkbox=node('input','');checkbox.type='checkbox';checkbox.required=true;
      consent.append(checkbox,node('span','','Все участники согласны на запись, расшифровку и хранение аудио.'));
      const submit=button('Загрузить запись',null,'secondary-button','submit');form.append(file.wrap,consent,submit);
      form.addEventListener('submit',event=>{event.preventDefault();void run(submit,async()=>{
        const body=new FormData();body.append('file',file.input.files[0]);body.append('consent',String(checkbox.checked));
        try{await request(`/meetings/${meeting.id}/audio`,{method:'POST',body});}
        finally{if(current())await load();}
      });});section.append(form);
    }
    section.append(jobs);
    const report=node('div','');
    const metrics=button('Аналитика встречи',()=>void run(metrics,async()=>{
      const a=await request(`/meetings/${meeting.id}/analytics`);if(!current())return;
      report.replaceChildren(node('p','muted-copy',a.method));
      if(!a.timing_available)report.append(node('p','','Таймкодов нет: доля речи и паузы не рассчитываются.'));
      for(const s of a.speakers)report.append(node('p','',`${s.speaker}: ${s.share_percent==null?'нет таймкодов':s.share_percent+'% речи'}${s.little_speech?' · меньше5%':''}`));
      report.append(node('p','',`Без ответственного: ${a.missing_assignee}; без срока: ${a.missing_due}.`));
      if(a.timing_available)report.append(node('p','',`Перекрытия: ${a.overlap_ms/1000} сек.; длинных пауз: ${a.long_pauses.length}.`));
      for(const item of a.agenda)report.append(node('p','',`${item.text}: ${item.speech_ms/1000} сек. по совпадению слов.`));
    }));section.append(metrics,report);
    void run(refresh,load);
  }
  return {mount,source};
}
