import { useEffect, useRef, useState } from 'react';
import { PatchDiff } from './PatchDiff';
import { submissionForIntent, type PendingSubmission, type SessionIdentity } from './responseIdentity';
import { boundedResponse, type BoundedResponse } from './responseDeadline';
import { repairCandidateToReview, repairStartBlock, sameRepairReview, sameRepairScope,
  savedRepairRowsMatch, repairProgressText, type RepairReview, type RepairRun, type RepairScope } from './repairView';

type Props = {
  session: SessionIdentity & { ai_mode: string };
  item: { id: string; status: string; patch_hash: string | null; human_decision: string | null };
  remainingCalls: number | null | undefined;
  parentBusy: boolean;
  request: <T>(path: string, options?: RequestInit) => Promise<T>;
  onChanged: (itemId: string, signal: AbortSignal) => Promise<void>;
};

export function BoundedRepair(props: Props) {
  const { session, item, remainingCalls, parentBusy } = props;
  const scope: RepairScope = { session, itemId: item.id };
  const scopeRef = useRef(scope);
  scopeRef.current = scope;
  const propsRef = useRef(props);
  propsRef.current = props;
  const mounted = useRef(false);
  const lifetime = useRef(0);
  const readVersion = useRef(0);
  const readInFlight = useRef<number | null>(null);
  const activeRead = useRef<{ version: number; wait: BoundedResponse<RepairRun[]> } | null>(null);
  const activeMutation = useRef<BoundedResponse<unknown> | null>(null);
  const writing = useRef(false);
  const pending = useRef<{ scope: RepairScope; submission: PendingSubmission } | null>(null);
  const [record, setRecord] = useState<{ scope: RepairScope; runs: RepairRun[] } | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState('');
  const [loading, setLoading] = useState(false);
  const [acknowledged, setAcknowledged] = useState<RepairReview | null>(null);
  const isCurrent = (started: RepairScope) => mounted.current && sameRepairScope(started, scopeRef.current);
  const runs = sameRepairScope(record?.scope || null, scope) ? record!.runs : [];
  const loaded = sameRepairScope(record?.scope || null, scope);

  async function load(force = false) {
    if (!mounted.current || writing.current || (readInFlight.current !== null && !force)) return;
    const started = scopeRef.current;
    const version = ++readVersion.current;
    if (force) activeRead.current?.wait.cancel();
    readInFlight.current = version;
    if (force) setLoading(true);
    try {
      const transport = propsRef.current.request;
      const wait = boundedResponse(signal => transport<RepairRun[]>(`/v1/engineering/${started.itemId}/repairs`, { signal }));
      activeRead.current = { version, wait };
      const rows = await wait.promise;
      if (!isCurrent(started) || version !== readVersion.current) return;
      if (!savedRepairRowsMatch(rows, started.itemId)) throw new Error('Saved repair identity mismatch. Reload the work item.');
      setRecord({ scope: started, runs: rows });
      setError('');
    } catch (failure) {
      if (isCurrent(started) && version === readVersion.current) setError(`Saved repair refresh failed: ${String(failure)}. Existing saved results were not replaced. Retry the saved-state read.`);
    } finally {
      if (activeRead.current?.version === version) activeRead.current = null;
      if (readInFlight.current === version) readInFlight.current = null;
      if (isCurrent(started) && version === readVersion.current) setLoading(false);
    }
  }

  useEffect(() => {
    mounted.current = true;
    setRecord(null); setError(''); setNotice(''); setBusy(''); setAcknowledged(null);
    pending.current = null; writing.current = false; readInFlight.current = null;
    void load(true);
    // Reading persisted state never launches inference. It also observes other engineers.
    const timer = setInterval(() => { void load(); }, 3000);
    return () => {
      mounted.current = false; lifetime.current++; readVersion.current++; clearInterval(timer);
      activeRead.current?.wait.cancel(); activeRead.current = null;
      activeMutation.current?.cancel(); activeMutation.current = null;
    };
  }, [item.id, session.user_id, session.tenant_id, session.csrf_token, session.role]);

  const block = repairStartBlock({ role: session.role, mode: session.ai_mode, remainingCalls,
    itemStatus: item.status, patchHash: item.patch_hash, humanDecision: item.human_decision, runs });

  async function mutate(path: string, options: RequestInit, label: string, success: string) {
    if (writing.current || parentBusy) return;
    const started = scopeRef.current;
    const startedLifetime = lifetime.current;
    const stillCurrent = () => isCurrent(started) && startedLifetime === lifetime.current;
    const activeProps = propsRef.current;
    writing.current = true; readVersion.current++; readInFlight.current = null;
    activeRead.current?.wait.cancel(); activeRead.current = null;
    setBusy(label); setLoading(false); setError(''); setNotice('');
    let confirmed = false;
    try {
      const wait = boundedResponse(signal => activeProps.request<RepairRun>(path, { ...options, signal }));
      activeMutation.current = wait;
      const saved = await wait.promise;
      if (!stillCurrent()) return;
      if (saved.item_id !== started.itemId) throw new Error('Repair response did not match this work item.');
      confirmed = true;
      setRecord(previous => ({ scope: started, runs: [saved, ...(sameRepairScope(previous?.scope || null, started)
        ? previous!.runs.filter(run => run.id !== saved.id) : [])] }));
      pending.current = null;
      setAcknowledged(null); setNotice(success);
      setBusy('Repair action saved. Refreshing the work item…');
      const refreshWait = boundedResponse(signal => activeProps.onChanged(started.itemId, signal));
      activeMutation.current = refreshWait;
      await refreshWait.promise;
    } catch (failure) {
      if (stillCurrent()) setError(confirmed
        ? `Repair action was saved, but the work-item refresh failed: ${String(failure)}. Refresh the work item.`
        : `${label} was not confirmed: ${String(failure)}. Refresh saved state before retrying.`);
    } finally {
      if (stillCurrent()) { activeMutation.current = null; writing.current = false; setBusy(''); }
    }
  }

  async function start() {
    if (block || !loaded || !item.patch_hash || error) return;
    const body = JSON.stringify({ patch_hash: item.patch_hash, max_attempts: 2 });
    const intent = JSON.stringify({ itemId: item.id, body });
    const previous = sameRepairScope(pending.current?.scope || null, scope) ? pending.current!.submission : null;
    const submission = submissionForIntent(previous, intent, () => crypto.randomUUID());
    pending.current = { scope, submission };
    await mutate(`/v1/engineering/${item.id}/repairs`, { method: 'POST',
      headers: { 'Idempotency-Key': submission.key }, body }, 'Start bounded repair',
      'Repair saved. The worker owns progress. At most two candidates; nothing is deployed.');
  }

  return <section className="check-result" aria-labelledby="bounded-repair-title">
    <div className="proposal-head"><h3 id="bounded-repair-title">Bounded repair</h3><span className="pill neutral">Up to 2 attempts · no deployment</span></div>
    <p className="tiny">A model may propose corrections to the failed patch. Independent checks can reject them. Adopting a candidate only selects it for your separate release review.</p>
    {block && <p className="tiny">{block}</p>}
    {session.ai_mode === 'fixture' && <p className="tiny">Synthetic fixture mode. These are not live model results.</p>}
    <div className="button-row">
      <button className="secondary" onClick={() => void start()} disabled={!!block || !loaded || !!error || !!busy || parentBusy}>Start bounded repair</button>
      <button className="secondary" onClick={() => void load(true)} disabled={!!busy}>{loading ? 'Retry saved-state read' : 'Refresh saved repairs'}</button>
    </div>
    <p className="tiny" role="status" aria-live="polite">{busy || (loading ? 'Reading saved repair state…' : [notice, loaded ? repairProgressText(runs) : 'Saved repair state has not loaded.'].filter(Boolean).join(' '))}</p>
    {error && <p role="alert">{error} Existing results below may be stale.</p>}
    {runs.map(run => {
      const candidate = repairCandidateToReview(run);
      const review: RepairReview | null = candidate ? { ...scope, runId: run.id, attemptId: candidate.id, patchHash: candidate.candidate_hash! } : null;
      const canMutate = session.role === 'engineer' && !busy && !parentBusy && !error && !item.human_decision;
      return <div className="repair-run" key={run.id}>
        <div className="divider"/>
        <div className="proposal-head"><h4>Run {run.id.slice(0, 8)}</h4><span className={'pill ' + (run.state === 'awaiting_review' ? 'good' : 'neutral')}>{run.state.replaceAll('_', ' ')}</span></div>
        <p className="tiny">{run.configuration.mode === 'fixture' ? 'SYNTHETIC, NOT LIVE' : 'Saved provider-configured run, not a new inference claim'} · {run.configuration.model} · {run.attempts.length}/{run.max_attempts} attempts recorded</p>
        {run.workflow?.last_phase && <details><summary>Saved workflow evidence · {run.workflow.engine === 'langgraph' ? 'LangGraph' : 'Sequential comparator'}</summary>
          <p className="tiny">The database owns saved state. Parallel checks are not listed in wall-clock order. Reading this evidence runs no graph or inference.</p>
          <p>Last phase: {run.workflow.last_phase.phase}. Result accepted into the ledger: {run.workflow.last_phase.accepted ? 'yes' : 'no'}.</p>
          <ul>{run.workflow.last_phase.nodes.map((node, index) => <li key={`${index}:${node}`}>{node.replaceAll('_', ' ')}</li>)}</ul>
          {run.workflow.last_phase.reviews.map(review => <p key={review.role}>{review.role.replaceAll('_', ' ')}: {review.passed ? 'passed' : 'rejected'} · {review.code}</p>)}
          <p className="tiny">Candidate adoption and release still require separate human decisions.</p>
        </details>}
        <div className="hash-line"><span>ORIGINAL FAILED PATCH</span><code>{run.original_patch_hash}</code></div>
        {run.error_code && <p role="status">Run outcome: {run.error_code}</p>}
        {run.attempts.map(attempt => <div className="check-result" key={attempt.id}>
          <div className="proposal-head"><strong>Attempt {attempt.number}</strong><span className={'pill ' + (attempt.state === 'passed' ? 'good' : ['failed', 'timed_out', 'discarded'].includes(attempt.state) ? 'bad' : 'neutral')}>{attempt.state.replaceAll('_', ' ')}</span></div>
          <p className="tiny">Model: {attempt.model_id} · Local deadline: {new Date(attempt.deadline_at).toLocaleString()}</p>
          {attempt.error_code && <p>Attempt outcome: {attempt.error_code}</p>}
          {attempt.checks && <><p className="tiny">{attempt.checks.checks_completed ?? 'Unknown'} / {attempt.checks.checks_expected ?? 'unknown'} case checks completed · {attempt.checks.runner || 'Runner not reported'} · {attempt.checks.passed ? 'Checks passed, not a security guarantee' : 'No passing verdict'}</p>
            <details><summary>Independent check evidence</summary><pre>{JSON.stringify(attempt.checks, null, 2)}</pre></details></>}
          {attempt.usage && <p className="tiny">Recorded latency: {attempt.usage.latency_ms == null ? 'unknown' : `${attempt.usage.latency_ms} ms`} · Input tokens: {attempt.usage.input_tokens ?? 'unknown'} · Output tokens: {attempt.usage.output_tokens ?? 'unknown'}</p>}
          {attempt.candidate && attempt.candidate_hash && <details open={candidate?.id === attempt.id}>
            <summary>Review exact candidate {attempt.candidate_hash.slice(0, 12)}</summary>
            <div className="hash-line"><span>EXACT CANDIDATE HASH</span><code>{attempt.candidate_hash}</code></div>
            {attempt.candidate.edits.map(edit => <PatchDiff key={`${attempt.id}:${attempt.candidate_hash}:${edit.path}`} path={edit.path} before={edit.old} after={edit.new}/>)}
          </details>}
        </div>)}
        {review && <><label className="approval-ack"><input type="checkbox" checked={sameRepairReview(acknowledged, review)} onChange={event => setAcknowledged(event.target.checked ? review : null)} disabled={!canMutate}/> I reviewed the exact candidate above. Adoption does not accept or deploy it.</label>
          <button className="secondary" disabled={!canMutate || !sameRepairReview(acknowledged, review)} onClick={() => {
            if (!sameRepairReview(acknowledged, review)) return;
            void mutate(`/v1/repairs/${run.id}/adopt`, { method: 'POST', body: JSON.stringify({ patch_hash: review.patchHash }) },
              'Adopt exact candidate', 'Candidate adopted for separate engineer review. It is not accepted, merged or deployed.');
          }}>Adopt exact candidate for review</button></>}
        {['running', 'awaiting_review'].includes(run.state) && <div className="button-row"><button className="secondary" disabled={!canMutate} onClick={() => void mutate(`/v1/repairs/${run.id}/take-over`, { method: 'POST' },
          'Take over repair', 'Local repair stopped. Remote inference cancellation is unverified. Continue with the manual patch path.')}>Stop repair and continue manually</button></div>}
      </div>;
    })}
    <p className="tiny">Local stop or timeout never proves remote inference stopped. Earlier failed candidates remain saved. Server role, hash, source and budget checks remain authoritative.</p>
  </section>;
}
