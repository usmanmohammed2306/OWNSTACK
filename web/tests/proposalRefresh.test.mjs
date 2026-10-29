import assert from 'node:assert/strict';
import { test } from 'node:test';
const { matchesRefreshReview } = await import(process.env.OWNSTACK_REFRESH_MODULE || '../src/refreshIdentity.ts');
const identity = { actor: 'atlas-engineer', tenant: 'atlas', requestId: 'request', revision: 1,
  proposalId: 'old-proposal', proposalHash: 'a'.repeat(64) };
const valid = { schema: 'ownstack.proposal-refresh.v1', actor_id: identity.actor, tenant_id: identity.tenant,
  request_id: identity.requestId, request_revision: 1, proposal_id: identity.proposalId, proposal_hash: identity.proposalHash,
  saved_preview_hash: 'b'.repeat(64), fresh_preview_hash: 'c'.repeat(64), review_hash: 'd'.repeat(64),
  can_refresh: true, notice: 'No permission granted',
  parameters: { project_id: 'atlas-project', viewer_id: 'atlas-contractor', expires_at: '2026-10-24T12:00:00Z' },
  preview: { snapshot_hash: 'c'.repeat(64), visible_documents: [{ id: 'doc', title: 'Atlas plan' }] } };

test('accepts exact reviewed identity and distinguishes unchanged snapshot', () => {
  assert.equal(matchesRefreshReview(valid, identity), true);
  assert.equal(matchesRefreshReview({ ...valid, saved_preview_hash: valid.fresh_preview_hash, can_refresh: false }, identity), true);
});
test('rejects old sessions, tenants, requests, revisions and proposal subjects', () => {
  for (const [key, value] of Object.entries({ actor_id: 'old-user', tenant_id: 'nova', request_id: 'other',
    request_revision: 2, proposal_id: 'other-proposal', proposal_hash: '0'.repeat(64) })) {
    assert.equal(matchesRefreshReview({ ...valid, [key]: value }, identity), false, key);
  }
});
test('rejects inconsistent or malformed snapshots before showing a review', () => {
  for (const value of [null, {}, { ...valid, schema: 'other' }, { ...valid, can_refresh: false },
    { ...valid, review_hash: 'bad' }, { ...valid, parameters: null },
    { ...valid, parameters: { ...valid.parameters, expires_at: 'bad' } },
    { ...valid, preview: { ...valid.preview, snapshot_hash: 'e'.repeat(64) } },
    { ...valid, preview: { ...valid.preview, visible_documents: [null] } },
    { ...valid, preview: { ...valid.preview, visible_documents: [{ id: 'doc', title: 7 }] } }]) {
    assert.equal(matchesRefreshReview(value, identity), false, JSON.stringify(value));
  }
});
