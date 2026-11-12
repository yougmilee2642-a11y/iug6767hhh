// Pause-delimited streaming, one STT request at a time; only final text goes to AI.
(function (root) {
  function wavPCM(parts) {
    const size=parts.reduce((n,p)=>n+p.length,0);
    const buffer=new ArrayBuffer(44+size*2),view=new DataView(buffer);
    const ascii=(offset,text)=>[...text].forEach((c,i)=>view.setUint8(offset+i,c.charCodeAt(0)));
    ascii(0,'RIFF');view.setUint32(4,36+size*2,true);ascii(8,'WAVE');ascii(12,'fmt ');
    view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);
    view.setUint32(24,16000,true);view.setUint32(28,32000,true);
    view.setUint16(32,2,true);view.setUint16(34,16,true);ascii(36,'data');view.setUint32(40,size*2,true);
    let offset=44;
    for (const part of parts) for (const sample of part) {
      const value=Math.max(-1,Math.min(1,sample));
      view.setInt16(offset,Math.round(value*(value<0?32768:32767)),true);offset+=2;
    }
    return new Blob([buffer],{type:'audio/wav'});
  }

  class IncrementalSTT {
    constructor({transcribe,onPartial=()=>{},streaming=false}) {
      this.transcribe=transcribe;this.onPartial=onPartial;
      this.current=[];this.pending=[];this.parts=[];this.waiters=[];
      this.total=0;this.silence=0;this.voiced=false;this.lastCut=-48000;
      this.noiseFloor=0.008;this.running=false;this.cancelled=false;this.finished=false;
      this.error=null;this.controller=null;this.node=null;this.gain=null;
      this.metrics=[];
      this.streaming=streaming;this.waveform=[];this.sequence=0;
      this.speakerChecked=false;this.lastPrimaryVoiceAt=performance.now();
      this.streamId=globalThis.crypto?.randomUUID?.() || 'stt-'+Date.now()+'-'+Math.random().toString(36).slice(2);
    }
    async attach(context,source) {
      if (!context.audioWorklet || typeof AudioWorkletNode==='undefined') throw new Error('AudioWorklet недоступен');
      await context.audioWorklet.addModule('/static/pcm-capture-worklet.js');
      if (this.cancelled) return;
      this.node=new AudioWorkletNode(context,'focus-pcm');
      this.node.port.onmessage=({data}) => {
        if (data==='flushed') {this.flushAck?.();return;}
        this.push(data);
      };
      this.node.onprocessorerror=()=> {
        this.error=new Error('Потоковая запись прервалась');
        this.flushAck?.();
      };
      this.gain=context.createGain();this.gain.gain.value=0;
      source.connect(this.node);this.node.connect(this.gain);this.gain.connect(context.destination);
    }
    push(frame) {
      if (this.cancelled || this.finished || this.error) return;
      this.total+=frame.length;
      if (this.total>16000*120) {this.error=new Error('Реплика длиннее 120 секунд');return;}
      this.current.push(frame);
      this.waveform.push(frame);
      let power=0;for (const value of frame) power+=value*value;
      const rms=Math.sqrt(power/frame.length),threshold=Math.max(0.014,this.noiseFloor*2.1);
      if (rms>threshold) {this.voiced=true;this.silence=0;}
      else {
        this.silence+=frame.length;
        if (!this.voiced) this.noiseFloor=this.noiseFloor*0.96+rms*0.04;
      }
      // Never cut a word at an arbitrary time boundary. Keep the full waveform,
      // including quiet speech; RMS schedules requests, server Silero decides speech.
      if (this.streaming ? this.current.reduce((n,p)=>n+p.length,0)>=14400
          : this.voiced && this.silence>=6400 && this.total-this.lastCut>=48000) this.cut();
    }
    cut() {
      if (!this.current.length) return;
      this.pending.push(...this.current);this.current=[];
      this.lastCut=this.total;this.voiced=false;
      void this.pump();
    }
    async pump() {
      if (this.running || this.cancelled || this.error) return;
      this.running=true;
      try {
        while (this.pending.length && !this.cancelled) {
          // Coalesce backlog instead of queuing dozens of tiny CPU decodes.
          const waveform=this.pending.splice(0);
          this.controller=new AbortController();
          const timer=setTimeout(()=>this.controller?.abort(),60000);
          const began=performance.now();
          let result;
          try { result=await this.transcribe(wavPCM(waveform),this.controller.signal,{streamId:this.streamId,sequence:this.sequence++}); }
          finally {clearTimeout(timer);this.controller=null;}
          if (this.cancelled) return;
          if(result.speaker_checked){
            this.speakerChecked=true;
            if(result.primary_speech)this.lastPrimaryVoiceAt=performance.now();
          }
          if(result.cumulative)this.parts=[result.raw_text ?? result.text ?? ''];
          else this.parts.push(result.raw_text ?? result.text ?? '');
          this.metrics.push({audio_seconds:waveform.reduce((n,p)=>n+p.length,0)/16000,
            request_ms:Math.round(performance.now()-began)});
          this.onPartial(this.parts.join(' ').trim());
        }
      } catch (error) {if (!this.cancelled) this.error=error;}
      finally {
        this.running=false;
        this.waiters.splice(0).forEach(resolve=>resolve());
      }
    }
    async finish() {
      if (this.cancelled) throw new Error('Запись отменена');
      if (this.error) throw this.error;
      if (this.node) {
        await new Promise((resolve,reject)=> {
          const timer=setTimeout(()=>reject(new Error('Не удалось завершить PCM-запись')),1500);
          this.flushAck=()=> {clearTimeout(timer);resolve();};
          this.node.port.postMessage('flush');
        });
        this.disconnect();
      }
      if (this.error) throw this.error;
      this.finished=true;
      // Always send the remaining audio, even below the scheduling threshold.
      // A quiet final word must not be discarded as "silence" by browser RMS.
      this.cut();
      if (this.running) await new Promise(resolve=>this.waiters.push(resolve));
      if (this.cancelled) throw new Error('Запись отменена');
      if (this.error) throw this.error;
      return this.parts;
    }
    disconnect() {
      try {this.node?.disconnect();this.gain?.disconnect();} catch {}
      if (this.node) this.node.port.onmessage=null;
      this.node=null;this.gain=null;
    }
    finalBlob() {
      if(this.cancelled)throw new Error('Запись отменена');
      return wavPCM(this.waveform);
    }
    cancel() {
      this.cancelled=true;this.controller?.abort();this.flushAck?.();
      this.disconnect();this.current=[];this.pending=[];this.waveform=[];
      this.waiters.splice(0).forEach(resolve=>resolve());
    }
  }
  const api={IncrementalSTT,wavPCM};
  root.FocusSTT=api;
  if (typeof module==='object' && module.exports) module.exports=api;
})(typeof window==='object'?window:globalThis);
