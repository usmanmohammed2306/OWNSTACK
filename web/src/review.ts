/** Presentation-only derivations. None of these helpers authorize host access. */
export function repositoryCheckLabel(state:string|undefined,currentUsable:boolean):string {
  if(state==='passed')return currentUsable?'Current checks passed':'Saved checks passed';
  const labels:Record<string,string>={queued:'Waiting for the local operator',running:'Checking the baseline and candidate',recovering:'Recovering interrupted checks',recovery_blocked:'Recovery needs attention',recovered:'Replaced after worker crash',failed:'Checks failed',blocked:'Checks blocked',timed_out:'Checks timed out',canceled:'Attempt stopped locally',superseded:'Attempt replaced'};
  return state?labels[state]||'Unrecognized check state':'No saved checks';
}
export type RequestFilter = 'all' | 'attention' | 'active' | 'closed';
type RequestSummary = { id: string; text: string; status: string; kind: string };
export function filterRequests<T extends RequestSummary>(rows: T[], query: string, filter: RequestFilter): T[] {
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  return rows.filter(row => {
    const haystack = `${row.id} ${row.text} ${row.status} ${row.kind}`.toLowerCase();
    const matches = terms.every(term => haystack.includes(term));
    const stateMatches = filter === 'all' || (filter === 'attention' && ['new', 'ready', 'awaiting_approval', 'failed', 'refused', 'engineering'].includes(row.status))
      || (filter === 'active' && row.status === 'active') || (filter === 'closed' && ['revoked', 'expired', 'refused'].includes(row.status));
    return matches && stateMatches;
  });
}

export function effectiveVariationState(state: string, expiresAt: string, now: number): string {
  if (state !== 'active') return state;
  const deadline = Date.parse(expiresAt);
  if (!Number.isFinite(deadline)) return 'unknown';
  return deadline <= now ? 'expired' : 'active';
}

type ReviewEvent = { request_id: string; type: string; payload: Record<string, unknown> };
type Observation = { variation_id: string | null; allowed: boolean; project_id: string; actor_id: string };
export function attributedReads(request: { id: string; project_id: string | null; viewer_id: string | null }, events: ReviewEvent[], observations: Observation[]): number {
  const ids = new Set(events.filter(e => e.request_id === request.id && e.type === 'variation.activated')
    .map(e => e.payload.variation_id).filter((id): id is string => typeof id === 'string'));
  return observations.filter(o => o.allowed && o.variation_id !== null && ids.has(o.variation_id)
    && o.project_id === request.project_id && o.actor_id === request.viewer_id).length;
}

export type DiffLine = { kind: 'context' | 'remove' | 'add'; text: string; oldLine: number | null; newLine: number | null };
/** Bounded LCS presentation diff. A large edit falls back to exact full replacement. */
export function lineDiff(oldSource: string, newSource: string): DiffLine[] {
  const before = oldSource === '' ? [] : oldSource.split('\n');
  const after = newSource === '' ? [] : newSource.split('\n');
  if (before.length * after.length > 250_000) return [
    ...before.map((text, i): DiffLine => ({ kind: 'remove', text, oldLine: i + 1, newLine: null })),
    ...after.map((text, i): DiffLine => ({ kind: 'add', text, oldLine: null, newLine: i + 1 })),
  ];
  const width = after.length + 1;
  const grid = new Uint32Array((before.length + 1) * width);
  for (let i = before.length - 1; i >= 0; i--) for (let j = after.length - 1; j >= 0; j--) {
    grid[i * width + j] = before[i] === after[j] ? 1 + grid[(i + 1) * width + j + 1]
      : Math.max(grid[(i + 1) * width + j], grid[i * width + j + 1]);
  }
  const lines: DiffLine[] = [];
  let i = 0, j = 0;
  while (i < before.length || j < after.length) {
    if (i < before.length && j < after.length && before[i] === after[j]) {
      lines.push({ kind: 'context', text: before[i], oldLine: ++i, newLine: ++j });
    } else if (i < before.length && (j === after.length || grid[(i + 1) * width + j] >= grid[i * width + j + 1])) {
      lines.push({ kind: 'remove', text: before[i], oldLine: ++i, newLine: null });
    } else { lines.push({ kind: 'add', text: after[j], oldLine: null, newLine: ++j }); }
  }
  return lines;
}

export function currentPatchCheck(hash: string | null, checks: { subject_hash: string; result: { passed: boolean } }[]): 'passed' | 'failed' | 'mixed' | 'missing' {
  if (!hash) return 'missing';
  const matching = checks.filter(c => c.subject_hash === hash);
  if (!matching.length) return 'missing';
  const passed = matching.some(c => c.result.passed);
  const failed = matching.some(c => !c.result.passed);
  return passed && failed ? 'mixed' : passed ? 'passed' : 'failed';
}
