import test from 'node:test';
import assert from 'node:assert/strict';
import { sameSession, sameProposal, submissionForIntent } from '../src/responseIdentity.ts';

const session = { user_id: 'atlas-admin', tenant_id: 'atlas', role: 'admin', csrf_token: 'local-test-session' };
const proposal = { session, requestId: 'request-a', proposalId: 'proposal-a', proposalHash: 'hash-a' };

test('a late preview cannot bind to another request, proposal, hash, tenant or login session', () => {
  assert.equal(sameProposal(proposal, { ...proposal, session: { ...session } }), true);
  for (const changed of [
    null,
    { ...proposal, requestId: 'request-b' },
    { ...proposal, proposalId: 'proposal-b' },
    { ...proposal, proposalHash: 'hash-b' },
    { ...proposal, session: { ...session, tenant_id: 'nova' } },
    { ...proposal, session: { ...session, user_id: 'atlas-engineer' } },
    { ...proposal, session: { ...session, role: 'engineer' } },
    { ...proposal, session: { ...session, csrf_token: 'new-login-same-person' } },
  ]) assert.equal(sameProposal(proposal, changed), false);
  assert.equal(sameProposal(null, null), false);
  assert.equal(sameSession(session, null), false);
});

test('a lost create response retains its key until the submitted intent changes', () => {
  let generated = 0;
  const key = () => `key-${++generated}`;
  const original = submissionForIntent(null, 'body-a', key);
  assert.equal(submissionForIntent(original, 'body-a', key), original);
  assert.equal(submissionForIntent(original, 'body-a', key).key, 'key-1');
  const edited = submissionForIntent(original, 'body-b', key);
  assert.equal(edited.key, 'key-2');
  assert.equal(submissionForIntent(null, 'body-a', key).key, 'key-3');
  assert.equal(generated, 3);
});
test('team-scope changes fence late previews even when the login cookie stays the same',()=>{
  const before={...session,scope_version:'payments-v1'},after={...session,scope_version:'billing-v2'};
  assert.equal(sameSession(before,{...before}),true);
  assert.equal(sameSession(before,after),false);
  assert.equal(sameProposal({...proposal,session:before},{...proposal,session:after}),false);
  assert.equal(sameSession(before,session),false);
});
