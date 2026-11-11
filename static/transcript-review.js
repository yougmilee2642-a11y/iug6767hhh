// Review of a recognised phrase before it reaches the Runtime.
// The text is only a proposal until the customer-side tester confirms or edits it;
// the confirmed (possibly corrected) text becomes the authoritative user turn.
(function (root) {
  function createReview() {
    let pending = null;
    return {
      get active() { return pending !== null; },
      // Resolves with {text, edited} on confirmation, or null if discarded/cancelled.
      request(recognised) {
        if (pending) pending.resolve(null);
        return new Promise((resolve) => { pending = { resolve, recognised: String(recognised) }; });
      },
      confirm(text) {
        if (!pending) return false;
        const value = String(text ?? '').trim();
        if (!value) return false; // empty text is never sent
        const { resolve, recognised } = pending;
        pending = null;
        resolve({ text: value, edited: value !== recognised.trim() });
        return true;
      },
      discard() {
        if (!pending) return false;
        const { resolve } = pending;
        pending = null;
        resolve(null);
        return true;
      },
    };
  }
  const api = { createReview };
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.CallwiseTranscriptReview = api;
})(typeof self !== 'undefined' ? self : this);
