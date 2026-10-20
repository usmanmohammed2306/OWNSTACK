import { sameSession, type SessionIdentity } from './responseIdentity.ts';

export type RepairScope = { session: SessionIdentity; itemId: string };
export type RepairReview = RepairScope & { runId: string; attemptId: string; patchHash: string };
export type RepairCandidate = { edits: { path: string; old: string; new: string }[] };
export type RepairAttempt = {
  id: string; number: number; state: string; model_id: string;
  candidate: RepairCandidate | null; candidate_hash: string | null;
  checks: { passed?: boolean; checks_completed?: number; checks_expected?: number;
    stderr?: string; stdout?: string; runner?: string; oracle_version?: string;
    cases?: { id: string; passed: boolean; reason?: string }[] } | null;
  usage: { live?: boolean; latency_ms?: number | null; input_tokens?: number | null; output_tokens?: number | null } | null;
  error_code: string | null; deadline_at: string;
};
export type RepairRun = {
  id: string; item_id: string; state: string; max_attempts: number;
  original_patch_hash: string; error_code: string | null;
  configuration: { mode: string; model: string }; provenance: Record<string, unknown>;
  deadline_at: string; release_state: string; remote_cancellation_verified: boolean;
  attempts: RepairAttempt[];
  workflow?: { engine: string | null; schema: string | null; human_review_required: boolean;
    persistence: string; last_phase: { phase: string; accepted: boolean; nodes: string[];
      reviews: { role: string; passed: boolean; code: string }[] } | null };
};

/** Display fences only. Every mutation remains authorized and fenced by the API. */
export function sameRepairScope(left: RepairScope | null, right: RepairScope | null): boolean {
  return !!left && !!right && left.itemId === right.itemId && sameSession(left.session, right.session);
}

export function sameRepairReview(left: RepairReview | null, right: RepairReview | null): boolean {
  return !!left && !!right && sameRepairScope(left, right) && left.runId === right.runId
    && left.attemptId === right.attemptId && left.patchHash === right.patchHash;
}

export function repairStartBlock(input: {
  role: string; mode: string; remainingCalls: number | null | undefined; itemStatus: string;
  patchHash: string | null; humanDecision: string | null; runs: RepairRun[];
}): string | null {
  if (input.role !== 'engineer') return 'Only a tenant engineer can start or adopt a repair.';
  if (input.mode === 'off') return 'AI is paused. Saved evidence and manual work remain available.';
  if (!['fixture', 'nebius'].includes(input.mode)) return 'Inference mode is not available.';
  if (input.mode === 'nebius' && (typeof input.remainingCalls !== 'number' || input.remainingCalls < 1))
    return 'No confirmed inference allowance remains. Do not reset the saved counter.';
  if (input.runs.some(run => ['running', 'awaiting_review'].includes(run.state))) return 'A saved repair is already active. Review it or take over.';
  if (input.itemStatus !== 'checks_failed' || !input.patchHash || input.humanDecision)
    return 'A failed exact patch with no release decision is required before repair.';
  return null;
}

/** Never infer a usable candidate from an old passed attempt or a partial diff. */
export function repairCandidateToReview(run: RepairRun): RepairAttempt | null {
  const candidate = run.attempts.at(-1);
  if (run.state !== 'awaiting_review' || !candidate || candidate.state !== 'passed'
      || !candidate.candidate_hash || candidate.checks?.passed !== true
      || candidate.candidate?.edits.length !== 1) return null;
  const edit = candidate.candidate.edits[0];
  return edit.path === 'sample_app/report.py' && typeof edit.old === 'string' && typeof edit.new === 'string' ? candidate : null;
}

export function savedRepairRowsMatch(rows: RepairRun[], itemId: string): boolean {
  return rows.every(run => run.item_id === itemId) && new Set(rows.map(run => run.id)).size === rows.length;
}

export function repairProgressText(runs: RepairRun[]): string {
  const run = runs.find(row => ['running', 'awaiting_review'].includes(row.state)) || runs[0];
  if (!run) return 'No saved repair runs for this work item.';
  const attempt = run.attempts.at(-1);
  return `Saved repair: ${run.state.replaceAll('_', ' ')}.${attempt ? ` Attempt ${attempt.number}: ${attempt.state.replaceAll('_', ' ')}.` : ' No attempt recorded yet.'} Refresh does not call AI.`;
}
