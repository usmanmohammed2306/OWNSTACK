import test from 'node:test';
import assert from 'node:assert/strict';
import { repairCandidateToReview, repairStartBlock, sameRepairScope, sameRepairReview, savedRepairRowsMatch, repairProgressText } from '../src/repairView.ts';
import { submissionForIntent } from '../src/responseIdentity.ts';

const session = { user_id: 'atlas-engineer', tenant_id: 'atlas', role: 'engineer', csrf_token: 'synthetic-session' };
const scope = { session, itemId: 'item-a' };
const review = { ...scope, runId: 'run-a', attemptId: 'attempt-a', patchHash: 'hash-a' };
const attempt = { id: 'attempt-a', number: 1, state: 'passed', candidate_hash: 'hash-a', checks: { passed: true },
  candidate: { edits: [{ path: 'sample_app/report.py', old: 'old', new: 'new' }] } };
const run = { id: 'run-a', item_id: 'item-a', state: 'awaiting_review', attempts: [attempt] };
const enabled = { role: 'engineer', mode: 'fixture', remainingCalls: null, itemStatus: 'checks_failed', patchHash: 'hash-a', humanDecision: null, runs: [] };

test('saved repairs cannot display for another item, tenant, user, role or login', () => {
  assert.equal(sameRepairScope(scope, { ...scope, session: { ...session } }), true);
  for (const changed of [null, { ...scope, itemId: 'item-b' },
    ...['user_id', 'tenant_id', 'role', 'csrf_token'].map(key => ({ ...scope, session: { ...session, [key]: 'other' } }))])
    assert.equal(sameRepairScope(scope, changed), false);
  assert.equal(sameRepairScope(null, null), false);
});

test('candidate acknowledgement binds to session, item, run, attempt and exact hash', () => {
  assert.equal(sameRepairReview(review, { ...review }), true);
  for (const key of ['itemId', 'runId', 'attemptId', 'patchHash'])
    assert.equal(sameRepairReview(review, { ...review, [key]: 'changed' }), false);
  assert.equal(sameRepairReview(review, { ...review, session: { ...session, csrf_token: 'new-login' } }), false);
  assert.equal(sameRepairReview(null, review), false);
});

test('AI-off, unknown live allowance and active saved work block new repair', () => {
  assert.equal(repairStartBlock(enabled), null);
  assert.equal(repairStartBlock({ ...enabled, mode: 'nebius', remainingCalls: 1 }), null);
  for (const changes of [{ mode: 'off' }, { mode: 'unknown' }, { role: 'admin' },
    { mode: 'nebius', remainingCalls: 0 }, { mode: 'nebius', remainingCalls: null },
    { mode: 'nebius', remainingCalls: undefined }, { itemStatus: 'checks_passed' },
    { patchHash: null }, { humanDecision: 'take_over' }, { runs: [run] },
    { runs: [{ ...run, state: 'running' }] }]) assert.ok(repairStartBlock({ ...enabled, ...changes }));
});

test('only the latest exact passing candidate awaiting review can be offered for adoption', () => {
  assert.equal(repairCandidateToReview(run), attempt);
  for (const state of ['running', 'adopted', 'manual_handoff', 'taken_over'])
    assert.equal(repairCandidateToReview({ ...run, state }), null);
  for (const changed of [{ ...attempt, state: 'failed' }, { ...attempt, candidate_hash: null },
    { ...attempt, checks: { passed: false } }, { ...attempt, candidate: null },
    { ...attempt, candidate: { edits: [] } },
    { ...attempt, candidate: { edits: [{ path: 'other.py', old: 'old', new: 'new' }] } }])
    assert.equal(repairCandidateToReview({ ...run, attempts: [changed] }), null);
  assert.equal(repairCandidateToReview({ ...run, attempts: [attempt, { ...attempt, id: 'attempt-b', state: 'failed' }] }), null);
  assert.equal(repairCandidateToReview({ ...run, attempts: [] }), null);
});

test('repair response collections reject foreign work items and duplicate runs', () => {
  assert.equal(savedRepairRowsMatch([run], 'item-a'), true);
  assert.equal(savedRepairRowsMatch([], 'item-a'), true);
  assert.equal(savedRepairRowsMatch([run], 'item-b'), false);
  assert.equal(savedRepairRowsMatch([run, run], 'item-a'), false);
});

test('an unconfirmed repair start retains its key for the same exact submitted intent', () => {
  let calls = 0;
  const create = () => `synthetic-key-${++calls}`;
  const original = submissionForIntent(null, JSON.stringify({ itemId: 'item-a', patch_hash: 'hash-a', max_attempts: 2 }), create);
  const repeat = submissionForIntent(original, original.intent, create);
  assert.equal(repeat.key, original.key);
  const changed = submissionForIntent(original, JSON.stringify({ itemId: 'item-a', patch_hash: 'hash-b', max_attempts: 2 }), create);
  assert.notEqual(changed.key, original.key);
  assert.equal(calls, 2);
});

test('live progress text names the persisted run and attempt state without inventing completion', () => {
  assert.match(repairProgressText([]), /No saved repair/);
  for (const state of ['queued', 'generating', 'candidate_ready', 'verifying', 'failed']) {
    const text = repairProgressText([{ ...run, state: 'running', attempts: [{ ...attempt, state }] }]);
    assert.ok(text.includes(`Attempt 1: ${state.replaceAll('_', ' ')}`));
    assert.ok(text.includes('Refresh does not call AI'));
  }
  assert.match(repairProgressText([run]), /awaiting review\. Attempt 1: passed/);
});
