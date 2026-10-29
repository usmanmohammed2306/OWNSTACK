import test from 'node:test';
import assert from 'node:assert/strict';
import { parseReleaseDraft, releaseCanApprove, releaseCanRead, releaseCanWrite, releaseCheckRows,
  releaseEvidenceIdentity, releaseFailedCases, releaseHash, releaseIntent, releaseRequirementIdentity,
  releaseRequirementRows, releaseReviewAllowed, releaseStateText } from '../src/releaseAssuranceState.ts';

const sha = 'a'.repeat(64), otherSha = 'b'.repeat(64);
const spec = { key: 'atlas-docs', version: 1, title: 'Assigned documents only', customer_tenant_id: 'atlas',
  source_ref: 'ATLAS-42', owner_id: 'owner', expires_at: null,
  cases: [{ case_id: 'atlas-deny', title: 'Unassigned contractor', kind: 'target', input: { resource_tenant_id: 'atlas' },
    expected: { status_code: 403, visible_fields: [] } },
  { case_id: 'nova-control', title: 'Nova unchanged', kind: 'control', input: { resource_tenant_id: 'nova' },
    expected: { status_code: 200, visible_fields: ['id', 'title'] } }] };
const requirement = { id: 'requirement-a', project_id: 'project-a', state: 'approved', requirement_hash: sha,
  spec, created_by: 'engineer', approved_by: 'admin' };
const check = { id: 'check-a', project_id: 'project-a', state: 'passed', revision: 3, baseline_sha256: sha,
  candidate_sha256: otherSha, requirements_sha256: sha, requirement_ids: ['requirement-a'],
  report: { assessments: [] }, evidence_hash: sha, decision: null, reason: null,
  created_at: '2026-10-27T00:00:00Z', completed_at: '2026-10-27T00:00:01Z' };

test('manager inspection never grants approval, queue or release decision permissions', () => {
  assert.equal(releaseCanRead('manager'), true);
  assert.equal(releaseCanWrite('manager'), false);
  assert.equal(releaseCanApprove('manager'), false);
  assert.equal(releaseReviewAllowed(check, 'manager'), false);
  for (const role of ['member', 'contractor', 'product_owner', 'unknown']) {
    assert.equal(releaseCanRead(role), false);
    assert.equal(releaseCanWrite(role), false);
    assert.equal(releaseCanApprove(role), false);
  }
  for (const role of ['admin', 'engineer']) assert.equal(releaseCanWrite(role), true);
  assert.equal(releaseCanApprove('engineer'), false);
  assert.equal(releaseCanApprove('admin'), true);
});

test('requirement responses reject unknown project scope and duplicate identities', () => {
  assert.equal(releaseRequirementRows([requirement], ['project-a']), true);
  assert.equal(releaseRequirementRows([], ['project-a']), true);
  assert.equal(releaseRequirementRows([requirement], ['other-project']), false);
  assert.equal(releaseRequirementRows([requirement, requirement], ['project-a']), false);
  for (const change of [{ requirement_hash: 'fake' }, { state: 'auto_approved' }, { spec: null },
    { spec: { ...spec, cases: [] } }, { spec: { ...spec, cases: [{ ...spec.cases[0], expected: null }] } }])
    assert.equal(releaseRequirementRows([{ ...requirement, ...change }], ['project-a']), false);
});

test('check responses require scoped unique records, source hashes and revisions', () => {
  assert.equal(releaseCheckRows([check], ['project-a']), true);
  assert.equal(releaseCheckRows([check], ['other']), false);
  assert.equal(releaseCheckRows([check, check], ['project-a']), false);
  for (const change of [{ revision: 0 }, { revision: true }, { candidate_sha256: 'short' },
    { evidence_hash: 'forged' }, { requirement_ids: ['same', 'same'] }, { state: 'released' },
    { decision: 'deployed' }, { report: [] }])
    assert.equal(releaseCheckRows([{ ...check, ...change }], ['project-a']), false);
});

