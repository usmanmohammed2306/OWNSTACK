import test from 'node:test';
import assert from 'node:assert/strict';
import { filterRequests, effectiveVariationState, attributedReads, lineDiff, currentPatchCheck, repositoryCheckLabel } from '../src/review.ts';

test('search matches all words, status and IDs without changing selection or input', () => {
  const rows = [{ id: 'req-123', text: 'Atlas read access', status: 'new', kind: 'access' }, { id: 'req-456', text: 'PDF export', status: 'active', kind: 'feature' }];
  assert.deepEqual(filterRequests(rows, ' atlas READ ', 'attention'), [rows[0]]);
  assert.deepEqual(filterRequests(rows, '456', 'active'), [rows[1]]);
  assert.deepEqual(filterRequests(rows, 'Atlas PDF', 'all'), []);
  assert.equal(rows.length, 2);
  assert.equal(filterRequests([{ ...rows[0], status: 'awaiting_approval' }], '', 'attention').length, 1);
});
test('variation expiry cannot appear active at deadline; revoke stays revoked', () => {
  const at = Date.parse('2026-10-09T12:00:00Z');
  assert.equal(effectiveVariationState('active', '2026-10-09T12:00:00Z', at), 'expired');
  assert.equal(effectiveVariationState('active', '2026-10-09T12:00:01Z', at), 'active');
  assert.equal(effectiveVariationState('revoked', '2026-10-10T12:00:00Z', at), 'revoked');
  assert.equal(effectiveVariationState('active', 'invalid', at), 'unknown');
});
test('observed grants require this request activation, exact variation, project and viewer', () => {
  const request = { id: 'r1', project_id: 'atlas', viewer_id: 'contractor' };
  const events = [{ request_id: 'r1', type: 'variation.activated', payload: { variation_id: 'v1' } }, { request_id: 'r2', type: 'variation.activated', payload: { variation_id: 'v2' } }];
  const read = { variation_id: 'v1', allowed: true, project_id: 'atlas', actor_id: 'contractor' };
  const observations = [read, { ...read, allowed: false }, { ...read, variation_id: null }, { ...read, variation_id: 'v2' }, { ...read, project_id: 'nova' }, { ...read, actor_id: 'admin' }];
  assert.equal(attributedReads(request, events, observations), 1);
  assert.equal(attributedReads(request, [], observations), 0);
});
test('historical checks cannot cover another hash; conflicting current results remain mixed', () => {
  const checks = [{ subject_hash: 'old', result: { passed: true } }, { subject_hash: 'new', result: { passed: false } }];
  assert.equal(currentPatchCheck('new', checks), 'failed');
  assert.equal(currentPatchCheck('other', checks), 'missing');
  assert.equal(currentPatchCheck(null, checks), 'missing');
  assert.equal(currentPatchCheck('new', [...checks, { subject_hash: 'new', result: { passed: true } }]), 'mixed');
});
test('a saved repository pass is not presented as current authorization',()=>{
  assert.equal(repositoryCheckLabel('passed',false),'Saved checks passed');
  assert.equal(repositoryCheckLabel('passed',true),'Current checks passed');
  assert.equal(repositoryCheckLabel('failed',true),'Checks failed');
  assert.equal(repositoryCheckLabel('running',false),'Checking the baseline and candidate');
  assert.equal(repositoryCheckLabel('canceled',false),'Attempt stopped locally');
  assert.equal(repositoryCheckLabel('recovering',false),'Recovering interrupted checks');
  assert.equal(repositoryCheckLabel('recovery_blocked',false),'Recovery needs attention');
  assert.equal(repositoryCheckLabel('recovered',false),'Replaced after worker crash');
  assert.equal(repositoryCheckLabel('all_secure',true),'Unrecognized check state');
  assert.equal(repositoryCheckLabel(undefined,true),'No saved checks');
});
function reconstruct(lines, side) { return lines.filter(l => side === 'old' ? l.kind !== 'add' : l.kind !== 'remove').map(l => l.text).join('\n'); }
test('line diff preserves exact old and new source including empty lines and trailing newline', () => {
  for (const [before, after] of [['a\nb\n', 'a\nc\n'], ['', 'hello'], ['hello', ''], ['a\n\na', 'a\na\n'], ['same', 'same']]) {
    const diff = lineDiff(before, after);
    assert.equal(reconstruct(diff, 'old'), before);
    assert.equal(reconstruct(diff, 'new'), after);
  }
  assert.deepEqual(lineDiff('a\nb', 'a\nc').map(l => l.kind), ['context', 'remove', 'add']);
});
test('large diff uses bounded full replacement and retains source', () => {
  const before = Array(600).fill('old').join('\n');
  const after = Array(600).fill('new').join('\n');
  const diff = lineDiff(before, after);
  assert.equal(diff.length, 1200);
  assert.equal(reconstruct(diff, 'old'), before);
  assert.equal(reconstruct(diff, 'new'), after);
});
