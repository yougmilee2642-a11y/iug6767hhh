const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

let currentConfig = null;
let selectedAgentId = null;
let selectedAgentConfig = null;
let selectedAgentSource = null;
let conversationGreeting = '';
let customQuestions = [];
let messages = [];
let active = false;
let starting = false;
let finishing = false;
let turnBusy = false;
let pendingAsk = null;
let interactionId = null;
let sessionVersion = 0;
let settleSpeech = null;
let voiceEnabled = true;
let media = null;
let recorder = null;
let chunks = [];
let discardCurrentRecording = false;
let audioContext = null;
let analyser = null;
let audioSource = null;
let monitorId = null;
let player = null;
let playerUrl = null;
let speechToken = 0;
let speechController = null;
let localVoice = false;
let incrementalRecorder = null;
let callStartedAt = 0;
let callTick = null;
// Cancels every in-flight STT/assemble/chat request of the current conversation (Stop, finish, page close).
let sessionAbort = null;
let emptyHearings = 0;
let endpointMs = null;
let recordingStartedAt = 0;
let modelLabel = '';
const voiceMetrics = FocusVoiceMetrics.create();
window.focusVoiceMetrics = voiceMetrics;

const isCancel = (error) => error?.name === 'AbortError';
function abortSession() {
  sessionAbort?.abort();
  sessionAbort = null;
}
// Runs one stage and records it: success, cancellation or failure (the latter two never count as latency).
async function measured(stage, work, extra = {}) {
  const began = performance.now();
  try {
    const result = await work();
    voiceMetrics.record(stage, performance.now() - began, 'ok', extra);
    return result;
  } catch (error) {
    voiceMetrics.record(stage, performance.now() - began, isCancel(error) ? 'cancelled' : 'failed', extra);
    throw error;
  }
}

const chat = $('#chat');
const callCard = $('.call-card');

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  }[char]));
}

function showToast(message) {
  const toast = $('#toast');
  toast.textContent = message;
  toast.classList.add('show');
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove('show'), 2600);
}

function setStatus(text, kind = 'ready') {
  const status = $('#status');
  status.lastChild.textContent = ` ${text}`;
  status.dataset.kind = kind;
}

function addMessage(role, text) {
  if (chat.querySelector('.empty-state')) chat.innerHTML = '';
  const item = document.createElement('div');
  item.className = `msg ${role}`;
  const businessName = selectedAgentSource && selectedAgentSource !== 'demo' ? selectedAgentConfig.business.name : currentConfig.business_name;
  item.innerHTML = `<span class="label">${role === 'ai' ? escapeHtml(businessName) + ' AI' : 'Вы'}</span>${escapeHtml(text)}`;
  chat.append(item);
  chat.scrollTop = chat.scrollHeight;
  messages.push({ role: role === 'ai' ? 'assistant' : 'user', content: text });
}

function stopPlayer() {
  speechToken += 1;
  speechController?.abort();
  speechController = null;
  settleSpeech?.();
  settleSpeech = null;
  if (player) {
    player.pause();
    player.src = '';
    player = null;
  }
  if (playerUrl) {
    URL.revokeObjectURL(playerUrl);
    playerUrl = null;
  }
}

async function speak(text) {
  const token = ++speechToken;
  speechController?.abort();
  const controller = new AbortController();
  speechController = controller;
  if (player) player.pause();
  $('#state').textContent = 'Готовлю голосовой ответ…';
  const speakStartedAt = performance.now();
  let firstAudioRecorded = false;
  const fetchPart = async (part) => {
    const response = await fetch('/api/speech', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: part }), signal: controller.signal
    });
    if (!response.ok) throw new Error('Русская озвучка недоступна — можно продолжить текстом');
    const blob = await response.blob();
    if (!firstAudioRecorded) {
      firstAudioRecorded = true;
      voiceMetrics.record('tts_first_audio', performance.now() - speakStartedAt, 'ok', { chars: part.length });
    }
    return blob;
  };
  let firstPlayed = false;
  const play = (blob) => playSpeechBlob(blob, token, () => {
    if (firstPlayed) return;
    firstPlayed = true;
    voiceMetrics.record('playback_start', performance.now() - speakStartedAt, 'ok');
  });
  try {
    const parts = localVoice ? FocusVoice.speechParts(text) : [text];
    await FocusVoice.speakPreparedParts(parts, fetchPart, play, () => token === speechToken);
  } catch (error) {
    if (!firstAudioRecorded) voiceMetrics.record('tts_first_audio', performance.now() - speakStartedAt, isCancel(error) ? 'cancelled' : 'failed');
    throw error;
  } finally {
    controller.abort();
    if (speechController === controller) speechController = null;
  }
}

