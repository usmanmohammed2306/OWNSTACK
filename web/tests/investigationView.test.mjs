import test from 'node:test';
import assert from 'node:assert/strict';
import { investigationMatches, handoffLabel } from '../src/investigationView.ts';
const scope = { tenant: 'atlas', request: 'req-1', revision: 1 };
const hash = 'a'.repeat(64);
const fixture = () => ({ id: 'run-1', tenant_id: 'atlas', request_id: 'req-1', revision: 1,
  state: 'completed', version: 6, source: 'offline_policy', max_steps: 4, error_code: null,
  steps: [{ action: 'inspect_request', source: 'request', observation_hash: hash, latency_ms: 0 },
    { action: 'inspect_contract', source: 'contract', observation_hash: hash, latency_ms: 2 },
    { action: 'conclude', latency_ms: 1 }],
  result: { handoff: 'prepare_for_host_preview', citations: [{ source: 'request', hash }, { source: 'contract', hash }],
    untrusted_note: 'Offline policy handoff. No model used.', limitation: 'Advisory only.' }, limitation: 'Advisory only.' });

test('a cited handoff is displayed as preparation, never approval', () => {
  const value = fixture();
  assert.equal(investigationMatches(value, scope), true);
  assert.equal(handoffLabel(value.result), 'Prepare for host preview');
});
test('wrong tenant, request, revision or unknown state is rejected', () => {
  for (const change of [{ tenant_id: 'nova' }, { request_id: 'other' }, { revision: 2 },
    { state: 'approved' }, { source: 'invented' }, { version: -1 }, { max_steps: 99 }]) {
    assert.equal(investigationMatches({ ...fixture(), ...change }, scope), false);
  }
});
test('fabricated and duplicate citations cannot become a saved handoff', () => {
  for (const citations of [[{ source: 'request', hash }], [{ source: 'request', hash }, { source: 'contract', hash: 'b'.repeat(64) }],
    [{ source: 'request', hash }, { source: 'request', hash }], [{ source: 'request', hash }, { source: 'engineering', hash }]]) {
    const value = fixture(); value.result.citations = citations;
    assert.equal(investigationMatches(value, scope), false);
  }
});
test('unknown tools, duplicated inspections, excessive steps and premature results fail', () => {
  for (const mutate of [v => { v.steps[0].action = 'deploy'; }, v => { v.steps.splice(1, 0, v.steps[0]); },
    v => { v.steps.push(...v.steps); }, v => { v.state = 'running'; }, v => { v.steps.pop(); }]) {
    const value = fixture(); mutate(value);
    assert.equal(investigationMatches(value, scope), false);
  }
});
test('code handoff needs engineering evidence and historical failure remains a failure', () => {
  const value = fixture(); value.result.handoff = 'review_code';
  assert.equal(investigationMatches(value, scope), false);
  value.steps[1] = { action: 'inspect_engineering', source: 'engineering', observation_hash: hash, latency_ms: 1 };
  value.result.citations[1].source = 'engineering';
  assert.equal(investigationMatches(value, scope), true);
  value.state = 'failed'; value.result = null;
  assert.equal(investigationMatches(value, scope), true);
  assert.equal(handoffLabel(value.result), 'Investigation in progress');
});
