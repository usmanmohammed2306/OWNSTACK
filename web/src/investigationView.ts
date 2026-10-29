/** Display boundaries for saved advisory investigations, separate from approvals. */
export type InvestigationScope = { tenant: string; request: string; revision: number };
export type InvestigationRun = {
  id: string; tenant_id: string; request_id: string; revision: number;
  state: 'ready' | 'running' | 'completed' | 'failed' | 'stopped' | 'stale';
  version: number; source: 'nemotron' | 'offline_policy'; max_steps: number;
  steps: { action: string; source?: string; observation_hash?: string; latency_ms: number }[];
  error_code: string | null;
  result: null | { handoff: 'review_code' | 'prepare_for_host_preview' | 'clarify_request';
    citations: { source: string; hash: string }[]; untrusted_note: string; limitation: string };
  limitation: string;
};
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const integer = (value: unknown) => Number.isSafeInteger(value) && (value as number) >= 0;
const sources = ['request', 'contract', 'engineering'];
const hash = (value: unknown) => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);

export function investigationMatches(value: unknown, scope: InvestigationScope): value is InvestigationRun {
  if (!object(value) || typeof value.id !== 'string' || !value.id || value.tenant_id !== scope.tenant
      || value.request_id !== scope.request || value.revision !== scope.revision || !integer(value.version)
      || !['ready', 'running', 'completed', 'failed', 'stopped', 'stale'].includes(String(value.state))
      || !['nemotron', 'offline_policy'].includes(String(value.source)) || value.max_steps !== 4
      || !Array.isArray(value.steps) || value.steps.length > 4 || typeof value.limitation !== 'string') return false;
  const seen = new Map<string, string>();
  for (const step of value.steps) {
    if (!object(step) || !integer(step.latency_ms)) return false;
    if (step.action === 'conclude') {
      if (step !== value.steps.at(-1)) return false;
    } else {
      if (typeof step.source !== 'string' || !sources.includes(step.source) || step.action !== `inspect_${step.source}`
          || seen.has(step.source) || !hash(step.observation_hash)) return false;
      seen.set(step.source, step.observation_hash as string);
    }
  }
  if (value.state === 'completed') {
    const result = value.result;
    if (!object(result) || !['review_code', 'prepare_for_host_preview', 'clarify_request'].includes(String(result.handoff))
        || typeof result.untrusted_note !== 'string' || result.untrusted_note.length > 400
        || !Array.isArray(result.citations) || result.citations.length < 2 || result.citations.length > 3
        || value.steps.at(-1)?.action !== 'conclude') return false;
    const cited = new Set<string>();
    for (const citation of result.citations) {
      if (!object(citation) || typeof citation.source !== 'string' || cited.has(citation.source)
          || !seen.has(citation.source) || seen.get(citation.source) !== citation.hash) return false;
      cited.add(citation.source);
    }
    if (!cited.has('request') || !cited.has(result.handoff === 'review_code' ? 'engineering' : 'contract')) return false;
  } else if (value.result !== null) return false;
  return true;
}

export function handoffLabel(value: InvestigationRun['result']) {
  return value?.handoff === 'review_code' ? 'Continue in code review'
    : value?.handoff === 'prepare_for_host_preview' ? 'Prepare for host preview'
    : value?.handoff === 'clarify_request' ? 'Clarify the request first' : 'Investigation in progress';
}