async function playSpeechBlob(blob, token, onStarted = () => {}) {
  if (token !== speechToken) return;
  $('#state').textContent = 'AI отвечает…';
  if (playerUrl) URL.revokeObjectURL(playerUrl);
  playerUrl = URL.createObjectURL(blob);
  player = new Audio(playerUrl);
  player.playbackRate = 1.2;
  player.preservesPitch = true;
  return new Promise((resolve) => {
    const thisPlayer = player;
    let playbackWatchdog;
    let settled = false;
    const done = () => {
      if (settled) return;
      settled = true;
      clearTimeout(playbackWatchdog);
      if (settleSpeech === done) settleSpeech = null;
      resolve();
    };
    const armWatchdog = (delay) => {
      clearTimeout(playbackWatchdog);
      playbackWatchdog = setTimeout(() => {
        thisPlayer.pause();
        showToast('Воспроизведение остановлено — можно продолжить');
        done();
      }, delay);
    };
    settleSpeech = done;
    thisPlayer.onended = done;
    thisPlayer.onerror = () => { showToast('Не удалось воспроизвести голос'); done(); };
    thisPlayer.onplaying = () => onStarted(); // real start of audible playback, not the play() call
    thisPlayer.onloadedmetadata = () => {
      if (Number.isFinite(thisPlayer.duration)) armWatchdog((thisPlayer.duration + 3) * 1000);
    };
    armWatchdog(45000); // Playback recovery only; never limits microphone recording.
    thisPlayer.play().catch(() => { showToast('Браузер заблокировал звук — продолжайте текстом'); done(); });
  });
}

// Recognised speech is only a proposal: with review enabled the tester can correct it
// (names, phones, amounts, negations) and the confirmed text becomes the user's turn.
const transcriptReview = FocusTranscriptReview.createReview();
function reviewRecognised(text) {
  const box = $('#voiceReview'), field = $('#voiceReviewText');
  field.value = text;
  box.hidden = false;
  setStatus('Проверьте текст', 'ready');
  $('#state').textContent = 'Проверьте распознанную фразу и нажмите «Отправить»';
  field.focus();
  return transcriptReview.request(text).finally(() => { box.hidden = true; });
}

async function ask(text) {
  if (turnBusy || !active) return false;
  text = text.trim();
  if (!text) return false;
  turnBusy = true;
  const version = sessionVersion;
  pendingAsk = (async () => {
    addMessage('user', text);
    setStatus('AI отвечает', 'working');
    const data = await measured('llm', async () => {
      const response = await fetch('/api/chat', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: sessionAbort?.signal,
        body: JSON.stringify({ interaction_id: interactionId, text, request_id: crypto.randomUUID() })
      });
      const body = await response.json();
      if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Не удалось получить ответ AI');
      return body;
    });
    if (version !== sessionVersion || !active) return false;
    if (!data.text) throw new Error('AI вернул пустой ответ');
    renderApplication(data.interaction);
    addMessage('ai', data.text);
    setStatus('AI говорит', 'working');
    if (voiceEnabled) {
      try { await speak(data.text); } catch (error) { if(!isCancel(error)&&version===sessionVersion&&active)showToast(error.message); }
    }
    if (active && version === sessionVersion && !data.complete && !voiceEnabled) {
      setStatus('Ожидаю ответ');
      $('#state').textContent = 'Введите ответ в поле диалога';
    }
    return Boolean(data.complete);
  })();
  try { return await pendingAsk; }
  finally { turnBusy = false; pendingAsk = null; }
}

function chooseMime() {
  return ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']
    .find((type) => MediaRecorder.isTypeSupported(type)) || '';
}

function stopVoiceMonitor() {
  if (monitorId) cancelAnimationFrame(monitorId);
  monitorId = null;
  try { audioSource?.disconnect(); } catch (_) {}
  audioSource = null;
  analyser = null;
}

function monitorSilence() {
  if (!recorder || recorder.state !== 'recording' || !analyser) return;
  const samples = new Uint8Array(analyser.fftSize);
  let speechDetected = false;
  let speechFrames = 0;
  let noiseFloor = 0.008;
  let lastVoiceAt = performance.now();

  const check = () => {
    if (!recorder || recorder.state !== 'recording' || !analyser) return;
    if ((!speechDetected && performance.now()-recordingStartedAt>15000) || performance.now()-recordingStartedAt>120000) {
      recorder.stop(); return;
    }
    analyser.getByteTimeDomainData(samples);
    let power = 0;
    for (const sample of samples) {
      const normalized = (sample - 128) / 128;
      power += normalized * normalized;
    }
    const rms = Math.sqrt(power / samples.length);
    const threshold = Math.max(0.014, noiseFloor * (speechDetected ? 2.1 : 2.7));

    if (!speechDetected) {
      if (rms > threshold) {
        speechFrames += 1;
        if (speechFrames >= 3) {
          speechDetected = true;
          lastVoiceAt = performance.now();
        }
      } else {
        speechFrames = 0;
        noiseFloor = noiseFloor * 0.96 + rms * 0.04;
      }
    } else if (rms > threshold) {
      lastVoiceAt = performance.now();
    }

    const endSilenceMs=/телефон|номер|по цифр/i.test(messages.filter(m=>m.role==='assistant').at(-1)?.content||'')?1800:1200;
    const lastDetectedVoice=incrementalRecorder?.speakerChecked?incrementalRecorder.lastPrimaryVoiceAt:lastVoiceAt;
    if (speechDetected && performance.now() - lastDetectedVoice > endSilenceMs) {
      endpointMs = performance.now() - lastVoiceAt; // time from last detected voice frame to the stop decision
      recorder.stop();
      return;
    }
    monitorId = requestAnimationFrame(check);
  };
  monitorId = requestAnimationFrame(check);
}

