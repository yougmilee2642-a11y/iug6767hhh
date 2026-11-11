const { test } = require('node:test');
const assert = require('node:assert/strict');
const { LIMITS, usage, problems, counterText } = require('../static/knowledge-limits.js');

const faq = (n, q = 'в', a = 'о', s = '') => Array.from({ length: n }, (_, i) => ({ question: q + i, answer: a, source: s }));

test('usage counts facts and every FAQ part exactly like the server', () => {
  const u = usage({ facts: 'abc', qa: [{ question: 'qq', answer: 'aaa', source: 's' }] });
  assert.deepEqual(u, { facts: 3, faq: 6, total: 9, remaining: LIMITS.total - 9 });
});

test('within limits produces no problems', () => {
  assert.deepEqual(problems({ facts: 'x'.repeat(3000), qa: faq(10, 'вопрос ', 'a'.repeat(100)) }), []);
});

test('each field reports its own limit with exact overflow and nothing is truncated', () => {
  const data = { facts: 'x'.repeat(3001), qa: [{ question: 'q'.repeat(241), answer: 'a'.repeat(1201), source: 's'.repeat(201) }] };
  const p = problems(data);
  assert.deepEqual(p.map(x => x.field).sort(), ['answer', 'facts', 'question', 'source']);
  assert.match(p.find(x => x.field === 'facts').message, /3001 из 3000.*на 1\./);
  assert.equal(data.facts.length, 3001); // input untouched
});

test('total limit is reported separately from per-field limits', () => {
  const data = { facts: 'x'.repeat(3000), qa: faq(4, 'q', 'a'.repeat(1000)) };
  const p = problems(data);
  assert.equal(p.length, 1);
  assert.equal(p[0].field, 'total');
  assert.match(p[0].message, /не обрезаются автоматически/);
});

test('more than 10 FAQ and duplicate questions are explained near the right item', () => {
  assert.equal(problems({ facts: '', qa: faq(11) }).some(x => x.field === 'faq-count'), true);
  const dup = problems({ facts: '', qa: [{ question: ' Цена ?', answer: 'a' }, { question: 'цена  ?', answer: 'b' }] });
  assert.equal(dup.length, 1);
  assert.equal(dup[0].index, 1);
  assert.match(dup[0].message, /повторяет вопрос 1/);
});

test('counter text shows remaining and overflow', () => {
  assert.match(counterText({ facts: 'abc', qa: [] }), /3 из 6500.*Осталось 6497/);
  assert.match(counterText({ facts: 'x'.repeat(3000), qa: faq(4, 'q', 'a'.repeat(1000)) }), /Превышение на/);
});


test('Unicode code points and whitespace match server counting',()=>{
  assert.equal(usage({facts:'  😀😀  ',qa:[{question:' ё ',answer:' да '}]}).total,5);
  assert.ok(problems({qa:[{question:'ЁЛКА',answer:'a'},{question:'елка',answer:'b'}]}).some(p=>p.field==='question'));
});
