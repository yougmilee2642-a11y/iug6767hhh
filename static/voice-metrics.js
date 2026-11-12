// Browser-side voice latency log (P1-03). Stages are recorded and summarised separately and
// are never added up into a "full conversation time". Cancelled and failed attempts are kept
// as unsuccessful attempts and never enter p50/p95.
(function (root) {
  const STAGES = ['endpointing', 'stt', 'llm', 'tts_first_audio', 'playback_start'];

  function percentile(values, q) {
    if (!values.length) return null;
    const ordered = [...values].sort((a, b) => a - b);
    return ordered[Math.max(0, Math.ceil(q / 100 * ordered.length) - 1)];
  }

  // attempt: {stage, ms, ok, outcome, temperature, audio_seconds}
  function summarize(attempts) {
    const groups = new Map();
    for (const item of attempts) {
      const key = `${item.stage}|${item.temperature}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(item);
    }
    return [...groups.entries()].map(([key, items]) => {
      const [stage, temperature] = key.split('|');
      const good = items.filter((i) => i.ok && Number.isFinite(i.ms)).map((i) => i.ms);
      return {
        stage, temperature, attempts: items.length, successes: good.length,
        failures: items.length - good.length,
        cancelled: items.filter((i) => i.outcome === 'cancelled').length,
        p50_ms: percentile(good, 50), p95_ms: percentile(good, 95),
        minimum_sample_size_met: good.length >= 20,
      };
    }).sort((a, b) => STAGES.indexOf(a.stage) - STAGES.indexOf(b.stage) || a.temperature.localeCompare(b.temperature));
  }

  function create(now = () => Date.now()) {
    const attempts = [];
    const seen = new Set(); // first attempt only describes page-local order; model cache is not measured
    return {
      attempts,
      record(stage, ms, outcome = 'ok', extra = {}) {
        const temperature = seen.has(stage) ? 'repeat_attempt' : 'first_attempt';
        seen.add(stage);
        if(attempts.length>=500)attempts.shift();
        attempts.push({
          stage, ms: Number.isFinite(ms) ? Math.round(ms) : null, ok: outcome === 'ok',
          outcome, temperature, at: now(), ...extra,
        });
      },
      summary: () => summarize(attempts),
      reset() { attempts.length = 0; seen.clear(); },
    };
  }

  const api = { create, summarize, percentile, STAGES };
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.FocusVoiceMetrics = api;
})(typeof self !== 'undefined' ? self : this);