async function listen() {
  if (!active || !media) return;
  stopVoiceMonitor();
  const version = sessionVersion;
  const recordingChunks = [];
  chunks = recordingChunks;
  discardCurrentRecording = false;
  endpointMs = null;
  const contextText=messages.filter(m=>m.role==='assistant').at(-1)?.content || '';
  let progressive=null,pcmSource=null;
  if (localVoice) {
    try {
      await import('/static/incremental-stt.js');
      audioContext ??= new AudioContext();
      await audioContext.resume();
      pcmSource=audioContext.createMediaStreamSource(media);
      progressive=new FocusSTT.IncrementalSTT({
        streaming:true,
        transcribe:async (blob,signal,chunk)=> {
          const form=new FormData();
          form.append('file',blob,'chunk.wav');form.append('interaction_id',interactionId);
          form.append('context',contextText);
          form.append('mode','preview');form.append('stream_id',chunk.streamId);form.append('sequence',chunk.sequence);
          const response=await fetch('/api/transcribe',{method:'POST',body:form,signal});
          const data=await response.json();
          if (!response.ok) throw new Error(data.detail || 'Ошибка распознавания фрагмента');
          return data;
        },
        onPartial:(text)=> {
          if (version===sessionVersion && active && recorder?.state==='recording' && text)
            $('#state').textContent='Уже распознано: '+text.slice(-160);
        },
      });
      incrementalRecorder=progressive;
      await progressive.attach(audioContext,pcmSource);
    } catch {
      progressive?.cancel();progressive=null;
      pcmSource?.disconnect();pcmSource=null;
    }
    if (!active || version!==sessionVersion) {progressive?.cancel();pcmSource?.disconnect();return;}
  }
  const mime = chooseMime();
  try {
    recorder = new MediaRecorder(media, mime ? { mimeType: mime } : undefined);
  } catch (_) {
    progressive?.cancel();pcmSource?.disconnect();
    setError('Этот браузер не умеет записывать звук. Используйте Chrome или Edge.');
    return;
  }

  const thisRecorder = recorder;
  thisRecorder.discard = false;
  recorder.ondataavailable = (event) => { if (event.data.size) recordingChunks.push(event.data); };
  recorder.onerror = () => {if(version===sessionVersion&&active)setError('Не удалось записать звук. Проверьте доступ к микрофону.');};
  recorder.onstop = async () => {
    if(version!==sessionVersion){progressive?.cancel();pcmSource?.disconnect();return;}
    stopVoiceMonitor();
    $('#sendVoice').hidden = true;
    callCard.classList.remove('recording');
    if (thisRecorder.discard || version !== sessionVersion || !active || !recordingChunks.length) {
      progressive?.cancel();
      discardCurrentRecording = false;
      return;
    }
    if (endpointMs !== null) voiceMetrics.record('endpointing', endpointMs, 'ok');
    endpointMs = null;
    const audioSeconds = Math.round((performance.now() - recordingStartedAt) / 100) / 10;
    const gone = () => thisRecorder.discard || version !== sessionVersion || !active;
    const signal = sessionAbort?.signal;
    setStatus('Распознаю', 'working');
    $('#state').textContent = 'Распознаю фразу…';
    try {
      // T-one previews never reach the agent. GigaAM verifies the complete waveform.
      const data = await measured('stt', async () => {
        let result = null;
        if (progressive) {
          try {
            await progressive.finish();
            if (gone()) throw new DOMException('Отменено','AbortError');
            const form=new FormData();
            form.append('file',progressive.finalBlob(),'utterance.wav');
            form.append('interaction_id',interactionId);form.append('context',contextText);
            form.append('mode','final');form.append('stream_id',progressive.streamId);
            const response=await fetch('/api/transcribe',{method:'POST',body:form,signal});
            result=await response.json();
            if (!response.ok) throw new Error(result.detail || 'Не удалось собрать реплику');
          } catch (error) {
            if (gone() || isCancel(error)) throw new DOMException('Отменено','AbortError');
            progressive.cancel();result=null;
            $('#state').textContent='Поток прервался. Распознаю сохранённую запись целиком…';
          }
        }
        if (!result) {
          const extension = mime.includes('mp4') ? 'mp4' : 'webm';
          const form = new FormData();
          form.append('file', new Blob(recordingChunks, { type: mime || 'audio/webm' }), `voice.${extension}`);
          form.append('interaction_id', interactionId);
          form.append('mode','final');
          form.append('context', messages.filter((message) => message.role === 'assistant').at(-1)?.content || '');
          const response = await fetch('/api/transcribe', { method: 'POST', body: form, signal });
          result = await response.json();
          if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Ошибка распознавания');
        }
        return result;
      }, { audio_seconds: audioSeconds, recognition_mode:progressive?'incremental':'whole_recording', measurement_span:'recording_stop_to_final_transcript' });
      if (!data || gone()) return;
      if (!data.text?.trim()) {
        if(data.speaker?.requires_repeat){
          $('#state').textContent=data.speaker.message;
          showToast(data.speaker.message);
          if(active)listen();
          return;
        }
        // Silence or noise: nothing is sent, no turn is created, nothing reaches the Runtime.
        emptyHearings += 1;
        $('#state').textContent = emptyHearings >= 3
          ? 'Речь не слышна. Проверьте микрофон и шум вокруг или введите ответ текстом'
          : 'Не расслышал. Попробуйте ещё раз';
        if(emptyHearings>=3){stopRecording(true);releaseMicrophone();voiceEnabled=false;setStatus('Продолжите текстом');return;}
        if (active) listen();
        return;
      }
      emptyHearings = 0;
      let phrase = data.text.trim();
      if ($('#reviewVoiceToggle')?.checked) {
        const reviewed = await reviewRecognised(phrase);
        if (gone()) return;
        if (!reviewed) { $('#state').textContent = 'Фраза отброшена. Скажите заново'; listen(); return; }
        phrase = reviewed.text;
      }
      let complete;
      try { complete = await ask(phrase); }
      catch (error) {
        if (isCancel(error) || gone()) return;
        // LLM/runtime failure (for example Ollama is off): keep the call usable.
        showToast(error.message);
        if (active) {
          await listen();
          $('#state').textContent = error.message + ' Скажите фразу ещё раз или введите её текстом';
        }
        return;
      }
      if (complete) await finish(true);
      else if (active) listen();
    } catch (error) {
      if (isCancel(error) || gone()) return;
      // Recognition failed (STT error, Ollama off): the call stays open, the customer can repeat or type.
      if (active) {
        showToast(error.message);
        await listen();
        $('#state').textContent = error.message + ' Скажите фразу ещё раз или введите её текстом';
      } else setError(error.message);
    }
  };

  recordingStartedAt = performance.now();
  recorder.start(250);
  $('#sendVoice').hidden = false;
  callCard.classList.add('recording');
  setStatus('Слушаю', 'listening');
  $('#state').textContent = progressive ? 'Слушаю и распознаю во время пауз' : 'Говорите — пауза завершит запись';
  try {
    audioContext ??= new AudioContext();
    if (audioContext.state === 'suspended') await audioContext.resume();
    audioSource = pcmSource || audioContext.createMediaStreamSource(media);
    analyser = audioContext.createAnalyser();
    analyser.fftSize = 2048;
    analyser.smoothingTimeConstant = 0.2;
    audioSource.connect(analyser);
    monitorSilence();
  } catch (_) {
    setError('Браузер не поддерживает определение тишины.');
  }
}

