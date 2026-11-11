const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createReview } = require('../static/transcript-review.js');

test('unchanged confirmation sends the recognised text and is not marked edited', async () => {
  const review = createReview();
  const result = review.request('Меня зовут Анна');
  assert.equal(review.active, true);
  assert.equal(review.confirm('Меня зовут Анна'), true);
  assert.deepEqual(await result, { text: 'Меня зовут Анна', edited: false });
  assert.equal(review.active, false);
});

test('corrected phone number and negation become the authoritative text', async () => {
  const review = createReview();
  const result = review.request('Мой номер плюс триста семьдесят пять двадцать девять и я хочу доставку');
  review.confirm('  Мой номер +375291112233 и я не хочу доставку ');
  const value = await result;
  assert.equal(value.edited, true);
  assert.equal(value.text, 'Мой номер +375291112233 и я не хочу доставку');
});

test('empty correction is never sent; discard and cancel resolve to null', async () => {
  const review = createReview();
  const first = review.request('текст');
  assert.equal(review.confirm('   '), false);
  assert.equal(review.active, true);
  assert.equal(review.discard(), true);
  assert.equal(await first, null);
  assert.equal(review.discard(), false);
});

test('a new request cancels a stale pending one instead of sending it', async () => {
  const review = createReview();
  const stale = review.request('старая фраза');
  const fresh = review.request('новая фраза');
  assert.equal(await stale, null);
  review.confirm('новая фраза');
  assert.equal((await fresh).text, 'новая фраза');
});
