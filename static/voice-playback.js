// Play already-approved text earlier; never stream unvalidated model/tool output.
(function (root) {
  function speechParts(text) {
    if (typeof Intl.Segmenter !== 'function' || text.length <= 100) return [text];
    const parts = [];
    const segmenter = new Intl.Segmenter('ru', { granularity: 'sentence' });
    let pending = '';
    for (const item of segmenter.segment(text)) {
      pending += item.segment;
      if (pending.trim().length >= 24) {
        parts.push(pending.trim());
        pending = '';
      }
    }
    if (pending.trim()) {
      if (parts.length) parts[parts.length - 1] += ' ' + pending.trim();
      else parts.push(pending.trim());
    }
    // Bound per-answer requests without truncating the remaining text.
    return parts.length > 8 ? [...parts.slice(0, 7), parts.slice(7).join(' ')] : parts;
  }

  async function speakPreparedParts(parts, fetchPart, playPart, isCurrent) {
    // Capture lookahead errors immediately, even while the previous audio plays.
    const prepare = (part) => Promise.resolve().then(() => fetchPart(part)).then(
      value => ({ value }), error => ({ error }));
    let prepared = prepare(parts[0]);
    for (let index = 0; index < parts.length; index += 1) {
      const item = await prepared;
      if (!isCurrent()) return;
      if (item.error) throw item.error;
      const next = index + 1 < parts.length ? prepare(parts[index + 1]) : null;
      await playPart(item.value);
      if (!isCurrent()) return;
      prepared = next;
    }
  }

  const api = { speechParts, speakPreparedParts };
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.FocusVoice = api;
})(typeof window === 'object' ? window : globalThis);