function stopRecording(discard = false) {
  $('#sendVoice').hidden = true;
  discardCurrentRecording = discard;
  if (recorder) recorder.discard = discard;
  if (discard) {incrementalRecorder?.cancel();incrementalRecorder=null;transcriptReview.discard();}
  stopVoiceMonitor();
  if (recorder?.state === 'recording') recorder.stop();
  callCard.classList.remove('recording');
}

function releaseMicrophone() {
  media?.getTracks().forEach((track) => { track.onended = null; track.stop(); });
  media = null;
}

function setError(message) {
  $('#sendVoice').hidden = true;
  callCard.classList.remove('recording');
  $('#state').textContent = message;
  setStatus('Ошибка', 'error');
}

function resultFields(item) {
  const fields = { 'Намерение': item.intent };
  if (item.brief_summary) fields['Кратко'] = item.brief_summary;
  if(item.transcript_digest?.quotes?.length){
    fields['Реплики клиента · цитаты'] = item.transcript_digest.quotes.map(q=>'«'+q.text+(q.truncated?'…':'')+'»').join('\n')+(item.transcript_digest.omitted_user_turns?'\nПоказаны последние три реплики; весь разговор — в расшифровке.':'');
  }
  if (item.telegram_delivery) {
    const delivery=item.telegram_delivery;
    fields['Telegram'] = ({not_queued:'Не поставлено в очередь',pending:'Ожидает отправки',retry:'Повторная попытка запланирована',sending:'Отправляется',sent:'Доставлено в чат, чтение не подтверждено',failed:'Не отправлено',unknown:'Результат неизвестен, повтор отключён',cancelled:'Отправка отменена'})[delivery.status] || delivery.status;
    if(delivery.attempts)fields['Попытки отправки']=delivery.attempts;
  }
  const entries = item.display_fields || Object.entries(item.action_result || item.structured_data || {})
    .map(([id, value]) => ({ id, label: id, value }));
  for (const entry of entries) fields[entry.label] = entry.value;
  fields['Статус'] = ({ active: 'Разговор идёт', awaiting_confirmation: 'Ожидает подтверждения', completed: 'Действие выполнено', escalated: 'Запрос сотруднику', stopped: 'Разговор остановлен', legacy: 'Архив' })[item.status] || item.status;
  fields['Результат'] = item.result || 'Действие пока не выполнено';
  if (item.escalation) fields['Причина передачи'] = ({ explicit_user_request: 'Клиент попросил человека', complaint: 'Жалоба', unsupported_scenario: 'Неподдерживаемый запрос', tool_failure: 'Повторная ошибка инструмента' })[item.escalation.reason] || item.escalation.reason;
  return fields;
}

