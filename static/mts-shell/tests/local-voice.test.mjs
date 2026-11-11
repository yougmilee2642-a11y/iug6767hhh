import test from "node:test";
import assert from "node:assert/strict";
import { LocalVoiceSession, shellPayload } from "../local-voice.mjs";
import { SEED_AGENTS } from "../adapter.mjs";
const reply = (data) =>
  new Response(JSON.stringify(data), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
const health = {
  local_only: true,
  ai_provider: "Ollama",
  llm_ready: true,
  local_speech: { stt_weights: true },
};
const mock = (t, handler) => {
  t.mock.method(globalThis, "fetch", handler);
};

test("shell payload excludes controls and secrets", () => {
  const payload = shellPayload({
    ...SEED_AGENTS[0],
    token: "secret",
    tools: ["unsafe"],
  });
  assert.equal(payload.token, undefined);
  assert.equal(payload.tools, undefined);
  assert.equal(payload.qa[0].id, undefined);
  assert.equal(payload.role, "Поддержка клиентов");
});
test("real request contract and finish are idempotent", async (t) => {
  const seen = [];
  mock(t, async (path, options) => {
    seen.push([path, options]);
    if (path === "/api/health") return reply(health);
    if (path === "/api/shell/conversations")
      return reply({ interaction_id: "server-id", greeting: "Здравствуйте" });
    if (path === "/api/chat")
      return reply({ text: "Ответ из модели", complete: false });
    return reply({ id: "server-id", status: "stopped" });
  });
  const messages = [];
  const session = new LocalVoiceSession(SEED_AGENTS[0], {
    message: (m) => messages.push(m),
  });
  session.sound = false;
  await session.start({voice:false});
  await session.send("Вопрос");
  await session.end();
  await session.end();
  assert.deepEqual(
    messages.map((m) => m.text),
    ["Здравствуйте", "Вопрос", "Ответ из модели"],
  );
  assert.equal(seen.filter(([path]) => path === "/api/application").length, 1);
  const chat = JSON.parse(seen.find(([path]) => path === "/api/chat")[1].body);
  assert.equal(chat.interaction_id, "server-id");
  assert.ok(chat.request_id);
  assert.ok(seen.every(([path]) => path.startsWith("/api/")));
});
test("unavailable local service never returns a static mock answer", async (t) => {
  mock(t, async () => reply({ ...health, llm_ready: false }));
  const errors = [];
  const messages = [];
  const session = new LocalVoiceSession(SEED_AGENTS[0], {
    error: (e) => errors.push(e),
    message: (m) => messages.push(m),
  });
  session.sound = false;
  await session.start({voice:false});
  assert.equal(session.state, "error");
  assert.equal(messages.length, 0);
  assert.match(errors[0], /Локальная модель недоступна/);
});
test("close during chat suppresses late response", async (t) => {
  let resolveChat;
  mock(t, async (path) => {
    if (path === "/api/health") return reply(health);
    if (path === "/api/shell/conversations")
      return reply({ interaction_id: "id", greeting: "Привет" });
    if (path === "/api/chat") return new Promise((r) => (resolveChat = r));
    return reply({ status: "stopped" });
  });
  const messages = [];
  const session = new LocalVoiceSession(SEED_AGENTS[0], {
    message: (m) => messages.push(m),
  });
  session.sound = false;
  await session.start({voice:false});
  const sending = session.send("Вопрос");
  await session.end();
  resolveChat(reply({ text: "Запоздалый ответ", complete: false }));
  await sending;
  assert.deepEqual(
    messages.map((m) => m.text),
    ["Привет", "Вопрос"],
  );
  assert.equal(session.closed, true);
});
test("close during start finalizes the late server ID", async (t) => {
  let resolveStart;
  let started;
  const ready = new Promise((r) => (started = r));
  let ends = 0;
  mock(t, async (path) => {
    if (path === "/api/health") return reply(health);
    if (path === "/api/shell/conversations") {
      started();
      return new Promise((r) => (resolveStart = r));
    }
    ends++;
    return reply({ status: "stopped" });
  });
  const messages = [];
  const session = new LocalVoiceSession(SEED_AGENTS[0], {
    message: (m) => messages.push(m),
  });
  session.sound = false;
  const starting = session.start({voice:false});
  await ready;
  await session.end();
  resolveStart(
    reply({ interaction_id: "late-id", greeting: "Старое приветствие" }),
  );
  await starting;
  assert.equal(ends, 1);
  assert.equal(messages.length, 0);
});
test("closing frees audio and media resources", async (t) => {
  mock(t, async () => reply({ status: "stopped" }));
  let stopped = 0,
    closed = 0,
    paused = 0,
    settled = 0;
  const session = new LocalVoiceSession(SEED_AGENTS[0]);
  session.id = "id";
  session.media = { getTracks: () => [{ stop: () => stopped++ }] };
  session.audioContext = { close: async () => closed++ };
  session.audio = { pause: () => paused++, removeAttribute() {}, load() {} };
  session.settleAudio = () => settled++;
  await session.end();
  assert.equal(stopped, 1);
  assert.equal(closed, 1);
  assert.equal(paused, 1);
  assert.equal(settled, 1);
  assert.equal(session.media, null);
});

function mockCapture(t) {
  const replacements={
    AudioContext:class {
      async resume() {} async close() {}
      createMediaStreamSource(){return {connect(){},disconnect(){}};}
      createAnalyser(){return {fftSize:2048,getByteTimeDomainData(){}};}
    },
    MediaRecorder:class {
      static isTypeSupported(){return true;}
      state='inactive';
      start(){this.state='recording';}
      stop(){this.state='inactive';this.ondataavailable?.({data:new Blob(['saved whole audio'])});return this.onstop?.();}
    },
    requestAnimationFrame:()=>1,cancelAnimationFrame:()=>{},
  };
  for (const [key,value] of Object.entries(replacements)) {
    const original=globalThis[key];globalThis[key]=value;
    t.after(()=>{if(original===undefined)delete globalThis[key];else globalThis[key]=original;});
  }
  t.mock.method(globalThis.CallwiseSTT.IncrementalSTT.prototype,'attach',async()=>{});
}

test('partial recognition never reaches chat; full-waveform final correction becomes one turn',async(t)=> {
  mockCapture(t);const paths=[],partialMessages=[];
  mock(t,async(path,options)=> {
    paths.push(path);
    if(path==='/api/health')return reply(health);
    if(path==='/api/shell/conversations')return reply({interaction_id:'id',greeting:'Здравствуйте'});
    if(path==='/api/transcribe') {
      if(options.body.get('mode')==='preview')return reply({raw_text:'Где',text:'Где',cumulative:true});
      assert.equal(options.body.get('mode'),'final');
      assert.equal(options.body.get('file').name,'utterance.wav');
      assert.equal(options.body.get('file').size,44+1600*2);
      return reply({text:'Где баланс?'});
    }
    if(path==='/api/transcribe/assemble')assert.fail('Final speech must be decoded from audio');
    if(path==='/api/chat')return reply({text:'В приложении',complete:false});
    return reply({status:'stopped'});
  });
  const session=new LocalVoiceSession(SEED_AGENTS[0],{message:m=>partialMessages.push(m)});
  session.sound=false;await session.start({voice:false});
  session.media={getTracks:()=>[{stop(){}}]};session.autoListen=true;await session.listen();
  session.incremental.push(new Float32Array(1600).fill(.1));session.incremental.cut();
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(paths.includes('/api/chat'),false);assert.equal(partialMessages.length,1);
  session.autoListen=false;await session.recorder.stop();
  assert.equal(paths.filter(path=>path==='/api/chat').length,1);
  assert.deepEqual(partialMessages.map(m=>m.text),['Здравствуйте','Где баланс?','В приложении']);
  await session.end();
});

test('failed chunk falls back to the preserved whole recording, not an incomplete transcript',async(t)=> {
  mockCapture(t);const uploads=[];
  mock(t,async(path,options)=> {
    if(path==='/api/health')return reply(health);
    if(path==='/api/shell/conversations')return reply({interaction_id:'id',greeting:'Здравствуйте'});
    if(path==='/api/transcribe') {
      const filename=options.body.get('file').name;uploads.push(filename);
      if(filename==='chunk.wav')return new Response(JSON.stringify({detail:'failed chunk'}),{status:422});
      return reply({text:'Целая реплика'});
    }
    if(path==='/api/transcribe/assemble')assert.fail('Failed partial transcript must not be assembled');
    if(path==='/api/chat') {
      assert.equal(JSON.parse(options.body).text,'Целая реплика');
      return reply({text:'Ответ',complete:false});
    }
    return reply({status:'stopped'});
  });
  const session=new LocalVoiceSession(SEED_AGENTS[0]);session.sound=false;await session.start({voice:false});
  session.media={getTracks:()=>[{stop(){}}]};session.autoListen=true;await session.listen();
  session.incremental.push(new Float32Array(1600).fill(.1));session.incremental.cut();
  await new Promise(resolve=>setImmediate(resolve));session.autoListen=false;
  await session.recorder.stop();assert.deepEqual(uploads,['chunk.wav','voice.webm']);await session.end();
});
