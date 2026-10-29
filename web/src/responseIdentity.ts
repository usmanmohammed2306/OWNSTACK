/** Browser display fences only. Server authorization remains authoritative. */
export type SessionIdentity = { user_id: string; tenant_id: string; csrf_token: string; role: string;scope_version?:string };
export type ProposalIdentity = { session: SessionIdentity; requestId: string; proposalId: string; proposalHash: string };

export function sameSession(left: SessionIdentity | null, right: SessionIdentity | null): boolean {
  return !!left && !!right && left.user_id === right.user_id && left.tenant_id === right.tenant_id
    && left.csrf_token === right.csrf_token && left.role === right.role&&left.scope_version===right.scope_version;
}

export function sameProposal(left: ProposalIdentity | null, right: ProposalIdentity | null): boolean {
  return !!left && !!right && sameSession(left.session, right.session)
    && left.requestId === right.requestId && left.proposalId === right.proposalId
    && left.proposalHash === right.proposalHash;
}

export type PendingSubmission = { intent: string; key: string };
/** Reuse an unconfirmed submission key; an edited body gets a different key. */
export function submissionForIntent(previous: PendingSubmission | null, intent: string, createKey: () => string): PendingSubmission {
  return previous?.intent === intent ? previous : { intent, key: createKey() };
}
