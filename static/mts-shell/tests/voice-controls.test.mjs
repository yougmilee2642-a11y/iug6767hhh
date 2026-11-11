import test from 'node:test';
import assert from 'node:assert/strict';
import { controlsLocked } from '../voice-controls.mjs';
import { LocalVoiceSession } from '../local-voice.mjs';

test('consent refusal keeps all conversational controls locked', () => {
  assert.equal(controlsLocked('connecting', undefined), true);
  assert.equal(controlsLocked('error', {id:'id', privacyReady:false}), true);
  assert.equal(controlsLocked('completed', {id:'id', privacyReady:false, completed:true}), true);
  assert.equal(controlsLocked('ready', {id:'id', privacyReady:true}), false);
  assert.equal(controlsLocked('error', {id:'id', privacyReady:true}), false);
  assert.equal(controlsLocked('ready', {id:'id', privacyReady:true, closed:true}), true);
});

test('send and microphone cannot start before consent or after refusal', async (t) => {
  t.mock.method(globalThis, 'fetch', () => assert.fail('No network action permitted'));
  const session = new LocalVoiceSession({});
  session.id = 'id';
  await session.send('Вопрос');
  await session.toggleMic();
  assert.equal(session.messages.length, 0);
  session.completed = true;
  await session.send('Вопрос после отказа');
  await session.toggleMic();
  assert.equal(session.messages.length, 0);
});
