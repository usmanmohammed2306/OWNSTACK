import test from 'node:test';
import assert from 'node:assert/strict';
import { scenarioContent, variationFrame } from '../src/variationModel.ts';

test('all eight illustrative stages preserve Nova, one shared app and no deployment', () => {
  for (const scenario of ['access', 'pdf']) {
    for (let stage = 0; stage < 4; stage += 1) {
      const frame = variationFrame(scenario, stage);
      assert.equal(frame.nova, 'unchanged');
      assert.equal(frame.sharedAppCount, 1);
      assert.equal(frame.deployed, false);
      assert.equal(scenarioContent[scenario].stages[stage].novaLabel, 'Unchanged');
    }
  }
});

test('access illustration separates contract, preview, temporary access and rollback', () => {
  assert.deepEqual([0, 1, 2, 3].map(stage => variationFrame('access', stage)), [
    { atlas: 'unchanged', nova: 'unchanged', route: 'contract', gate: 'required', sharedAppCount: 1, deployed: false },
    { atlas: 'preview', nova: 'unchanged', route: 'contract', gate: 'required', sharedAppCount: 1, deployed: false },
    { atlas: 'temporary', nova: 'unchanged', route: 'atlas', gate: 'illustrated-approval', sharedAppCount: 1, deployed: false },
    { atlas: 'revoked', nova: 'unchanged', route: 'closed', gate: 'illustrated-approval', sharedAppCount: 1, deployed: false },
  ]);
  assert.match(scenarioContent.access.stages[1].description, /does not grant access/);
});

test('PDF never uses the access contract, grants access or bypasses the human gate', () => {
  for (let stage = 0; stage < 4; stage += 1) {
    assert.deepEqual(variationFrame('pdf', stage), {
      atlas: 'unchanged', nova: 'unchanged', route: 'engineering', gate: 'required', sharedAppCount: 1, deployed: false,
    });
  }
  assert.match(scenarioContent.pdf.stages[2].description, /not a security guarantee or deployment/);
  assert.match(scenarioContent.pdf.stages[3].description, /does not merge or deploy/);
});

test('invalid, fractional and out-of-bounds stages have deterministic safe display states', () => {
  for (const stage of [NaN, Infinity, -Infinity, -100, -0.5]) {
    assert.deepEqual(variationFrame('access', stage), variationFrame('access', 0));
  }
  assert.deepEqual(variationFrame('access', 1.99), variationFrame('access', 1));
  assert.deepEqual(variationFrame('access', 2.99), variationFrame('access', 2));
  for (const stage of [3.5, 4, Number.MAX_VALUE]) {
    assert.deepEqual(variationFrame('access', stage), variationFrame('access', 3));
  }
  for (const stage of [NaN, Infinity, -Infinity, -100, 1.99, Number.MAX_VALUE]) {
    assert.deepEqual(variationFrame('pdf', stage), variationFrame('pdf', 0));
  }
});

test('illustration names identify the product boundary instead of generic machinery', () => {
  assert.deepEqual(scenarioContent.access.stages.map(stage => stage.name), ['Contract', 'Preview', 'Atlas only', 'Rollback']);
  assert.deepEqual(scenarioContent.pdf.stages.map(stage => stage.name), ['Boundary', 'Diff', 'Checks', 'Handoff']);
});
