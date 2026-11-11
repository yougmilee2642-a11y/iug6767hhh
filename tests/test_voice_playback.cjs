const { test } = require('node:test');
const assert = require('node:assert/strict');
const { speechParts, speakPreparedParts } = require('../static/voice-playback.js');

test('segmentation preserves exact words, numeric values and all long-answer content', () => {
  const text = 'Здравствуйте! Консультация стоит 50.75 BYN, длительность 30 минут. '
    + 'Телефон +375290000000. Пожалуйста, подтвердите выбранное действие. '
    + 'Ничего не выполнено до вашего согласия. '.repeat(12);
  const parts = speechParts(text);
  assert.ok(parts.length > 1 && parts.length <= 8);
  assert.equal(parts.join(' ').replace(/\s+/g, ' ').trim(), text.replace(/\s+/g, ' ').trim());
  assert.ok(parts.some(part => part.includes('50.75 BYN')));
});

test('short confirmation is spoken in full as one part', () => {
  const text = 'Запрос сохранён в Callwise. Доставка владельцу не подключена.';
  assert.deepEqual(speechParts(text), [text]);
});

test('next audio is prepared while first audio plays and order remains unchanged', async () => {
  const order = [];
  let releaseFirst;
  const firstPlaying = new Promise(resolve => { releaseFirst = resolve; });
  const playback = speakPreparedParts(['one','two'], async text => {
    order.push('fetch:' + text); return text;
  }, async audio => {
    order.push('play:' + audio);
    if (audio === 'one') await firstPlaying;
  }, () => true);
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(order.includes('fetch:two'));
  assert.ok(!order.includes('play:two'));
  releaseFirst();
  await playback;
  assert.deepEqual(order.filter(value => value.startsWith('play:')), ['play:one','play:two']);
});

test('Stop prevents a prefetched reply from speaking even if its request fails', async () => {
  let current = true;
  const spoken = [];
  await speakPreparedParts(['one','two'], async part => {
    if (part === 'two') throw Error('aborted');
    return part;
  }, async part => {
    spoken.push(part); current = false;
  }, () => current);
  assert.deepEqual(spoken, ['one']);
  await new Promise(resolve => setImmediate(resolve));
});

test('speech preparation failure is exposed instead of silently dropping the remainder', async () => {
  const spoken = [];
  await assert.rejects(speakPreparedParts(['one','two'], async part => {
    if (part === 'two') throw Error('tts failed'); return part;
  }, async part => spoken.push(part), () => true), /tts failed/);
  assert.deepEqual(spoken, ['one']);
});
