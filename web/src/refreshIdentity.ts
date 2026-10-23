export type RefreshReview = {
  schema: string; actor_id: string; tenant_id: string; request_id: string; request_revision: number;
  proposal_id: string; proposal_hash: string; saved_preview_hash: string; fresh_preview_hash: string;
  review_hash: string; can_refresh: boolean; notice: string;
  parameters: { project_id: string; viewer_id: string; expires_at: string };
  preview: { snapshot_hash: string; visible_documents: { id: string; title: string }[] };
};
export type RefreshIdentity = { actor: string; tenant: string; requestId: string; revision: number; proposalId: string; proposalHash: string };
const hash = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);

/** Fences display as well as mutations against a previous login or proposal. */
export function matchesRefreshReview(value: unknown, identity: RefreshIdentity): value is RefreshReview {
  if (!value || typeof value !== 'object') return false;
  const r = value as Partial<RefreshReview>;
  return r.schema === 'ownstack.proposal-refresh.v1' && r.actor_id === identity.actor && r.tenant_id === identity.tenant
    && r.request_id === identity.requestId && r.request_revision === identity.revision
    && r.proposal_id === identity.proposalId && r.proposal_hash === identity.proposalHash
    && hash(r.saved_preview_hash) && hash(r.fresh_preview_hash) && hash(r.review_hash)
    && r.can_refresh === (r.saved_preview_hash !== r.fresh_preview_hash) && typeof r.notice === 'string'
    && typeof r.parameters?.project_id === 'string' && typeof r.parameters?.viewer_id === 'string'
    && typeof r.parameters?.expires_at === 'string' && Number.isFinite(Date.parse(r.parameters.expires_at))
    && r.preview?.snapshot_hash === r.fresh_preview_hash && Array.isArray(r.preview.visible_documents)
    && r.preview.visible_documents.every(d => d && typeof d.id === 'string' && typeof d.title === 'string');
}