function renderApplication(application) {
  $('#application').innerHTML = Object.entries(resultFields(application)).map(([label, value]) => (
    `<div class="field"><b>${escapeHtml(label)}</b><span>${escapeHtml(value ?? '—')}</span></div>`
  )).join('');
  const badge = $('#resultBadge');
  const support=selectedAgentConfig?.business?.knowledge?.track1_profile==='support';
  badge.textContent = ({ completed: 'Действие выполнено', escalated: 'Запрос человека зафиксирован', awaiting_confirmation: 'Подтвердите действие', active: support?'Разговор идёт':'Собирает данные', stopped: support?'Веб-тест сохранён':'Сохранён незавершённый разговор' })[application.status] || 'Сохранено';
  badge.classList.toggle('success', ['completed', 'escalated'].includes(application.status));
  if (application.email_error) showToast(application.email_error);
}

async function finish(automatic = false) {
  if (finishing || (!active && !automatic)) return;
  finishing = true;
  active = false;
  clearInterval(callTick);
  abortSession(); // in-flight STT / assemble / chat requests
  transcriptReview.discard();
  stopRecording(true);
  releaseMicrophone();
  if (audioContext) { try { await audioContext.close(); } catch (_) {} }
  audioContext = null;
  stopPlayer();
  $('#start').innerHTML = '<span>●</span> Начать разговор';
  $('#state').textContent = automatic ? 'Сценарий завершён' : 'Разговор завершён';
  setStatus('Сохраняю разговор', 'working');
  try { await pendingAsk; } catch (_) {}
  sessionVersion += 1;
  if (!messages.some((message) => message.role === 'user')) {
    setStatus('Готов');
    finishing = false;
    return;
  }
  try {
    const response = await fetch('/api/application', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ interaction_id: interactionId })
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Не удалось сформировать заявку');
    renderApplication(data);
    setStatus(data.email_sent ? 'Отправлено на email' : 'Обращение сохранено');
    showToast(data.email_sent ? 'Обращение сохранено и отправлено' : 'Обращение сохранено в кабинете');
  } catch (error) {
    setError(error.message);
  } finally { finishing = false; }
}

async function startCall(useMicrophone = true) {
  if (starting || finishing || !currentConfig) return;
  if (active) {
    await finish(false);
    return;
  }
  starting = true;
  const startVersion=++sessionVersion;
  abortSession();
  sessionAbort = new AbortController();
  emptyHearings = 0;
  try {
    const response = await fetch('/api/conversations', { method: 'POST', signal:sessionAbort?.signal, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ agent_id: selectedAgentId }) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Не удалось начать разговор');
    if(startVersion!==sessionVersion)return;
    interactionId = data.interaction_id;
    conversationGreeting = data.greeting;
    if(data.privacy?.status==='pending'){
      const {askPrivacy}=await import('/static/privacy-consent.mjs');
      const decision=await askPrivacy(data.privacy,sessionAbort?.signal);
      if(startVersion!==sessionVersion)return;
      const consentResponse=await fetch('/api/conversations/'+encodeURIComponent(interactionId)+'/consent',{
        method:'POST',signal:sessionAbort?.signal,headers:{'Content-Type':'application/json'},
        body:JSON.stringify({accepted:decision,version:data.privacy.version})});
      const consent=await consentResponse.json();
      if(!consentResponse.ok)throw new Error(consent.detail||'Не удалось сохранить выбор.');
      if(!consent.accepted){$('#state').textContent=consent.greeting;starting=false;return;}
      conversationGreeting=consent.greeting;
    }
    if (useMicrophone) {
      try {
        const acquiredMedia = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount:1 }
        });
        if(startVersion!==sessionVersion){acquiredMedia.getTracks().forEach(t=>t.stop());return;}
        media=acquiredMedia;
      } catch (error) {
        const denied = ['NotAllowedError', 'SecurityError'].includes(error?.name);
        const missing = ['NotFoundError', 'OverconstrainedError'].includes(error?.name);
        showToast(denied ? 'Доступ к микрофону запрещён — продолжайте текстом'
          : missing ? 'Микрофон не найден — продолжайте текстом' : 'Микрофон недоступен — продолжайте текстом');
        media = null;
      }
      media?.getAudioTracks().forEach((track) => {
        track.onended = () => { // device unplugged or permission revoked mid-call
          if (!active || media === null) return;
          stopRecording(true);
          releaseMicrophone();
          voiceEnabled = false;
          setError('Микрофон отключился. Продолжайте текстом или начните разговор заново.');
        };
      });
    }
    if(startVersion!==sessionVersion)return;
  } catch (error) {
    releaseMicrophone();
    abortSession();
    setError(error.message);
    starting = false;
    return;
  }
  active = true;
  starting = false;
  voiceEnabled = useMicrophone && Boolean(media);
  messages = [];
  chat.innerHTML = '';
  const support=selectedAgentConfig?.business?.knowledge?.track1_profile==='support';
  $('#application').innerHTML = '<div class="empty-state wide"><span>⌁</span><b>Разговор идёт</b><p>'+(support?'Проверьте известный и неизвестный вопрос. Контакты для FAQ не обязательны.':'Обращение сохраняется после сбора данных и подтверждения клиента.')+'</p></div>';
  $('#resultBadge').textContent = support?'Разговор идёт':'Собирает данные';
  $('#resultBadge').classList.remove('success');
  $('#start').innerHTML = '<span>■</span> Завершить разговор';
  callStartedAt = Date.now();
  $('#timer').textContent = '00:00';
  callTick = setInterval(() => {
    $('#timer').textContent = new Date(Date.now() - callStartedAt).toISOString().substring(14, 19);
  }, 1000);
  addMessage('ai', conversationGreeting);
  setStatus('AI говорит', 'working');
  $('#state').textContent = 'AI приветствует клиента…';
  try {
    if (voiceEnabled) await speak(conversationGreeting);
    if (active) await listen();
  } catch (error) {
    showToast(error.message);
    if (active) await listen();
  } finally { starting = false; }
}

