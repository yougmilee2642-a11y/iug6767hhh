const { test } = require('node:test');
const assert = require('node:assert/strict');
const { create, summarize, percentile } = require('../static/voice-metrics.js');

test('first and repeated attempts do not imply model cache state', () => {
  const m = create(() => 0);
  m.record('stt', 900); m.record('stt', 400); m.record('llm', 1500);
  assert.deepEqual(m.attempts.map((a) => [a.stage, a.temperature]), [['stt', 'first_attempt'], ['stt', 'repeat_attempt'], ['llm', 'first_attempt']]);
});

test('cancelled and failed attempts are unsuccessful and never enter p50/p95', () => {
  const m = create(() => 0);
  for (const ms of [100, 200, 300]) m.record('llm', ms);
  m.record('llm', 5, 'cancelled'); m.record('llm', 7, 'failed');
  const warm = m.summary().find((r) => r.stage === 'llm' && r.temperature === 'repeat_attempt');
  assert.equal(warm.attempts, 4); assert.equal(warm.successes, 2); assert.equal(warm.failures, 2); assert.equal(warm.cancelled, 1);
  assert.equal(warm.p50_ms, 200); // 200 and 300 successful warm values, nearest-rank p50 = 200
  assert.equal(warm.minimum_sample_size_met, false);
});

test('minimum sample size is met only from 20 successful attempts; stages are never summed', () => {
  const rows = summarize(Array.from({ length: 20 }, (_, i) => ({ stage: 'stt', temperature: 'repeat_attempt', ok: true, ms: i + 1 })));
  assert.equal(rows.length, 1);
  assert.equal(rows[0].p95_ms, 19); assert.equal(rows[0].minimum_sample_size_met, true);
  assert.equal(rows.some((r) => r.stage === 'total' || r.stage === 'conversation'), false);
  assert.equal(percentile([], 50), null);
});

test('endpointing and playback start are separate stages from STT/LLM/TTS', () => {
  const m = create(() => 0);
  ['endpointing', 'stt', 'llm', 'tts_first_audio', 'playback_start'].forEach((s) => m.record(s, 10));
  assert.deepEqual(m.summary().map((r) => r.stage), ['endpointing', 'stt', 'llm', 'tts_first_audio', 'playback_start']);
});
