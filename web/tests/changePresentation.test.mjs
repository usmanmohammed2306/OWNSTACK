import test from 'node:test';
import assert from 'node:assert/strict';
import { accessRequestText, changeStatus, changeTitle, personName, projectName } from '../src/changePresentation.ts';
import { filterRequests } from '../src/review.ts';

test('an expired approved access request cannot look current at its exact deadline', () => {
  const request = { kind: 'access', status: 'active', expires_at: '2026-10-25T12:00:00Z' };
  const deadline = Date.parse(request.expires_at);
  assert.equal(changeStatus(request, deadline - 1), 'active');
  assert.equal(changeStatus(request, deadline), 'expired');
  assert.equal(changeStatus(request, deadline + 1), 'expired');
  assert.equal(request.status, 'active');
});
test('organization access drafts name the selected project instead of an ambiguous placeholder',()=>{
  for(const name of ['Project Atlas','Billing workspace','Credit Operations']){
    assert.equal(accessRequestText(name),`Give this person read-only access to ${name} until the selected expiry.`);
    assert.ok(!accessRequestText(name).includes('this project'));
  }
});
test('revocation, feature requests and malformed dates are never inferred into grants', () => {
  const expired = '2020-01-01T00:00:00Z';
  for (const status of ['revoked', 'failed', 'new', 'awaiting_approval', 'unknown']) {
    assert.equal(changeStatus({ kind: 'access', status, expires_at: expired }), status);
  }
  assert.equal(changeStatus({ kind: 'feature', status: 'active', expires_at: expired }), 'active');
  for (const expires_at of [null, undefined, '', 'invalid']) {
    assert.equal(changeStatus({ kind: 'access', status: 'active', expires_at }), 'active');
  }
});
test('friendly known names do not invent identities or rewrite unknown identifiers', () => {
  assert.equal(projectName('atlas-project'), 'Project Atlas');
  assert.equal(projectName('nova-project'), 'Project Nova');
  assert.equal(personName('nova-contractor'), 'Nova contractor');
  assert.equal(personName('customer-123'), 'customer-123');
  assert.equal(projectName('external-123'), 'external-123');
  assert.equal(personName(null), 'No person selected');
  assert.equal(projectName(null), 'Workspace');
  assert.equal(changeTitle('feature'), 'Feature request');
  assert.equal(changeTitle('access'), 'Temporary access');
  assert.equal(changeTitle('unknown'), 'Customer request');
});

test('expired access leaves the active filter while the persisted history is unchanged', () => {
  const rows = [{ id: 'old', text: 'Read access', status: 'active', kind: 'access', expires_at: '2020-01-01T00:00:00Z' },
    { id: 'new', text: 'Read access', status: 'active', kind: 'access', expires_at: '2030-01-01T00:00:00Z' }];
  const display = rows.map(row => ({ ...row, status: changeStatus(row, Date.parse('2026-10-25T12:00:00Z')) }));
  assert.deepEqual(filterRequests(display, '', 'active').map(row => row.id), ['new']);
  assert.equal(rows[0].status, 'active');
});