async function sendTypedAnswer(event) {
  event.preventDefault();
  const input = $('#textAnswer');
  const text = input.value.trim();
  if (!text || turnBusy || starting || finishing) return;
  if (!active) await startCall(false);
  if (!active) return;
  input.value = '';
  stopRecording(true);
  try {
    const complete = await ask(text);
    if (complete) await finish(true);
    else if (active) await listen();
  } catch (error) {
    if (!isCancel(error)) setError(error.message);
  }
}

function updateBusinessPreview() {
  const business = selectedAgentSource && selectedAgentSource !== 'demo' ? selectedAgentConfig?.business : null;
  $('#callBusinessName').textContent = business?.name || currentConfig.business_name;
  const intake = business?.knowledge?.track1_quick === true;
  const support = business?.knowledge?.track1_profile === 'support';
  $('#callBusinessMeta').textContent = [business ? business.city : currentConfig.city, business?.industry || currentConfig.industry, intake ? 'приём обращения · веб-тест' : support ? 'ответы по знаниям · веб-тест' : 'тестовый календарь'].filter(Boolean).join(' · ');
  const emptyDescription = $('#chat .empty-state p');
  if (emptyDescription) emptyDescription.textContent = business
    ? `Роль: ${selectedAgentConfig.role.name}. ${intake ? 'Имя, телефон и причина обращения. Доставка не подключена.' : support ? 'Ответы по знаниям. Внешний канал не подключён.' : 'Расписание локальное и тестовое.'}`
    : 'Демо: AI-администратор салона красоты. Расписание локальное и тестовое.';
}

async function loadConfig() {
  const response = await fetch('/api/config');
  if (!response.ok) throw new Error('Не удалось загрузить настройки компании');
  currentConfig = await response.json();
  customQuestions = structuredClone(currentConfig.custom_questions || []);
  updateBusinessPreview();
  fillConfigForm();
}

async function loadHealth() {
  const response = await fetch('/api/health');
  if (!response.ok) return;
  const health = await response.json();
  if(health.qa_stub){
    $('#healthTitle').textContent='Стенд интерфейса';$('#healthMeta').textContent='Ответы имитируются';
    $('#channelNotice').textContent='Стенд интерфейса: ответы имитируются, база временная. Проверяйте текстовый разговор. Это не проверка качества AI или речи.';
    return;
  }
  localVoice = health.ai_provider === 'Ollama';
  modelLabel = [health.ai_provider, health.model].filter(Boolean).join(' / ');
  if(health.ai_provider==='Ollama'){
    $('#healthTitle').textContent=health.llm_ready?'Локальный AI готов':'Ожидает локальную LLM';
    $('#healthMeta').textContent=health.model+' · локально';
    $('#channelNotice').textContent='Голос и текст обрабатываются на этом компьютере. Это веб-проверка: телефонная линия и внешняя доставка не подключены.';
    $('#silenceNote').textContent='Фраза отправляется после короткой паузы или сразу по кнопке. Одна реплика — до 120 секунд.';
    return;
  }
  $('#healthTitle').textContent = health.groq_configured ? 'AI подключён' : 'Нужен ключ Groq';
  $('#healthMeta').textContent = health.smtp_configured ? 'Groq + email готовы' : 'Email ещё не настроен';
}

function fillConfigForm() {
  const form = $('#configForm');
  ['business_name', 'industry', 'city', 'notification_email', 'greeting', 'services', 'description', 'opening_hours', 'timezone', 'callback_message', 'knowledge_base']
    .forEach((name) => { form.elements[name].value = currentConfig[name] || ''; });
  renderQuestions();
}

