import test from 'node:test';
import assert from 'node:assert/strict';
import { accountResponse } from '../src/accountResponse.ts';

test('a valid slow authentication response is accepted after the ordinary read deadline', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  let calls = 0;
  const task = accountResponse(() => { calls++; return new Promise(resolve => setTimeout(() => resolve({ role: 'member' }), 16_000)); });
  t.mock.timers.tick(16_000);
  assert.deepEqual(await task.promise, { role: 'member' });
  assert.equal(calls, 1);
});

test('a stalled authentication stops waiting without resending or accepting its late answer', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  let calls = 0, signal, finish;
  const task = accountResponse(s => { calls++; signal = s; return new Promise(resolve => { finish = resolve; }); });
  const rejected = assert.rejects(task.promise, error => error.code === 'timeout' && error.message.includes('server may still complete'));
  t.mock.timers.tick(30_000);
  await rejected;
  assert.equal(signal.aborted, true);
  finish({ role: 'admin' });
  await Promise.resolve();
  assert.equal(calls, 1);
  await assert.rejects(task.promise, error => error.code === 'timeout');
});

test('leaving authentication cancels only the local wait', async () => {
  let signal;
  const task = accountResponse(s => { signal = s; return new Promise(() => {}); });
  task.cancel();
  await assert.rejects(task.promise, error => error.code === 'canceled' && error.message.includes('unverified'));
  assert.equal(signal.aborted, true);
});
