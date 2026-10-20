import test from 'node:test';
import assert from 'node:assert/strict';
import { boundedResponse, LocalResponseWaitError } from '../src/responseDeadline.ts';
import { submissionForIntent } from '../src/responseIdentity.ts';

test('a completed response is retained and later local cancel has no effect', async () => {
  let signal;
  const wait = boundedResponse(active => { signal = active; return Promise.resolve('saved'); }, 50);
  assert.equal(await wait.promise, 'saved');
  wait.cancel();
  assert.equal(signal.aborted, false);
  assert.equal(await wait.promise, 'saved');
});

test('an unresponsive transport times out locally even if it ignores AbortSignal', async () => {
  let signal;
  const wait = boundedResponse(active => { signal = active; return new Promise(() => {}); }, 5);
  await assert.rejects(wait.promise, error => error instanceof LocalResponseWaitError && error.code === 'timeout'
    && error.message.includes('server may still complete'));
  assert.equal(signal.aborted, true);
});

test('scope cleanup or forced refresh cancels only the local wait and ignores late success', async () => {
  let signal, finish;
  const wait = boundedResponse(active => { signal = active; return new Promise(resolve => { finish = resolve; }); }, 100);
  wait.cancel();
  await assert.rejects(wait.promise, error => error.code === 'canceled' && error.message.includes('unverified'));
  assert.equal(signal.aborted, true);
  finish('late prior item');
  await assert.rejects(wait.promise, error => error.code === 'canceled');
});

test('an unconfirmed mutation timeout leaves its idempotency intent reusable', async () => {
  const pending = submissionForIntent(null, 'exact-item-and-patch', () => 'original-key');
  const wait = boundedResponse(() => new Promise(() => {}), 5);
  await assert.rejects(wait.promise, error => error.code === 'timeout');
  assert.equal(submissionForIntent(pending, pending.intent, () => 'incorrect-new-key').key, 'original-key');
});

test('ordinary failure and invalid deadlines do not become fabricated responses', async () => {
  const error = new Error('read failed');
  await assert.rejects(boundedResponse(() => Promise.reject(error), 50).promise, error);
  await assert.rejects(boundedResponse(() => { throw error; }, 50).promise, error);
  for (const deadline of [0, -1, NaN, Infinity])
    assert.throws(() => boundedResponse(() => Promise.resolve('never'), deadline), RangeError);
});
