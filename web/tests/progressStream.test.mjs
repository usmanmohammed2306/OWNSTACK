import test from 'node:test';
import assert from 'node:assert/strict';
import { openProgress, validateProgress } from '../src/progressStream.ts';

const scope = { tenant_id: 'atlas', request_id: 'req-1', project_id: 'atlas-project', attempt_id: 'attempt-1', revision: 1 };
function snapshot(extra = {}) {
  return { ...scope, sequence: 1, state: 'running', deadline_elapsed: false, phase: 'receiving',
    received_bytes: 14, deltas: 2, source: 'fixture_stream', terminal: false, response: null, ...extra };
}
const frame = (type, data) => `event: ${type}\ndata: ${JSON.stringify(data)}\n\n`;
function response(raw, fragment = false) {
  const bytes = new TextEncoder().encode(raw);
  return new Response(new ReadableStream({ start(controller) {
    if (fragment) for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
    else controller.enqueue(bytes);
    controller.close();
  } }), { headers: { 'content-type': 'text/event-stream; charset=utf-8' } });
}

test('fragmented feed displays only matching snapshots and a validated saved response', async () => {
  const seen = [];
  const raw = frame('snapshot', snapshot()) + frame('snapshot', snapshot({ sequence: 2, state: 'accepted',
    phase: 'validated', terminal: true, response: { proposal_id: 'p-1', route: 'configure' } })) + frame('end', { code: 'complete' });
  const wait = openProgress(async () => response(raw, true), scope, value => seen.push(value));
  assert.equal(await wait.promise, 'complete');
  assert.equal(seen.length, 2);
  assert.equal(seen[1].response.route, 'configure');
});

test('tenant, project, attempt and revision changes are rejected before display', async () => {
  for (const change of [{ tenant_id: 'nova' }, { project_id: 'nova-project' }, { request_id: 'other' },
    { attempt_id: 'old-attempt' }, { revision: 2 }]) {
    const seen = [];
    const wait = openProgress(async () => response(frame('snapshot', snapshot(change))), scope, v => seen.push(v));
    await assert.rejects(wait.promise, /scope/);
    assert.equal(seen.length, 0);
  }
});

test('malformed shapes, extra fields, unsafe counters and premature responses fail closed', () => {
  for (const change of [{ secret: 'do-not-display' }, { sequence: 0 }, { sequence: '1' }, { received_bytes: -1 },
    { deltas: 513 }, { terminal: true }, { source: 'live-certified' }, { source: 'saved_status' },
    { response: { proposal_id: 'p', route: 'configure' } },
    { state: 'accepted', terminal: true, response: { proposal_id: 'p', route: 'configure', shell: 'bad' } }]) {
    assert.throws(() => validateProgress(snapshot(change), scope, null));
  }
  assert.throws(() => validateProgress(snapshot(), scope, snapshot()), /scope/);
  assert.throws(() => validateProgress(snapshot({ sequence: 2, received_bytes: 1 }), scope, snapshot()), /scope/);
});

test('truncated JSON, absent end, premature completion, unknown events and byte limits reject', async () => {
  for (const raw of ['event: snapshot\ndata: {\n\n', frame('snapshot', snapshot()), frame('end', { code: 'complete' }),
    frame('tool', { shell: 'bad' }), 'x'.repeat(5000), 'x'.repeat(66000)]) {
    await assert.rejects(openProgress(async () => response(raw), scope, () => {}).promise);
  }
});

test('scope/session invalidation ends watching without pretending work was canceled', async () => {
  for (const code of ['scope_changed', 'session_changed', 'wait_limit', 'unavailable']) {
    assert.equal(await openProgress(async () => response(frame('end', { code })), scope, () => {}).promise, code);
  }
});

test('local cancellation ignores a late transport response and never displays it', async () => {
  let finish;
  const seen = [];
  const wait = openProgress(() => new Promise(resolve => { finish = resolve; }), scope, v => seen.push(v));
  wait.cancel();
  await assert.rejects(wait.promise, /locally/);
  finish(response(frame('snapshot', snapshot())));
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(seen, []);
});

test('a reader ignoring AbortSignal cannot freeze the visible wait', async () => {
  const seen = [];
  const stalled = new Response(new ReadableStream({ pull() { return new Promise(() => {}); } }),
    { headers: { 'content-type': 'text/event-stream' } });
  const wait = openProgress(async () => stalled, scope, v => seen.push(v), 15);
  await assert.rejects(wait.promise, /timed out locally/);
  assert.deepEqual(seen, []);
});
