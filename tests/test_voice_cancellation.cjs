const { test } = require('node:test');
const assert = require('node:assert/strict');
const { IncrementalSTT } = require('../static/incremental-stt.js');
const { speakPreparedParts } = require('../static/voice-playback.js');
const { createReview } = require('../static/transcript-review.js');
const tick = () => new Promise((resolve) => setImmediate(resolve));
const frame = (value) => new Float32Array(1600).fill(value);

function speakThenPause(stt) {
  for (let i = 0; i < 10; i++) stt.push(frame(0.1));
  for (let i = 0; i < 4; i++) stt.push(frame(0));
}

test('cancel during STT aborts the in-flight request and finish() refuses to return text', async () => {
  let aborted = false;
  const stt = new IncrementalSTT({ transcribe: (blob, signal) => new Promise((_, reject) => {
    signal.addEventListener('abort', () => { aborted = true; reject(Object.assign(new Error('aborted'), { name: 'AbortError' })); });
  }) });
  speakThenPause(stt);
  await tick();
  stt.cancel();
  await tick();
  assert.equal(aborted, true);
  await assert.rejects(() => stt.finish(), /отменена/);
});

test('a failed fragment is an error, never a shorter "complete" phrase', async () => {
  let call = 0;
  const stt = new IncrementalSTT({ transcribe: async () => {
    call += 1;
    if (call === 2) throw new Error('STT упал');
    return { raw_text: 'часть' + call };
  } });
  speakThenPause(stt);
  await tick();
  for (let i = 0; i < 10; i++) stt.push(frame(0.1));
  await assert.rejects(() => stt.finish(), /STT упал/);
});

test('partial text is only a UI hint and does not appear as a finished phrase', async () => {
  const partials = [];
  const stt = new IncrementalSTT({ transcribe: async () => ({ raw_text: 'меня зовут' }), onPartial: (t) => partials.push(t) });
  speakThenPause(stt);
  await tick();
  assert.deepEqual(partials, ['меня зовут']);
  stt.cancel(); // nothing was confirmed or sent anywhere
});

test('cancelling TTS playback between parts prevents fetching and playing the rest', async () => {
  let current = true; const fetched = []; const played = [];
  await speakPreparedParts(['a', 'b', 'c'], async (p) => { fetched.push(p); return p; },
    async (audio) => { played.push(audio); current = false; /* Stop pressed during first audio */ }, () => current);
  assert.deepEqual(played, ['a']);
  assert.ok(fetched.length <= 2); // at most the single lookahead part, never the third
});

test('TTS failure surfaces as an error so the call can continue in text', async () => {
  await assert.rejects(() => speakPreparedParts(['a'], async () => { throw new Error('Русская озвучка недоступна'); },
    async () => {}, () => true), /озвучка недоступна/);
});

test('Stop/finish discards a pending transcript review so it can never be sent later', async () => {
  const review = createReview();
  const pending = review.request('мой номер плюс три семь пять');
  review.discard(); // what finish() and stopRecording(true) do
  assert.equal(await pending, null);
  assert.equal(review.confirm('мой номер'), false);
});

test('review keeps names, phone digits, amounts and negation exactly as the user corrected them', async () => {
  const review = createReview();
  const pending = review.request('Анна не хочет скидку 15 рублей, номер 37529');
  review.confirm('Анна не хочет скидку 50 рублей, номер +375291112233');
  const { text, edited } = await pending;
  assert.equal(edited, true);
  assert.match(text, /не хочет/); assert.match(text, /50 рублей/); assert.match(text, /\+375291112233/);
});
