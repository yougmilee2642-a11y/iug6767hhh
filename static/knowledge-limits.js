// Knowledge limits shared by the quick wizard UI. Mirrors services/track1_service.py;
// the server stays authoritative, this only explains limits before a request is sent.
(function (root) {
  const LIMITS = Object.freeze({ faqCount: 10, question: 240, answer: 1200, source: 200, facts: 3000, total: 6500 });

  const count=(value)=>Array.from(String(value||'').trim()).length;
  function usage(data) {
    const qa = data.qa || [];
    const faq = qa.reduce((sum, q) => sum + count(q.question) + count(q.answer) + count(q.source), 0);
    const facts = count(data.facts);
    return { facts, faq, total: facts + faq, remaining: LIMITS.total - facts - faq };
  }

  const norm = (s) => String(s || '').normalize('NFKC').toLowerCase().replace(/ё/g,'е').replace(/ß/g,'ss').replace(/\s+/g, ' ').trim();

  // Returns [{field, index, message}]. field: 'facts' | 'total' | 'faq-count' | 'question' | 'answer' | 'source'.
  function problems(data) {
    const out = [], qa = data.qa || [], used = usage(data);
    if (count(data.facts) > LIMITS.facts)
      out.push({ field: 'facts', index: null, message: `Факты: ${used.facts} из ${LIMITS.facts} символов. Сократите на ${used.facts - LIMITS.facts}.` });
    if (qa.length > LIMITS.faqCount)
      out.push({ field: 'faq-count', index: null, message: `Вопросов ${qa.length}, допускается ${LIMITS.faqCount}.` });
    const seen = new Map();
    qa.forEach((q, index) => {
      for (const [key, label] of [['question', 'Вопрос'], ['answer', 'Ответ'], ['source', 'Источник']]) {
        const length = count(q[key]);
        if (length > LIMITS[key])
          out.push({ field: key, index, message: `${label} ${index + 1}: ${length} из ${LIMITS[key]} символов. Сократите на ${length - LIMITS[key]}.` });
      }
      const question = norm(q.question);
      if (question && seen.has(question))
        out.push({ field: 'question', index, message: `Вопрос ${index + 1} повторяет вопрос ${seen.get(question) + 1}. Вопросы должны быть уникальными.` });
      else if (question) seen.set(question, index);
    });
    if (used.total > LIMITS.total)
      out.push({ field: 'total', index: null, message: `Знания занимают ${used.total} из ${LIMITS.total} символов. Сократите на ${used.total - LIMITS.total}; данные не обрезаются автоматически.` });
    return out;
  }

  function counterText(data) {
    const u = usage(data);
    return `Объём знаний: ${u.total} из ${LIMITS.total} символов (факты ${u.facts}, FAQ ${u.faq}). ` +
      (u.remaining >= 0 ? `Осталось ${u.remaining}.` : `Превышение на ${-u.remaining}.`);
  }

  const api = { LIMITS, usage, problems, counterText };
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.CallwiseKnowledgeLimits = api;
})(typeof self !== 'undefined' ? self : this);