function renderQuestions() {
  const list = $('#questionsList');
  if (!customQuestions.length) {
    list.innerHTML = '<div class="empty-state"><b>Дополнительных вопросов нет</b><p>AI соберёт стандартные данные заявки.</p></div>';
    return;
  }
  list.innerHTML = '';
  customQuestions.forEach((question, index) => {
    const row = document.createElement('div');
    row.className = 'question-row';
    row.innerHTML = `
      <label><span>Название поля</span><input data-key="label" value="${escapeHtml(question.label)}" maxlength="80"></label>
      <label><span>Как задать вопрос</span><input data-key="question" value="${escapeHtml(question.question)}" maxlength="240"></label>
      <label class="question-required"><input data-key="required" type="checkbox" ${question.required ? 'checked' : ''}> Обязательный</label>
      <button type="button" class="delete-question" aria-label="Удалить вопрос">×</button>`;
    row.querySelectorAll('[data-key]').forEach((input) => {
      input.addEventListener('input', () => {
        customQuestions[index][input.dataset.key] = input.type === 'checkbox' ? input.checked : input.value;
        $('#configState').textContent = 'Есть несохранённые изменения';
      });
    });
    row.querySelector('.delete-question').onclick = () => {
      customQuestions.splice(index, 1);
      renderQuestions();
      $('#configState').textContent = 'Есть несохранённые изменения';
    };
    list.append(row);
  });
}

function addQuestion() {
  const id = `question_${Date.now().toString(36)}`;
  customQuestions.push({ id, label: 'Дополнительное поле', question: 'Уточните дополнительную информацию.', required: true });
  renderQuestions();
  $('#configState').textContent = 'Есть несохранённые изменения';
}

