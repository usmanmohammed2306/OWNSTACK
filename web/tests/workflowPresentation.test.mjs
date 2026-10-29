import test from 'node:test';
import assert from 'node:assert/strict';
const { requestLabel, requestSteps, hasApprovalHistory, primaryDestinations } = await import(process.env.OWNSTACK_PRESENTATION_MODULE || '../src/workflowPresentation.ts');

test('new work is saved, never implicitly prepared or approved', () => {
  for (const state of ['new', 'interpreting', 'failed', 'refused', 'unexpected']) {
    assert.deepEqual(requestSteps(state, false, false).map(s => s.done), [true, false, false, false]);
  }
});
test('preview requires a proposal and cannot become approval', () => {
  assert.deepEqual(requestSteps('awaiting_approval', true, false).map(s => s.done), [true, true, false, false]);
  assert.deepEqual(requestSteps('awaiting_approval', true, true).map(s => s.done), [true, true, true, false]);
  assert.deepEqual(requestSteps('new', false, true).map(s => s.done), [true, false, false, false]);
});
test('approval history stays distinct from currently effective access', () => {
  for (const state of ['active', 'expired', 'revoked']) assert.ok(requestSteps(state, false, false).every(s => s.done));
  assert.equal(requestLabel('active'), 'Approved');
  assert.equal(requestLabel('expired'), 'Expired');
  assert.equal(requestLabel('revoked'), 'Revoked');
});
test('labels use readable text without inferring success for unknown states', () => {
  assert.equal(requestLabel('awaiting_approval'), 'Ready for review');
  assert.equal(requestLabel('failed'), 'Needs attention');
  assert.equal(requestLabel('engineering'), 'Code review');
  assert.equal(requestLabel('future_unknown'), 'future unknown');
});

test('approved, revoked and expired preview snapshots stay historical', () => {
  for (const state of ['active', 'expired', 'revoked']) assert.equal(hasApprovalHistory(state), true);
  assert.equal(hasApprovalHistory('new', 'approved'), true);
  assert.equal(hasApprovalHistory('awaiting_approval', 'ready'), false);
  assert.equal(hasApprovalHistory('engineering'), false);
});

test('everyday navigation is limited to the role’s three primary tasks', () => {
  assert.deepEqual(primaryDestinations('admin'), ['demo', 'journey', 'access']);
  assert.deepEqual(primaryDestinations('member'), ['demo', 'journey', 'access']);
  assert.deepEqual(primaryDestinations('engineer'), ['demo', 'journey', 'engineering']);
  assert.deepEqual(primaryDestinations('contractor'), ['demo', 'journey']);
  assert.deepEqual(primaryDestinations('product_owner'), ['demo', 'convergence']);
});
