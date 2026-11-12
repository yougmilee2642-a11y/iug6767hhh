// «Фокус», the manager's voice assistant: a push-to-talk question (or one after «Привет, Фокус» /
// «Окей, Фокус») -> /api/meet/voice/ask -> a short phrase aloud, the full answer with sources on screen.
// Without the opt-in wake mode the microphone is on only while the user holds the turn.
const MAX_SECONDS = 30;
const VOICE_RATE = 1.25;         // скорость речи Фокуса (1 — обычная)
const PACKET_MS = 100;           // pcm-capture-worklet posts 1600 samples at 16 kHz
const WAKE_SILENCE_MS = 700;     // end of a wake segment
const QUESTION_SILENCE_MS = 1300;
const WAKE_MAX_MS = 6000;
const QUESTION_MAX_MS = 15000;
const QUESTION_WAIT_MS = 6000;
const PREROLL_PACKETS = 3;

export function voiceAssistant(h) {
  const { node, makeButton, request, state, openSource, dateLabel } = h;
  let capture = null;
  let player = null;
  let sequence = 0;
  let wake = null;
  const panel = node('section', 'voice-panel');
  panel.id = 'voice-panel';
  panel.hidden = true;
  panel.setAttribute('aria-label', 'Голосовой помощник Фокус');
  const status = node('p', 'voice-status', '');
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');
  const heard = node('p', 'voice-heard', '');
  const result = node('div', 'voice-result');
  // Фокус озвучивает все ответы: это решение владельца компьютера, флажок «я один» убран.
  const SPEAK_EVERYTHING = true;
  const form = node('form', 'voice-form');
  const typed = node('input', '');
  typed.type = 'text';
  typed.maxLength = 1000;
  typed.placeholder = 'Или напишите вопрос';
  typed.setAttribute('aria-label', 'Вопрос помощнику текстом');
  form.append(typed, makeButton('Спросить', null, 'secondary-button', 'submit'));
  form.addEventListener('submit', (event) => { event.preventDefault(); const text = typed.value.trim(); if (text) { typed.value = ''; void ask(text); } });
  // «Привет, Фокус» слушается автоматически, пока пользователь в системе.
  // Речь распознаётся на этом компьютере и не сохраняется; выключить можно ссылкой в панели.
  const WAKE_KEY = 'focus-wake-off';
  const wakeWanted = () => { try { return localStorage.getItem(WAKE_KEY) !== '1'; } catch { return true; } };
  let wakeStarting = false;
  let wakeFailed = false;
  const wakeBox = node('div', 'voice-wake');
  const wakeNote = node('span', 'voice-wake-note', '');
  const wakeToggle = makeButton('', () => {
    const off = Boolean(wake);
    try { localStorage.setItem(WAKE_KEY, off ? '1' : '0'); } catch { /* storage off */ }
    wakeFailed = false;
    if (off) void stopWake('Фокус больше не слушает «Привет, Фокус».'); else void startWake();
    syncWake();
  }, 'voice-wake-toggle');
  wakeBox.append(wakeNote, wakeToggle);
  function syncWake() {
    wakeNote.textContent = wake ? 'Слушаю «Привет, Фокус»' : 'Не слушаю «Привет, Фокус»';
    wakeToggle.textContent = wake ? 'Не слушать' : 'Слушать';
    talk.classList.toggle('listening', Boolean(wake));
    talk.title = wake ? 'Фокус слушает «Привет, Фокус». Нажмите, чтобы сразу задать вопрос (Alt+V)'
      : 'Нажмите и говорите; нажмите ещё раз, чтобы отправить (Alt+V)';
  }
  const head = node('div', 'voice-panel-head');
  const close = makeButton('×', () => {
    stopSpeaking(); void cancelCapture();
    if (wake && wake.mode === 'question') { wake.mode = 'wake'; wake.waitMs = 0; }
    panel.hidden = true;
  }, 'icon-button');
  close.setAttribute('aria-label', 'Свернуть Фокус');
  const hush = makeButton('Остановить озвучку', stopSpeaking, 'secondary-button');
  hush.hidden = true;
  head.append(node('h2', '', 'Фокус'), close);
  panel.append(head, status, heard, result, hush, form, wakeBox);
  document.body.append(panel);

  const talk = node('button', 'voice-talk-button', 'Спросить голосом');
  talk.type = 'button';
  talk.title = 'Нажмите и говорите; нажмите ещё раз, чтобы отправить (Alt+V)';
  talk.addEventListener('click', () => void toggle());
  document.addEventListener('keydown', (event) => {
    if (event.altKey && !event.repeat && (event.code === 'KeyV') && state.user) { event.preventDefault(); void toggle(); }
    if (event.key === 'Escape' && capture) void cancelCapture();
  });

  function meetingId() {
    return state.page === 'meeting' ? state.meetingData?.meeting?.id ?? null : null;
  }

  function setStatus(text) { status.textContent = text; }

  // Приветствие при открытии и подсказки — как у голосового помощника, а не пустая форма.
  const SUGGESTIONS = ['Какие у меня сегодня встречи?', 'Какие ближайшие сроки?', 'Что важного сегодня?', 'Что ты умеешь?'];
  function partOfDay() {
    const hour = Number(new Intl.DateTimeFormat('ru-RU', { hour: 'numeric', hour12: false, timeZone: 'Europe/Minsk' }).format(new Date()));
    return hour >= 5 && hour < 12 ? 'Доброе утро' : hour < 18 && hour >= 12 ? 'Добрый день' : hour >= 18 && hour < 23 ? 'Добрый вечер' : 'Доброй ночи';
  }
  function intro() {
    if (result.childNodes.length || heard.textContent) return;
    const name = String(state.user?.name || '').trim().split(/\s+/)[0];
    result.append(node('p', 'voice-phrase voice-hello', `${partOfDay()}${name ? `, ${name}` : ''}! Я Фокус. Спросите голосом или текстом.`));
    const chips = node('div', 'voice-suggestions');
    for (const text of SUGGESTIONS) chips.append(makeButton(text, () => void ask(text), 'voice-suggestion'));
    result.append(chips);
  }

  function mount(container) {
    if (!state.user || !state.capabilities.includes('qa.ask')) { talk.remove(); panel.hidden = true; return; }
    talk.textContent = capture ? 'Отправить вопрос' : 'Спросить голосом';
    talk.classList.toggle('recording', Boolean(capture));
    container.prepend(talk);
    syncWake();
    // Автоматически: после входа и после окончания записи встречи.
    if (!wake && !wakeStarting && !wakeFailed && wakeWanted() && !capture && !state.voiceCapture?.recording) void startWake();
  }

  function reset() {
    sequence++; stopSpeaking(); void cancelCapture(); void stopWake('');
    wakeFailed = false;
    panel.hidden = true; heard.textContent = ''; result.replaceChildren(); setStatus('');
  }

  async function toggle() {
    if (capture) { await finishCapture(); return; }
    panel.hidden = false;
    intro();
    stopSpeaking();
    if (wake) {
      // Кнопка микрофона при включённом «Привет, Фокус»: сразу слушать вопрос.
      wake.mode = 'question'; wake.waitMs = 0; wake.segment = []; wake.speechMs = 0; wake.silenceMs = 0;
      if (wake.context.state === 'suspended') await wake.context.resume().catch(() => {});
      setStatus('Слушаю вопрос…');
      return;
    }
    if (state.voiceCapture?.recording) { setStatus('Идёт запись встречи. Остановите её, чтобы спросить Фокус.'); return; }
    if (!navigator.mediaDevices?.getUserMedia || typeof AudioWorkletNode === 'undefined' || !window.CallwiseSTT?.wavPCM) {
      setStatus('Браузер не даёт записать микрофон. Напишите вопрос текстом.');
      typed.focus();
      return;
    }
    let stream; let context;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
      context = new AudioContext();
      await context.audioWorklet.addModule('/static/pcm-capture-worklet.js');
      const source = context.createMediaStreamSource(stream);
      const worklet = new AudioWorkletNode(context, 'callwise-pcm');
      const gain = context.createGain();
      gain.gain.value = 0;
      source.connect(worklet); worklet.connect(gain); gain.connect(context.destination);
      capture = { stream, context, worklet, frames: [], samples: 0, flushed: null, epoch: state.epoch };
      worklet.port.onmessage = ({ data }) => {
        if (data === 'flushed') { capture?.flushed?.(); return; }
        if (data instanceof Float32Array && capture) {
          capture.frames.push(data); capture.samples += data.length;
          if (capture.samples >= 16000 * MAX_SECONDS) void finishCapture();
        }
      };
      capture.timer = setTimeout(() => void finishCapture(), MAX_SECONDS * 1000 + 500);
      setStatus(`Слушаю… Нажмите «Отправить вопрос» или Alt+V. До ${MAX_SECONDS} секунд.`);
      heard.textContent = '';
    } catch {
      stream?.getTracks().forEach((track) => track.stop());
      await context?.close().catch(() => {});
      capture = null;
      setStatus('Нет доступа к микрофону. Разрешите его в браузере или напишите вопрос текстом.');
    }
    syncButton();
  }

  function syncButton() {
    talk.textContent = capture ? 'Отправить вопрос' : 'Спросить голосом';
    talk.classList.toggle('recording', Boolean(capture));
    talk.setAttribute('aria-pressed', capture ? 'true' : 'false');
  }

  async function release(current) {
    clearTimeout(current.timer);
    current.stream.getTracks().forEach((track) => track.stop());
    await current.context.close().catch(() => {});
  }

  async function cancelCapture() {
    const current = capture;
    if (!current) return;
    capture = null; syncButton();
    await release(current);
    setStatus('Запись отменена.');
  }

  async function finishCapture() {
    const current = capture;
    if (!current) return;
    capture = null; syncButton();
    await new Promise((resolve) => {
      current.flushed = resolve;
      current.worklet.port.postMessage('flush');
      setTimeout(resolve, 400);
    });
    await release(current);
    if (current.epoch !== state.epoch) return;
    if (current.samples < 16000 * 0.4) { setStatus('Слишком коротко. Нажмите и задайте вопрос.'); return; }
    const mine = ++sequence;
    const started = performance.now();
    setStatus('Распознаю вопрос…');
    const form = new FormData();
    form.append('file', window.CallwiseSTT.wavPCM(current.frames), 'question.wav');
    try {
      const { text } = await request('/voice/transcribe', { method: 'POST', body: form });
      if (mine !== sequence) return;
      const asrMs = Math.round(performance.now() - started);
      if (!text) { setStatus('Не расслышал вопрос. Повторите или напишите его.'); return; }
      await ask(text, { asrMs });
    } catch (error) {
      if (mine === sequence) setStatus(error.message || 'Не удалось распознать вопрос.');
    }
  }

  async function ask(text, timing = {}) {
    const mine = ++sequence;
    panel.hidden = false;
    stopSpeaking();
    heard.textContent = timing.quiet ? '' : `Вы: ${text}`;
    result.replaceChildren();
    setStatus('Ищу ответ…');
    const started = performance.now();
    let reply;
    try {
      const id = meetingId();
      reply = await request('/voice/ask', { method: 'POST', body: { text, speak_private: SPEAK_EVERYTHING, ...(id ? { meeting_id: Number(id) } : {}) } });
    } catch (error) {
      if (mine === sequence) setStatus(error.message || 'Не удалось получить ответ.');
      return;
    }
    if (mine !== sequence) return;
    const answerMs = Math.round(performance.now() - started);
    renderReply(reply);
    window.CallwiseVoiceTiming = { asr_ms: timing.asrMs ?? null, answer_ms: answerMs, tts_ms: null, route: reply.route };
    if (!reply.speak || !reply.spoken) {
      setStatus(reply.silent_reason || 'Ответ показан на экране.');
      return;
    }
    setStatus('Озвучиваю…');
    const ttsStarted = performance.now();
    try {
      const response = await fetch('/api/speech', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: reply.spoken, voice: 'focus' }), credentials: 'same-origin' });
      if (!response.ok) throw new Error('tts');
      const audio = await response.blob();
      if (mine !== sequence) return;
      window.CallwiseVoiceTiming.tts_ms = Math.round(performance.now() - ttsStarted);
      player = new Audio(URL.createObjectURL(audio));
      // Быстрее, без «мультяшного» голоса: браузер сохраняет высоту тона.
      player.preservesPitch = true;
      player.playbackRate = VOICE_RATE;
      if (wake) wake.paused = true;  // never hear itself
      hush.hidden = false;
      player.addEventListener('ended', () => { stopSpeaking(); setStatus('Готово.'); }, { once: true });
      await player.play();
      setStatus('Говорю. Полный ответ — ниже.');
    } catch {
      stopSpeaking();
      if (mine === sequence) setStatus('Озвучка недоступна — ответ на экране.');
    }
  }

  function stopSpeaking() {
    if (player) { player.pause(); URL.revokeObjectURL(player.src); player = null; }
    hush.hidden = true;
    if (wake) { wake.paused = false; wake.segment = []; wake.speechMs = 0; wake.silenceMs = 0; }
  }

  // ---------- «Привет, Фокус»: voice-activity detection here, short segments to the local ASR ----------
  async function startWake() {
    if (wake || wakeStarting || !state.user) return;
    if (capture || state.voiceCapture?.recording) return;
    if (!navigator.mediaDevices?.getUserMedia || typeof AudioWorkletNode === 'undefined' || !window.CallwiseSTT?.wavPCM) {
      wakeFailed = true;
      setStatus('Браузер не даёт слушать микрофон. Используйте кнопку или напишите вопрос.');
      return;
    }
    wakeStarting = true;
    let stream; let context;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
      context = new AudioContext();
      await context.audioWorklet.addModule('/static/pcm-capture-worklet.js');
      const source = context.createMediaStreamSource(stream);
      const worklet = new AudioWorkletNode(context, 'callwise-pcm');
      const gain = context.createGain();
      gain.gain.value = 0;
      source.connect(worklet); worklet.connect(gain); gain.connect(context.destination);
      wake = { stream, context, worklet, epoch: state.epoch, mode: 'wake', preroll: [], segment: [], speechMs: 0,
        silenceMs: 0, waitMs: 0, noise: 0.004, busy: false, paused: false };
      worklet.port.onmessage = ({ data }) => { if (data instanceof Float32Array) acceptWakeFrame(data); };
    } catch {
      stream?.getTracks().forEach((track) => track.stop());
      await context?.close().catch(() => {});
      wake = null; wakeStarting = false; wakeFailed = true;
      setStatus('Нет доступа к микрофону. Разрешите его в браузере, и Фокус начнёт слушать «Привет, Фокус».');
      syncWake();
      return;
    }
    wakeStarting = false;
    // Браузер может держать звук на паузе до первого действия на странице — продолжаем по первому клику или клавише.
    if (context.state === 'suspended') {
      const resume = () => { void context.resume().catch(() => {}); };
      document.addEventListener('pointerdown', resume, { once: true, capture: true });
      document.addEventListener('keydown', resume, { once: true, capture: true });
    }
    syncWake();
    setStatus('Скажите «Привет, Фокус» и задайте вопрос.');
  }

  async function stopWake(message) {
    const current = wake;
    if (!current) return;
    wake = null;
    current.stream.getTracks().forEach((track) => track.stop());
    await current.context.close().catch(() => {});
    syncWake();
    if (message) setStatus(message);
  }

  function acceptWakeFrame(frame) {
    const current = wake;
    if (!current || current.paused || current.busy) return;
    if (current.epoch !== state.epoch || state.voiceCapture?.recording) {
      void stopWake('Фокус перестал слушать: началась запись встречи или сменился профиль.');
      return;
    }
    let energy = 0;
    for (let i = 0; i < frame.length; i++) energy += frame[i] * frame[i];
    const rms = Math.sqrt(energy / frame.length);
    const voiced = rms > Math.max(0.012, current.noise * 3);
    const asking = current.mode === 'question';
    if (!current.segment.length) {
      if (voiced) {
        current.segment = [...current.preroll, frame]; current.preroll = [];
        current.speechMs = PACKET_MS; current.silenceMs = 0;
        return;
      }
      current.noise = current.noise * 0.95 + rms * 0.05;
      current.preroll.push(frame);
      if (current.preroll.length > PREROLL_PACKETS) current.preroll.shift();
      if (asking && (current.waitMs += PACKET_MS) > QUESTION_WAIT_MS) {
        current.mode = 'wake'; current.waitMs = 0;
        setStatus('Вопрос не прозвучал. Фокус снова ждёт «Привет, Фокус».');
      }
      return;
    }
    current.segment.push(frame);
    if (voiced) { current.speechMs += PACKET_MS; current.silenceMs = 0; } else current.silenceMs += PACKET_MS;
    const length = current.segment.length * PACKET_MS;
    if (current.silenceMs >= (asking ? QUESTION_SILENCE_MS : WAKE_SILENCE_MS) || length >= (asking ? QUESTION_MAX_MS : WAKE_MAX_MS)) {
      const frames = current.segment; const speech = current.speechMs;
      current.segment = []; current.speechMs = 0; current.silenceMs = 0;
      if (speech >= 400) void handleSegment(current, frames);
    }
  }

  async function handleSegment(current, frames) {
    current.busy = true;
    const body = new FormData();
    body.append('file', window.CallwiseSTT.wavPCM(frames), 'segment.wav');
    try {
      const started = performance.now();
      if (current.mode === 'question') {
        current.mode = 'wake'; current.waitMs = 0;
        setStatus('Распознаю вопрос…');
        const { text } = await request('/voice/transcribe', { method: 'POST', body });
        if (wake !== current) return;
        if (text) await ask(text, { asrMs: Math.round(performance.now() - started) });
        else setStatus('Не расслышал вопрос. Скажите «Привет, Фокус» ещё раз.');
        return;
      }
      const reply = await request('/voice/wake', { method: 'POST', body });
      if (wake !== current || !reply.wake) return;
      panel.hidden = false;
      chime();
      if (reply.question) {
        await ask(reply.question, { asrMs: Math.round(performance.now() - started) });
      } else {
        heard.textContent = ''; result.replaceChildren();
        // Отзывается голосом («Добрый день, Марина! Слушаю.»), затем ждёт вопрос.
        await ask('Фокус', { quiet: true });
        if (wake !== current) return;
        current.mode = 'question'; current.waitMs = 0;
        setStatus('Слушаю вопрос…');
      }
    } catch (error) {
      if (wake === current) { wakeFailed = true; await stopWake(error.message || 'Фокус перестал слушать из-за ошибки.'); }
    } finally {
      current.busy = false;
    }
  }

  function chime() {
    try {
      const context = wake?.context;
      if (!context) return;
      const tone = context.createOscillator();
      const level = context.createGain();
      tone.frequency.value = 880;
      level.gain.setValueAtTime(0.08, context.currentTime);
      level.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + 0.18);
      tone.connect(level); level.connect(context.destination);
      tone.start(); tone.stop(context.currentTime + 0.2);
    } catch { /* a missing chime must not stop the assistant */ }
  }

  function renderReply(reply) {
    result.replaceChildren();
    const phrase = node('p', `voice-phrase${reply.speak ? '' : ' voice-phrase-silent'}`, reply.display);
    result.append(phrase);
    if (reply.route === 'chat' || reply.route === 'restricted') return;
    if (reply.route === 'action_draft') {
      result.append(node('p','',reply.display),makeButton('Проверить действие',()=>h.proposeAction(reply.proposed_action),'secondary-button'));
      return;
    }

    if (reply.route === 'agenda') {
      const list = node('ul', 'voice-items');
      for (const item of (reply.answer?.items || []).slice(0, 12)) {
        const row = node('li', item.late ? 'late' : '');
        const copy = node('span', '');
        copy.append(node('b', '', item.title), node('small', '', item.meta || ''));
        row.append(copy);
        if (item.meeting_id) {
          const tab = item.kind === 'task' ? 'tasks' : item.kind === 'decision' ? 'protocol' : undefined;
          row.append(makeButton('Открыть', () => void h.openMeeting(item.meeting_id, tab), 'voice-item-open'));
        }
        list.append(row);
      }
      if (list.childNodes.length) result.append(list);
      const page = { my_tasks: 'tasks', person_tasks: 'tasks', deadlines: 'tasks', documents: 'knowledge' }[reply.answer?.kind];
      if (page) result.append(makeButton(page === 'tasks' ? 'Все задачи' : 'Открыть знания', () => h.navigate(page), 'secondary-button'));

      return;
    }
    if (reply.route === 'action') {
      result.append(makeButton(reply.open_page === 'calendar' ? 'Открыть встречи' : 'Открыть задачи', () => {
        h.navigate(reply.open_page === 'calendar' ? 'meetings' : 'tasks');
      }, 'secondary-button'));
      return;
    }
    const answer = reply.answer || {};
    if (reply.route === 'briefing') {
      result.append(node('p','',answer.spoken || reply.display));
      for (const warning of answer.warnings || []) result.append(node('p','voice-warning',warning));
      result.append(makeButton('Открыть брифинг',()=>h.navigate('briefing'),'secondary-button'));
      return;
    }
    if (reply.route === 'assistant_read') {
      for (const claim of answer.claims || []) {
        result.append(node('p','',claim.text));
        for(const source of claim.sources || [])result.append(makeButton(source.title,()=>void openSource(source.kind,source.id,source.quote,source),'citation-chip'));
      }
      for(const warning of answer.warnings || [])result.append(node('p','voice-warning',warning));
      return;
    }
    if (reply.route === 'knowledge') {
      for (const claim of answer.claims || []) {
        const card = node('article', 'voice-claim');
        card.append(node('p', '', claim.text));
        for (const source of claim.sources || []) {
          card.append(makeButton(`${source.title || 'Источник'} · ${dateLabel(source.source_at)}`,
            () => void openSource('fragment', source.id, source.quote, source), 'citation-chip'));
        }
        result.append(card);
      }
      return;
    }
    const list = node('ul', 'voice-metrics');
    for (const metric of answer.metrics || []) {
      list.append(node('li', '', `${metric.label}: ${metric.value ?? 'нет данных'}${metric.value == null ? '' : ` ${metric.unit}`}`));
    }
    result.append(list);
    for (const warning of answer.warnings || []) result.append(node('p', 'voice-warning', warning));
    result.append(makeButton('Открыть обзор', () => h.navigate('overview'), 'secondary-button'));
  }

  return { mount, reset, ask };
}