async function saveBusinessConfig(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const formData = new FormData(form);
  const payload = Object.fromEntries(formData.entries());
  payload.language = 'ru';
  payload.custom_questions = customQuestions
    .map((question) => ({ ...question, label: question.label.trim(), question: question.question.trim() }))
    .filter((question) => question.label && question.question);
  $('#configState').textContent = 'Сохраняю…';
  const response = await fetch('/api/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  const data = await response.json();
  if (!response.ok) {
    $('#configState').textContent = 'Не удалось сохранить';
    showToast(data.detail?.errors?.map((e) => e.message).join('; ') || data.detail?.[0]?.msg || data.detail || 'Проверьте форму');
    return;
  }
  currentConfig = data;
  customQuestions = structuredClone(data.custom_questions || []);
  updateBusinessPreview();
  $('#configState').textContent = 'Все изменения сохранены';
  showToast('Настройки применены к AI');
}

// Where a saved conversation came from. Text labels, not only colour: the public concept demo
// (agent ids "shell_…") must never be mistaken for the owner's own assistants.
const HISTORY_ORIGINS = {
  own: 'Мой помощник',
  demo: 'Демо концепта МТС',
  other: 'Прочий агент / архив'
};
function historyOrigin(item) {
  if (['own','demo','other'].includes(item.origin)) return item.origin;
  if (String(item.agent_id || '').startsWith('shell_')) return 'demo';
  if (typeof productAgents !== 'undefined' && productAgents.some((agent) => agent.id === item.agent_id)) return 'own';
  return 'other';
}

function renderApplications(items) {
  const container = $('#applicationsList');
  if (!items.length) {
    container.innerHTML = '<div class="panel empty-state wide"><span>▤</span><b>Разговоров с этими условиями пока нет</b><p>Проведите веб-тест или измените фильтр.</p></div>';
    return;
  }
  container.innerHTML = items.map((item, index) => {
    const date = new Date(item.created_at).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' });
    const transcript = (item.transcript || []).map((message) => (
      `<div class="transcript-line ${message.role === 'assistant' ? 'assistant' : 'customer'}"><b>${message.role === 'assistant' ? 'AI' : 'Клиент'}</b><span>${escapeHtml(message.content)}</span></div>`
    )).join('');
    const extras = Object.entries(resultFields(item)).map(([key, value]) => (
      `<div><b>${escapeHtml(key)}</b><span>${escapeHtml(value ?? '—')}</span></div>`
    )).join('');
    return `<details class="panel application-item">
      <summary class="application-row">
        <div class="id">${escapeHtml(String(item.id).slice(0, 4))}</div>
        <div><b>${escapeHtml(item.customer_name || 'Веб-разговор')}</b><small>${escapeHtml(item.phone || 'Контакт не указан')}</small><span class="origin-chip origin-${historyOrigin(item)}">${HISTORY_ORIGINS[historyOrigin(item)]}</span></div>
        <div><b>${escapeHtml(item.intent || 'Намерение не указано')}</b><small>${date}</small></div>
        <div><b>${escapeHtml(item.result || 'Разговор ещё идёт')}</b><small>Нажмите, чтобы открыть диалог</small></div>
        <span class="mail-state ${item.email_sent ? 'sent' : ''}">${item.email_sent ? 'Email отправлен' : 'Сохранено'}</span>
      </summary>
      <div class="application-details">
        <div><p class="eyebrow">Расшифровка разговора</p><div class="saved-transcript">${transcript || '<span class="muted">Расшифровка отсутствует</span>'}</div>${productAgents.some(a=>a.id===item.agent_id) && item.transcript?.some(m=>m.role==='user') ? `<label>Вопрос для FAQ<select data-history-question="${index}">${item.transcript.filter(m=>m.role==='user').map(m=>`<option value="${escapeHtml(m.content.slice(0,240))}">${escapeHtml(m.content.slice(0,240))}</option>`).join('')}</select></label><button type="button" class="secondary-button" data-history-faq="${index}">Добавить свой ответ в черновик FAQ</button><p class="muted">Проверьте вопрос: фраза может содержать личные данные. Ответ владельца вводится вручную.</p>` : ''}</div>
        <div><p class="eyebrow">Результат и данные</p><div class="extra-answers">${extras || '<span class="muted">Дополнительных полей нет</span>'}</div></div>
      </div>
    </details>`;
  }).join('');
  container.querySelectorAll('[data-history-faq]').forEach(button=>button.onclick=()=>{
    const index=Number(button.dataset.historyFaq),item=items[index];
    addQuestionFromHistory(item.agent_id,container.querySelector('[data-history-question="'+index+'"]').value,item.id).catch(e=>showToast(e.message));
  });
}

async function loadApplications() {
  const query=new URLSearchParams();
  if($('#historyAgent').value)query.set('agent_id',$('#historyAgent').value);
  if($('#historyState').value)query.set('status',$('#historyState').value);
  query.set('limit','100');
  if($('#historySource')?.value)query.set('source',$('#historySource').value);
  const response = await fetch('/api/applications?'+query);
  if (!response.ok) {showToast('Не удалось загрузить обращения');return;}
  const items = (await response.json()).items;
  renderApplications(items);
}

function showView(name) {
  const labels = {
    overview:['Ваш бизнес · под контролем','Обзор'],assistant:['Роли и настройки','Помощники'],knowledge:['Подтверждённые ответы владельца','Знания'],channels:['Фактическое состояние подключений','Каналы'],
    call: ['Голос или текст в браузере', 'Проверка разговора'],
    setup: ['Конфигурация компании', 'Настройка AI-рецепциониста'],
    applications: ['История разговоров', 'Обращения клиентов']
    ,agents: ['Конструктор AI-сотрудника', 'Агенты'],evaluation:['Ограниченная проверка прототипа','Проверка помощника']
    ,quick:['Трек 1 · веб-прототип','Настройка помощника']
    ,telegram:['Канал доставки','Telegram']
  };
  if(!labels[name])name='overview';
  $$('.view').forEach((view) => view.classList.toggle('active', view.id === `view-${name}`));
  $$('.nav-item').forEach((button) => button.classList.toggle('active', button.dataset.view === (name==='quick'?'assistant':name)));
  $('#pageEyebrow').textContent = labels[name][0];
  $('#pageTitle').textContent = labels[name][1];
  if (name === 'applications') loadApplications();
  if (name === 'agents') loadAgentList().catch(error => showToast(error.message));
  if (name === 'telegram') refreshTelegramPanel().catch(error => showToast(error.message));
  if(['overview','assistant','knowledge','channels'].includes(name))refreshProductView(name).catch(error=>showToast(error.message));
  history.replaceState(null, '', `#${name}`);
  window.scrollTo(0,0);
}

async function initialize() {
  try {
    await Promise.all([loadConfig(), loadHealth()]);
    await loadAgentChoices();
    const view=location.hash.slice(1) || 'overview';
    if(view==='evaluation'){
      let remembered=null;try{remembered=localStorage.getItem('callwiseEvaluationAgent');}catch(_){}
      if(remembered)await openEvaluation(remembered);else showView('agents');
    }else showView(view);
  } catch (error) {
    setError(error.message);
  }
}

$$('.nav-item').forEach((button) => button.onclick = () => showView(button.dataset.view));
$('#start').onclick = () => startCall(true);
$('#voiceReviewSend').onclick = () => {
  if (!transcriptReview.confirm($('#voiceReviewText').value)) { showToast('Фраза пустая: исправьте текст или отбросьте её'); $('#voiceReviewText').focus(); }
};
$('#voiceReviewRetry').onclick = () => transcriptReview.discard();
// Closing or reloading the page cancels requests and playback and releases the microphone.
window.addEventListener('pagehide', () => {
  if (!active && !starting) return;
  active=false;starting=false;++sessionVersion;
  clearInterval(callTick);
  abortSession();
  transcriptReview.discard();
  stopRecording(true);
  stopPlayer();
  releaseMicrophone();
});
$('#downloadVoiceMetrics')?.addEventListener('click', () => {
  const report = {
    exported_at: new Date().toISOString(), model: modelLabel || 'неизвестно',
    note: 'Стадии не суммируются. Первая/повторная попытка не доказывает cold/warm модели. Отмены и ошибки исключены из статистики; 20 успешных — минимальная выборка, не гарантия точности p95.',
    summary: voiceMetrics.summary(), attempts: voiceMetrics.attempts,
  };
  const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 1)], { type: 'application/json' }));
  const link = Object.assign(document.createElement('a'), { href: url, download: 'focus-voice-metrics.json' });
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
$('#sendVoice').onclick = () => {
  if (active && recorder?.state === 'recording') stopRecording(false);
};
$('#textAnswerForm').onsubmit = sendTypedAnswer;
$('#configForm').onsubmit = saveBusinessConfig;
$('#configForm').addEventListener('input', () => $('#configState').textContent = 'Есть несохранённые изменения');
$('#addQuestion').onclick = addQuestion;
$('#refreshApplications').onclick = loadApplications;

window.addEventListener('DOMContentLoaded', initialize);
