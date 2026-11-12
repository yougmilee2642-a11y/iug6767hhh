// AudioWorklet keeps capture off the UI thread. Every message is independent PCM,
// not a WebM fragment that may be missing its container header.
class FocusPCM extends AudioWorkletProcessor {
  constructor() {
    super();
    this.samples=[];
    this.offset=0;
    this.packet=new Float32Array(1600);
    this.used=0;
    this.stopped=false;
    this.port.onmessage=({data}) => {
      if (data === 'flush') {
        this.stopped=true;
        if (this.used) this.port.postMessage(this.packet.slice(0,this.used));
        this.port.postMessage('flushed');
      }
    };
  }
  process(inputs) {
    if (this.stopped) return false;
    const channels=inputs[0];
    if (!channels?.length) return true;
    const mono=channels[0];
    for (let i=0;i<mono.length;i++) {
      let value=0;
      for (const channel of channels) value+=channel[i] || 0;
      this.samples.push(value/channels.length);
    }
    const step=sampleRate/16000;
    while (this.offset+step<=this.samples.length) {
      // Area-average resampling supports both 44.1/48 kHz and a native 16 kHz context.
      const end=this.offset+step;
      let sum=0;
      for (let i=Math.floor(this.offset);i<Math.ceil(end);i++) {
        sum+=this.samples[i]*(Math.min(end,i+1)-Math.max(this.offset,i));
      }
      this.packet[this.used++]=sum/step;
      this.offset=end;
      if (this.used===this.packet.length) {
        this.port.postMessage(this.packet);
        this.packet=new Float32Array(1600);
        this.used=0;
      }
    }
    const consumed=Math.floor(this.offset);
    this.samples.splice(0,consumed);
    this.offset-=consumed;
    return true;
  }
}
registerProcessor('focus-pcm',FocusPCM);