test('human release review requires exact passing saved evidence and no earlier decision', () => {
  assert.equal(releaseReviewAllowed(check, 'engineer'), true);
  for (const change of [{ state: 'regression' }, { state: 'baseline_failed' }, { state: 'blocked' },
    { state: 'queued' }, { state: 'canceled' }, { evidence_hash: null }, { report: null },
    { decision: 'reject' }, { decision: 'accept_for_manual_release' }])
    assert.equal(releaseReviewAllowed({ ...check, ...change }, 'engineer'), false);
  assert.equal(releaseReviewAllowed(null, 'admin'), false);
});

test('checkbox acknowledgements cannot survive changed requirement or evidence identity', () => {
  const req = releaseRequirementIdentity(requirement), evidence = releaseEvidenceIdentity(check);
  for (const change of [{ id: 'new' }, { project_id: 'new' }, { requirement_hash: otherSha }])
    assert.notEqual(releaseRequirementIdentity({ ...requirement, ...change }), req);
  for (const change of [{ id: 'new' }, { project_id: 'new' }, { revision: 4 }, { evidence_hash: otherSha }])
    assert.notEqual(releaseEvidenceIdentity({ ...check, ...change }), evidence);
  assert.equal(releaseRequirementIdentity(null), '');
  assert.equal(releaseEvidenceIdentity({ ...check, evidence_hash: null }), '');
});

test('idempotent check intent includes every approved requirement but ignores array order', () => {
  const intent = releaseIntent('p', sha, otherSha, ['a', 'b']);
  assert.equal(intent, releaseIntent('p', sha, otherSha, ['b', 'a']));
  assert.notEqual(intent, releaseIntent('other', sha, otherSha, ['a', 'b']));
  assert.notEqual(intent, releaseIntent('p', otherSha, otherSha, ['a', 'b']));
  assert.notEqual(intent, releaseIntent('p', sha, sha, ['a', 'b']));
  assert.notEqual(intent, releaseIntent('p', sha, otherSha, ['a']));
});

test('failed case presentation derives actual status and field differences, not claimed pass', () => {
  const mismatch = { requirement_key: 'atlas-docs', case_id: 'atlas-deny', candidate_passed: true,
    expected: { status_code: 403, visible_fields: [] },
    observed_baseline: { status_code: 403, visible_fields: [] },
    observed_candidate: { status_code: 200, visible_fields: ['id', 'tax_id'] } };
  assert.deepEqual(releaseFailedCases({ ...check, report: { assessments: [mismatch] } }), [mismatch]);
  const control = { ...mismatch, expected: { status_code: 200, visible_fields: ['id', 'title'] },
    observed_baseline: { status_code: 200, visible_fields: ['title', 'id'] },
    observed_candidate: { status_code: 200, visible_fields: ['title', 'id'] } };
  assert.deepEqual(releaseFailedCases({ ...check, report: { assessments: [control] } }), []);
  const baselineBad = { ...control, observed_baseline: { status_code: 403, visible_fields: [] } };
  assert.deepEqual(releaseFailedCases({ ...check, report: { assessments: [baselineBad] } }), [baselineBad]);
  assert.deepEqual(releaseFailedCases({ ...check, report: null }), []);
  assert.deepEqual(releaseFailedCases({ ...check, report: { assessments: [null, {}] } }), []);
});

test('states describe saved progress without suggesting automatic release', () => {
  assert.match(releaseStateText('queued'), /Waiting/);
  assert.match(releaseStateText('baseline_failed'), /Baseline/);
  assert.match(releaseStateText('regression'), /behavior changed/);
  assert.equal(releaseStateText('passed'), 'Checks passed');
  assert.equal(releaseStateText('canceled'), 'Canceled locally');
  assert.equal(releaseStateText('new_unknown_state'), 'Unknown saved state');
});

test('drafts are explicit reviewed JSON, bounded and ultimately server-validated', () => {
  assert.deepEqual(parseReleaseDraft(JSON.stringify(spec)), spec);
  for (const value of ['', 'null', '{"cases":[]}', 'not JSON', ' '.repeat(131_073)])
    assert.throws(() => parseReleaseDraft(value));
  assert.equal(releaseHash(sha), true);
  for (const value of [null, true, 'a'.repeat(63), 'A'.repeat(64), 'g'.repeat(64)]) assert.equal(releaseHash(value), false);
});
