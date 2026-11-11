// Real local transport: no mock reply, no browser/google speech synthesis.
import '../incremental-stt.js';
import { askPrivacy } from '../privacy-consent.mjs';
export async function requestJSON(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    credentials: "same-origin",
  });
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error("Сервер вернул некорректный ответ.");
  }
  if (!response.ok)
    throw new Error(data.detail || `Ошибка сервера (${response.status}).`);
  return data;
}

export function shellPayload(agent) {
  return {
    id: agent.id,
    name: agent.name,
    company: agent.company,
    role: agent.role,
    greeting: agent.greeting,
    knowledge: agent.knowledge || "",
    tone: agent.tone || "Дружелюбный",
    qa: agent.qa.map(({ question, answer, source }) => ({
      question,
      answer,
      source: source || "",
    })),
  };
}

export class LocalVoiceSession {
  constructor(agent, callbacks = {}) {
    this.agent = agent;
    this.callbacks = callbacks;
    this.state = "connecting";
    this.closed = false;
    this.id = null;
    this.requests = new Set();
    this.messages = [];
    this.media = null;
    this.audioContext = null;
    this.recorder = null;
    this.monitor = null;
    this.audio = null;
    this.audioUrl = null;
    this.settleAudio = null;
    this.autoListen = false;
    this.sound = true;
    this.busy = false;
    this.completed = false;
    this.endPromise = null;
    this.recordEpoch = 0;
    this.incremental = null;
    this.privacyReady = false;
    this.privacyAbort = new AbortController();
    this.emptyHearings = 0;
  }
  emitState(state, detail = "") {
    if (this.closed) return;
    this.state = state;
    this.callbacks.state?.(state, detail);
  }
  message(role, text) {
    if (this.closed) return;
    const m = { role, text };
    this.messages.push(m);
    this.callbacks.message?.(m);
  }
  async request(path, options = {}) {
    const controller = new AbortController();
    this.requests.add(controller);
    const timer = setTimeout(() => controller.abort(), 120000);
    try {
      return await requestJSON(path, { ...options, signal: controller.signal });
    } catch (error) {
      if (error.name === "AbortError" && !this.closed)
        throw new Error("Запрос остановлен или превысил время ожидания.");
      throw error;
    } finally {
      clearTimeout(timer);
      this.requests.delete(controller);
    }
  }
  async start({voice=true}={}) {
    this.emitState("connecting");
    try {
      const health = await this.request("/api/health");
      if (
        !health.local_only ||
        health.ai_provider !== "Ollama" ||
        !health.llm_ready
      )
        throw new Error(
          "Локальная модель недоступна. Проверьте Ollama и выбранную модель.",
        );
      this.health = health;
      if (this.closed) return;
      // Start is not aborted by close: a late created ID is finalized below, not left active.
      const started = await requestJSON("/api/shell/conversations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(shellPayload(this.agent)),
        signal: AbortSignal.timeout(20000),
      });
      this.id = started.interaction_id;
      if (this.closed) {
        await this.finalizeServer();
        return;
      }
      let greeting=started.greeting;
      if(started.privacy?.status==='pending'){
        this.emitState('connecting','Выберите согласие до начала разговора');
        const choice=await askPrivacy(started.privacy,this.privacyAbort.signal);
        if(this.closed)return;
        const consent=await this.request('/api/conversations/'+encodeURIComponent(this.id)+'/consent',{
          method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({accepted:choice,version:started.privacy.version})});
        if(this.closed)return;
        if(!consent.accepted){this.completed=true;this.message('assistant',consent.greeting);this.emitState('completed');return;}
        greeting=consent.greeting;
      }
      this.privacyReady=true;
      // Capture permission/device once after consent, but do not listen to our own greeting.
      if(voice) await this.acquireMicrophone();
      if(this.closed)return;
      this.message("assistant", greeting);
      this.emitState("ready");
      await this.speak(greeting);
      if (!this.closed) {
        this.emitState("ready");
        if(this.autoListen)await this.listen();
      }
    } catch (error) {
      if (!this.closed) {
        this.emitState("error", error.message);
        this.callbacks.error?.(error.message);
      }
    }
  }
  async speak(text) {
    if (this.closed || !this.sound) return;
    if (text.length > 1500) {
      this.callbacks.error?.(
        "Ответ слишком длинный для озвучки. Прочитайте его в диалоге.",
      );
      return;
    }
    try {
      this.emitState("speaking");
      const controller = new AbortController();
      this.requests.add(controller);
      const timer = setTimeout(() => controller.abort(), 30000);
      let response;
      try {
        response = await fetch("/api/speech", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text }),
          signal: controller.signal,
        });
      } finally {
        clearTimeout(timer);
        this.requests.delete(controller);
      }
      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || "Локальная озвучка недоступна.");
      }
      const blob = await response.blob();
      if (this.closed || !this.sound) return;
      this.releaseAudio();
      this.audioUrl = URL.createObjectURL(blob);
      this.audio = new Audio(this.audioUrl);
      this.audio.playbackRate = Number(this.agent.speed) || 1.2;
      this.audio.preservesPitch = true;
      await new Promise((resolve) => {
        this.settleAudio = resolve;
        this.audio.onended = resolve;
        this.audio.onerror = () => {
          this.callbacks.error?.(
            "Не удалось проиграть локальную озвучку. Продолжайте текстом.",
          );
          resolve();
        };
        this.audio.play().catch(() => {
          this.callbacks.error?.(
            "Браузер заблокировал звук. Нажмите «Повторить ответ» или продолжайте текстом.",
          );
          resolve();
        });
      });
    } catch (error) {
      if (!this.closed)
        this.callbacks.error?.(
          error.message || "Ошибка озвучки. Можно продолжить текстом.",
        );
    } finally {
      this.releaseAudio();
    }
  }
  releaseAudio() {
    this.settleAudio?.();
    this.settleAudio = null;
    if (this.audio) {
      this.audio.pause();
      this.audio.removeAttribute("src");
      this.audio.load();
      this.audio = null;
    }
    if (this.audioUrl) {
      URL.revokeObjectURL(this.audioUrl);
      this.audioUrl = null;
    }
  }
  async send(text) {
    if (this.closed || this.completed || !this.privacyReady || this.busy || !this.id || !text.trim())
      return;
    this.busy = true;
    this.stopRecording(true);
    this.message("user", text.trim());
    this.emitState("thinking");
    try {
      const data = await this.request("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          interaction_id: this.id,
          text: text.trim(),
          request_id: crypto.randomUUID(),
        }),
      });
      if (this.closed) return;
      this.message("assistant", data.text);
      this.completed = data.complete;
      await this.speak(data.text);
      if (this.closed) return;
      if (data.complete) {
        await this.end();
        return;
      }
      this.emitState("ready");
    } catch (error) {
      if (!this.closed) {
        this.autoListen = false;
        this.emitState("error", error.message);
        this.callbacks.error?.(error.message);
      }
    } finally {
      this.busy = false;
    }
    if (!this.closed && this.autoListen) await this.listen();
  }
  async toggleMic() {
    if (this.closed || this.completed || !this.privacyReady || !this.id || this.micPending) return;
    if (this.autoListen || this.state === "listening") {
      this.autoListen = false;
      this.stopRecording(true);
      this.releaseMedia();
      if(!this.busy && this.state!=='speaking')this.emitState("ready", "Микрофон выключен. Можно продолжить текстом.");
      return;
    }
    if(this.busy || this.state==='speaking')return;
    await this.acquireMicrophone();
    if(this.autoListen)await this.listen();
  }
  async acquireMicrophone() {
    if(this.closed || this.completed || !this.privacyReady || this.micPending)return;
    if(this.media){this.autoListen=true;return;}
    if (
      !navigator.mediaDevices?.getUserMedia ||
      typeof MediaRecorder === "undefined"
    ) {
      this.callbacks.error?.(
        "Микрофон недоступен в этом браузере. Используйте localhost/HTTPS и Chrome или Edge.",
      );
      return;
    }
    if (!this.health.local_speech?.stt_weights) {
      this.callbacks.error?.(
        "Локальные модели распознавания не найдены. Можно продолжить текстом.",
      );
      return;
    }
    this.emitState("connecting", "Разрешите доступ к микрофону");
    this.micPending = true;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount:1,
        },
      });
      if (this.closed) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      this.media = stream;
      this.autoListen = true;
      this.media.getAudioTracks?.().forEach(track=>{
        track.onended=()=>{
          if(this.closed || !this.media)return;
          this.autoListen=false;this.stopRecording(true);this.releaseMedia();
          this.emitState('ready','Микрофон отключился. Продолжите текстом или подключите устройство.');
        };
      });
    } catch (error) {
      if (!this.closed) {
        this.autoListen = false;
        this.releaseMedia();
        this.emitState("error");
        this.callbacks.error?.(
          error.name === "NotAllowedError"
            ? "Доступ к микрофону запрещён. Разрешите его в браузере или продолжите текстом."
            : error.name === "NotFoundError"
              ? "Микрофон не найден. Подключите его или продолжите текстом."
              : "Не удалось включить микрофон. Проверьте устройство.",
        );
      }
    } finally {
      this.micPending = false;
    }
  }
  async listen() {
    if (this.closed || !this.autoListen || !this.media || this.busy) return;
    try {
      this.stopRecording(true);
      this.audioContext ??= new AudioContext();
      await this.audioContext.resume();
      if (this.closed || !this.autoListen) return;
      const source = this.audioContext.createMediaStreamSource(this.media);
      const analyser = this.audioContext.createAnalyser();
      analyser.fftSize = 2048;
      source.connect(analyser);
      this.source = source;
      const epoch = ++this.recordEpoch;
      const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find(
        (type) => MediaRecorder.isTypeSupported(type),
      );
      const recorder = new MediaRecorder(
        this.media,
        mime ? { mimeType: mime } : undefined,
      );
      this.recorder = recorder;
      const chunks = [];
      const contextText=this.messages.filter((m)=>m.role==='assistant').at(-1)?.text || '';
      const progressive=new globalThis.CallwiseSTT.IncrementalSTT({
        streaming:true,
        transcribe:(blob,signal,chunk)=> {
          const form=new FormData();
          form.append('file',blob,'chunk.wav');form.append('interaction_id',this.id);
          form.append('context',contextText);
          form.append('mode','preview');form.append('stream_id',chunk.streamId);form.append('sequence',chunk.sequence);
          return requestJSON('/api/transcribe',{method:'POST',body:form,signal});
        },
        onPartial:(text)=> {
          if (epoch===this.recordEpoch && this.state==='listening' && text)
            this.emitState('listening','Уже распознано: '+text.slice(-160));
        },
      });
      this.incremental=progressive;
      let streaming=false;
      try {await progressive.attach(this.audioContext,source);streaming=!progressive.cancelled;}
      catch {progressive.cancel();}
      if (this.closed || epoch!==this.recordEpoch) return;
      recorder.ondataavailable = (e) => {
        if (e.data.size) chunks.push(e.data);
      };
      recorder.onerror = () => {
        this.autoListen = false;
        this.stopRecording(true);
        this.releaseMedia();
        this.emitState("error");
        this.callbacks.error?.("Ошибка записи микрофона. Продолжайте текстом.");
      };
      recorder.onstop = async () => {
        if (this.closed || epoch !== this.recordEpoch) return;
        this.stopMonitor();
        if (!chunks.length) {
          progressive.cancel();this.autoListen=false;this.releaseMedia();
          this.emitState('ready','Пустая запись. Нажмите микрофон повторно.');
          return;
        }
        this.emitState("transcribing");
        this.busy = true;
        try {
          let data;
          if (streaming) {
            try {
              await progressive.finish();
              if (this.closed || epoch!==this.recordEpoch) return;
              const form=new FormData();
              form.append('file',progressive.finalBlob(),'utterance.wav');
              form.append('interaction_id',this.id);form.append('context',contextText);
              form.append('mode','final');form.append('stream_id',progressive.streamId);
              data=await this.request('/api/transcribe',{method:'POST',body:form});
            } catch {
              if (this.closed || epoch!==this.recordEpoch) return;
              progressive.cancel();
              this.emitState('transcribing','Поток прервался. Распознаю сохранённую запись целиком…');
            }
          }
          if (!data) {
          const form = new FormData();
          form.append(
            "file",
            new Blob(chunks, { type: mime || "audio/webm" }),
            mime?.includes("mp4") ? "voice.mp4" : "voice.webm",
          );
          form.append("interaction_id", this.id);
          form.append('mode','final');
          form.append(
            "context",
            this.messages.filter((m) => m.role === "assistant").at(-1)?.text ||
              "",
          );
          data = await this.request("/api/transcribe", {
            method: "POST",
            body: form,
          });
          }
          if (this.closed || epoch!==this.recordEpoch) return;
          this.busy = false;
          if (data.text?.trim()) {this.emptyHearings=0;await this.send(data.text.trim());}
          else {
            if(data.speaker?.requires_repeat){
              this.emitState('ready',data.speaker.message);
              this.nextListeningHint=data.speaker.message;
              if(this.autoListen)await this.listen();
              return;
            }
            this.emptyHearings++;
            if(this.emptyHearings>=3){this.autoListen=false;this.releaseMedia();this.emitState('ready','Три попытки без речи. Продолжите текстом или проверьте микрофон.');return;}
            this.emitState("ready", "Не расслышал. Попробуйте ещё раз.");
            if (this.autoListen) await this.listen();
          }
        } catch (error) {
          if (!this.closed) {
            this.autoListen = false;
            this.releaseMedia();
            this.emitState("error");
            this.callbacks.error?.(error.message);
          }
        } finally {
          this.busy = false;
        }
      };
      recorder.start(250);
      this.emitState("listening",this.nextListeningHint || (streaming?'Слушаю. Говорите ближе к микрофону':'Поток недоступен. Распознаю после окончания фразы'));
      this.nextListeningHint=null;
      const samples = new Uint8Array(analyser.fftSize);
      let noiseFloor = 0.008,
        speech = false,
        frames = 0,
        lastVoice = performance.now();
      const began = performance.now();
      const endSilenceMs=/телефон|номер|по цифр/i.test(contextText)?1800:1200;
      const monitor = () => {
        if (
          this.closed ||
          epoch !== this.recordEpoch ||
          recorder.state !== "recording"
        )
          return;
        analyser.getByteTimeDomainData(samples);
        let power = 0;
        for (const sample of samples) power += ((sample - 128) / 128) ** 2;
        const rms = Math.sqrt(power / samples.length),
          threshold = Math.max(0.014, noiseFloor * (speech ? 2.1 : 2.7));
        const now = performance.now();
        if (rms > threshold) {
          frames++;
          if (frames >= 3) {
            speech = true;
            lastVoice = now;
          }
        } else if (!speech) {
          frames = 0;
          noiseFloor = 0.96 * noiseFloor + 0.04 * rms;
        }
        const lastDetectedVoice=progressive.speakerChecked?progressive.lastPrimaryVoiceAt:lastVoice;
        if (speech && (now - lastDetectedVoice > endSilenceMs || now - began > 120000)) {
          recorder.stop();
          return;
        }
        if (!speech && now - began > 15000) {
          this.autoListen = false;
          this.stopRecording(true);
          this.releaseMedia();
          this.emitState(
            "ready",
            "Речи не слышно. Нажмите микрофон, чтобы повторить.",
          );
          return;
        }
        this.monitor = requestAnimationFrame(monitor);
      };
      this.monitor = requestAnimationFrame(monitor);
    } catch (error) {
      this.autoListen = false;
      this.stopRecording(true);
      this.releaseMedia();
      this.emitState("error");
      this.callbacks.error?.(
        "Не удалось начать запись. Можно продолжить текстом.",
      );
    }
  }
  stopMonitor() {
    if (this.monitor) cancelAnimationFrame(this.monitor);
    this.monitor = null;
    try {
      this.source?.disconnect();
    } catch {}
    this.source = null;
  }
  stopRecording(discard) {
    if (discard) {
      this.recordEpoch++;
      this.incremental?.cancel();
      this.incremental=null;
    }
    this.stopMonitor();
    if (this.recorder?.state === "recording") this.recorder.stop();
    this.recorder = null;
  }
  releaseMedia() {
    this.media?.getTracks().forEach((track) => track.stop());
    this.media = null;
    const context = this.audioContext;
    this.audioContext = null;
    context?.close().catch(() => {});
  }
  async repeat() {
    if (
      this.closed ||
      this.busy ||
      ["speaking", "listening", "transcribing"].includes(this.state)
    )
      return;
    const text = this.messages
      .filter((m) => m.role === "assistant")
      .at(-1)?.text;
    if (text) {
      this.busy = true;
      await this.speak(text);
      this.busy = false;
      if (!this.closed) this.emitState("ready");
      if (!this.closed && this.autoListen) await this.listen();
    }
  }
  async finalizeServer() {
    if (!this.id) return null;
    return requestJSON("/api/application", {
      method: "POST",
      keepalive: true,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ interaction_id: this.id }),
      signal: AbortSignal.timeout(120000),
    });
  }
  end() {
    if (this.endPromise) return this.endPromise;
    this.closed = true;
    this.privacyAbort.abort();
    this.autoListen = false;
    this.stopRecording(true);
    this.releaseMedia();
    this.releaseAudio();
    this.requests.forEach((c) => c.abort());
    this.callbacks.state?.(
      "ended",
      "Разговор завершён. Сохраняю на локальном сервере…",
    );
    this.endPromise = this.finalizeServer()
      .then((result) => {
        this.callbacks.ended?.(result);
        return result;
      })
      .catch((error) => {
        this.callbacks.error?.(
          "Не удалось подтвердить сохранение: " + error.message,
        );
        return null;
      });
    return this.endPromise;
  }
}
