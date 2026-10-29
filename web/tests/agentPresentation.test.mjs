import test from 'node:test';
import assert from 'node:assert/strict';
import { agentPresentation } from '../src/agentPresentation.ts';

const run = (state, steps = [], handoff = 'prepare_for_host_preview') => ({ state, steps,
  result: state === 'completed' ? { handoff } : null });

test('a request is not an observation and paused AI does not imply work ran', () => {
  const view = agentPresentation(null, false, true, false);
  assert.equal(view.title, 'Your request is saved');
  assert.equal(view.nodes.some(n => n.done), false);
  assert.match(view.description, /paused/);
});
test('only saved inspected sources light up, never guessed progress', () => {
  const view = agentPresentation(run('ready', [{ action: 'inspect_request', source: 'request' }]), true, false, false);
  assert.deepEqual(view.nodes.map(n => n.done), [true, false, false]);
  assert.equal(view.complete, false);
});
test('code evidence changes the witness label and completed advice is not a release', () => {
  const view = agentPresentation(run('completed', [{ action: 'inspect_request', source: 'request' },
    { action: 'inspect_engineering', source: 'engineering' }, { action: 'conclude' }], 'review_code'), true, true, false);
  assert.equal(view.title, 'This needs a code change');
  assert.equal(view.nodes[1].detail, 'Code evidence');
  assert.deepEqual(view.nodes.map(n => n.done), [true, true, true]);
  assert.match(view.description, /Applying a change needs a separate review/);
});
test('failed, stale and stopped runs preserve observations without a success marker', () => {
  for (const state of ['failed', 'stale', 'stopped']) {
    const view = agentPresentation(run(state, [{ action: 'inspect_contract', source: 'contract' }]), true, false, false);
    assert.match(view.title, /attention/);
    assert.deepEqual(view.nodes.map(n => n.done), [false, true, false]);
  }
});
test('credits exhausted still shows the saved conclusion and asks clarification honestly', () => {
  assert.match(agentPresentation(null, true, true, false).description, /used up/);
  assert.equal(agentPresentation(run('completed', [], 'clarify_request'), false, true, false).title, 'A little more detail is needed');
});
test('running status describes saved work without claiming remote cancellation', () => {
  const view = agentPresentation(run('running'), true, false, true);
  assert.equal(view.title, 'Looking into your request');
  assert.equal(view.complete, false);
  assert.equal(view.nodes.some(n => n.done), false);
});

test('a feature points toward code evidence without claiming it has been inspected', () => {
  const view = agentPresentation(null, true, false, false, true);
  assert.equal(view.nodes[1].detail, 'Code evidence');
  assert.equal(view.nodes[1].done, false);
});
