/** Display/response fences. Server permissions and exact-evidence checks are authoritative. */
export type ReleaseExpectation = { status_code: number; visible_fields: string[] };
export type ReleaseCase = { case_id: string; title: string; kind: 'target' | 'control';
  input: { resource_tenant_id: string; [key: string]: unknown }; expected: ReleaseExpectation };
export type ReleaseSpec = { key: string; version: number; title: string; customer_tenant_id: string;
  source_ref: string; owner_id: string; expires_at: string | null; cases: ReleaseCase[]; [key: string]: unknown };
export type ReleaseRequirement = { id: string; project_id: string; state: string; requirement_hash: string;
  spec: ReleaseSpec; created_by: string; approved_by: string | null };
export type ReleaseCheck = { id: string; project_id: string; state: string; revision: number;
  baseline_sha256: string; candidate_sha256: string; requirement_ids: string[];
  requirements_sha256: string; evidence_hash: string | null; decision: string | null;
  reason: string | null; report: Record<string, unknown> | null; created_at: string; completed_at: string | null };
export type ReleaseAssessment = { requirement_key: string; case_id: string; expected: ReleaseExpectation;
  observed_baseline: ReleaseExpectation; observed_candidate: ReleaseExpectation };

const hash = /^[a-f0-9]{64}$/;
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
export const releaseHash = (value: unknown): value is string => typeof value === 'string' && hash.test(value);
export const releaseCanRead = (role: string) => ['admin', 'engineer', 'manager'].includes(role);
export const releaseCanWrite = (role: string) => ['admin', 'engineer'].includes(role);
export const releaseCanApprove = (role: string) => role === 'admin';

function expectation(value: unknown): value is ReleaseExpectation {
  return record(value) && Number.isInteger(value.status_code) && Number(value.status_code) >= 100
    && Number(value.status_code) <= 599 && Array.isArray(value.visible_fields)
    && value.visible_fields.every(field => typeof field === 'string')
    && new Set(value.visible_fields).size === value.visible_fields.length;
}
function spec(value: unknown): value is ReleaseSpec {
  return record(value) && typeof value.key === 'string' && typeof value.title === 'string'
    && typeof value.customer_tenant_id === 'string' && typeof value.source_ref === 'string'
    && typeof value.owner_id === 'string' && Number.isInteger(value.version) && Number(value.version) >= 1
    && Array.isArray(value.cases) && value.cases.length >= 2 && value.cases.length <= 64
    && value.cases.every(item => record(item) && typeof item.case_id === 'string' && typeof item.title === 'string'
      && ['target', 'control'].includes(String(item.kind)) && record(item.input)
      && typeof item.input.resource_tenant_id === 'string' && expectation(item.expected));
}
export function releaseRequirementRows(value: unknown, projects: string[]): value is ReleaseRequirement[] {
  return Array.isArray(value) && new Set(value.map(item => item?.id)).size === value.length
    && value.every(item => record(item) && typeof item.id === 'string' && projects.includes(String(item.project_id))
      && ['draft', 'approved', 'superseded'].includes(String(item.state)) && releaseHash(item.requirement_hash)
      && typeof item.created_by === 'string' && (item.approved_by === null || typeof item.approved_by === 'string') && spec(item.spec));
}
export function releaseCheckRows(value: unknown, projects: string[]): value is ReleaseCheck[] {
  return Array.isArray(value) && new Set(value.map(item => item?.id)).size === value.length
    && value.every(item => record(item) && typeof item.id === 'string' && projects.includes(String(item.project_id))
      && ['queued', 'running', 'blocked', 'baseline_failed', 'regression', 'passed', 'canceled'].includes(String(item.state))
      && Number.isInteger(item.revision) && Number(item.revision) >= 1
      && releaseHash(item.baseline_sha256) && releaseHash(item.candidate_sha256) && releaseHash(item.requirements_sha256)
      && Array.isArray(item.requirement_ids) && item.requirement_ids.every(id => typeof id === 'string')
      && new Set(item.requirement_ids).size === item.requirement_ids.length
      && (item.evidence_hash === null || releaseHash(item.evidence_hash))
      && (item.report === null || record(item.report))
      && (item.decision === null || ['accept_for_manual_release', 'reject'].includes(String(item.decision))));
}

export function releaseRequirementIdentity(row: ReleaseRequirement | null): string {
  return row ? JSON.stringify([row.project_id, row.id, row.requirement_hash]) : '';
}
export function releaseEvidenceIdentity(row: ReleaseCheck | null): string {
  return row && row.evidence_hash ? JSON.stringify([row.project_id, row.id, row.revision, row.evidence_hash]) : '';
}
export function releaseReviewAllowed(row: ReleaseCheck | null, role: string): boolean {
  return !!row && releaseCanWrite(role) && row.state === 'passed' && !row.decision
    && releaseHash(row.evidence_hash) && !!row.report;
}
export function releaseIntent(project: string, baseline: string, candidate: string, requirements: string[]): string {
  return JSON.stringify({ project_id: project, baseline_sha256: baseline, candidate_sha256: candidate,
    requirement_ids: [...requirements].sort() });
}
export function releaseStateText(state: string): string {
  return ({ queued: 'Waiting for local worker', running: 'Checks running', blocked: 'Inspection needed',
    baseline_failed: 'Baseline requirement failed', regression: 'Customer behavior changed',
    passed: 'Checks passed', canceled: 'Canceled locally' } as Record<string, string>)[state] || 'Unknown saved state';
}
function sameExpectation(left: ReleaseExpectation, right: ReleaseExpectation): boolean {
  return left.status_code === right.status_code && [...left.visible_fields].sort().join('\u0000') === [...right.visible_fields].sort().join('\u0000');
}
/** Derive mismatches from displayed observations rather than a claimed pass flag. */
export function releaseFailedCases(row: ReleaseCheck | null): ReleaseAssessment[] {
  const rows = row?.report?.assessments;
  if (!Array.isArray(rows)) return [];
  return rows.filter((item): item is ReleaseAssessment => record(item) && typeof item.requirement_key === 'string'
    && typeof item.case_id === 'string' && expectation(item.expected) && expectation(item.observed_baseline)
    && expectation(item.observed_candidate)).filter(item => !sameExpectation(item.expected, item.observed_baseline)
      || !sameExpectation(item.expected, item.observed_candidate));
}
export function parseReleaseDraft(raw: string): ReleaseSpec {
  if (!raw.trim() || new TextEncoder().encode(raw).length > 131_072) throw new Error('Paste a reviewed requirement JSON smaller than 128 KiB.');
  const value: unknown = JSON.parse(raw);
  if (!spec(value)) throw new Error('The requirement needs its metadata, target cases and other-tenant controls. The server validates the complete schema.');
  return value;
}
