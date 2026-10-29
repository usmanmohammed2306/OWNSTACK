import { useEffect, useRef, useState } from 'react';
import { SearchCheck, Check, ArrowRight, Layers3, RefreshCw, FileText, Route } from 'lucide-react';
import { boundedResponse, type BoundedResponse } from './responseDeadline';
import { handoffLabel, investigationMatches, type InvestigationRun, type InvestigationScope } from './investigationView';
import { agentPresentation } from './agentPresentation';

/** Read saved state on mount. Only the explicit user action can launch inference. */
export function AgentInvestigation({ scope, mode, remainingCalls, request, onPrepare, preparing, allowPrepare, prepared, feature }: {
  scope: InvestigationScope; mode: string; remainingCalls: number | null | undefined;
  request: <T>(path: string, options?: RequestInit) => Promise<T>;
  onPrepare: () => void; preparing: boolean; allowPrepare: boolean; prepared: boolean;
  feature: boolean;
}) {
  const [run, setRun] = useState<InvestigationRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [loaded, setLoaded] = useState(false);
  const mounted = useRef(false);
  const transport = useRef(request); transport.current = request;
  const active = useRef<BoundedResponse<unknown> | null>(null);
  const writing = useRef(false);
  const readId = useRef(0);
  const key = useRef(crypto.randomUUID());
  const live = mode === 'nebius';
  const capped = live && (remainingCalls == null || remainingCalls <= 0);

  async function read() {
    if (writing.current) return;
    const version = ++readId.current;
    active.current?.cancel();
    const wait = boundedResponse(signal => transport.current<unknown[]>(`/v1/requests/${encodeURIComponent(scope.request)}/investigations`, { signal }));
    active.current = wait;
    try {
      const rows = await wait.promise;
      if (!mounted.current || version !== readId.current) return;
      // Old revisions remain in history, not on this request's active card.
      const current = rows.filter(row => investigationMatches(row, scope));
      setRun(current[0] as InvestigationRun || null); setLoaded(true); setError('');
    } catch {
      if (mounted.current && version === readId.current) setError('Saved investigation unavailable. Refresh to try again.');
    } finally {
      if (active.current === wait) active.current = null;
    }
  }
  useEffect(() => {
    mounted.current = true;
    void read();
    return () => { mounted.current = false; readId.current++; active.current?.cancel(); };
  }, [scope.tenant, scope.request, scope.revision]);

  async function investigate() {
    if (writing.current || capped || !live || !loaded) return;
    writing.current = true; readId.current++; active.current?.cancel(); setBusy(true); setError('');
    async function send(path: string, body: object, headers?: HeadersInit) {
      const wait = boundedResponse(signal => transport.current<unknown>(path, {
        method: 'POST', headers, body: JSON.stringify(body), signal,
      }), 135_000);
      active.current = wait;
      const result = await wait.promise;
      if (!investigationMatches(result, scope)) throw new Error('Investigation scope mismatch');
      if (mounted.current) setRun(result);
      return result;
    }
    try {
      let next = run && ['ready', 'running'].includes(run.state) ? run : await send(`/v1/requests/${encodeURIComponent(scope.request)}/investigations`,
        { revision: scope.revision }, { 'Idempotency-Key': key.current });
      if (['failed', 'stopped'].includes(next.state)) {
        next = await send(`/v1/investigations/${encodeURIComponent(next.id)}/retry`, { expected_version: next.version });
      }
      // Each model call still crosses its own durable reservation/lease boundary.
      // Mount never starts work; the user's action drives a bounded loop.
      const limit = Math.min(4, remainingCalls || 0);
      for (let index = 0; index < limit; index++) {
        if (!mounted.current || !['ready', 'running'].includes(next.state)) break;
        next = await send(`/v1/investigations/${encodeURIComponent(next.id)}/step`, { expected_version: next.version });
        if (next.state === 'running') break;
      }
    } catch {
      if (mounted.current) setError('Stopped waiting locally. Read saved progress before retrying; remote cancellation is unverified.');
    } finally {
      writing.current = false; active.current = null;
      if (mounted.current) setBusy(false);
    }
  }
  const canContinue = !run || ['ready', 'running', 'failed', 'stopped', 'stale'].includes(run.state);
  const view = agentPresentation(run, live, capped, busy, feature);
  const icons = [FileText, SearchCheck, Route];
  return <section className="agent-card" aria-label="Change agent" aria-busy={busy}>
    <div className="agent-card-heading"><span className="agent-avatar"><Layers3 size={22}/></span><div>
      <h4>{!loaded && !error ? 'Loading the agent’s work…' : prepared && view.complete ? 'Review complete' : view.title}</h4></div>{run?.state === 'completed' && <span className="agent-saved">Saved</span>}</div>
    <p className="agent-description" role="status">{view.description}</p>
    <ol className="agent-map" aria-label="Investigation progress">{view.nodes.map((node, i) => {
      const Icon = icons[i];
      return <li className={node.done ? 'observed' : ''} key={node.id}><span className="agent-node">{node.done ? <Check size={19}/> : <Icon size={19}/>}</span>
        <strong>{node.label}</strong><span className="sr-only">{node.done ? 'complete' : 'not completed'}</span></li>;
    })}</ol>
    {run?.source === 'offline_policy' && <p className="tiny">Saved deterministic baseline. This is not an AI result.</p>}
    <div className="agent-next">
      {canContinue && <button className="primary" disabled={busy || capped || !live || !loaded || preparing} onClick={() => void investigate()}>
        {busy ? 'Investigating…' : !live ? 'Agent unavailable' : capped ? 'Usage limit reached' : run ? 'Continue review' : 'Start agent'} <ArrowRight size={15}/>
      </button>}
      {view.complete && run?.result?.handoff !== 'clarify_request' && allowPrepare && <button className="primary" disabled={preparing || capped || !live} onClick={onPrepare}>{preparing ? 'Preparing…' : !live ? 'Agent unavailable' : capped ? 'Usage limit reached' : feature ? 'Prepare code review' : 'Prepare access preview'}<ArrowRight size={15}/></button>}
    </div>
    {error && <p role="alert" className="alert error">{error}</p>}
    <details className="agent-details"><summary>View activity</summary>
      <p className="tiny">{live ? 'Nemotron selects scoped read tools. Four model steps maximum. Each step is saved.' : 'AI is paused. Saved evidence remains available.'}</p>
      {run && <p className="tiny">{run.state === 'completed' ? handoffLabel(run.result) : `Saved status: ${run.state}. ${run.error_code || ''}`}</p>}
      {run?.result && <>
        {run.result.citations.map(citation => <div className="hash-line" key={citation.source}><span>{citation.source}</span><code>{citation.hash}</code></div>)}
        <p className="tiny">{run.limitation}</p>
        <p className="tiny">{run.source === 'nemotron' ? 'Untrusted model note' : 'Offline policy note'}: {run.result.untrusted_note}</p>
      </>}
      {busy ? <button className="secondary" onClick={() => active.current?.cancel()}>Stop waiting locally</button>
        : <button className="secondary" onClick={() => void read()}><RefreshCw size={14}/> Refresh saved status</button>}
      <p className="tiny">Stopping only cancels your local wait. Remote cancellation is unverified.</p>
    </details>
  </section>;
}
