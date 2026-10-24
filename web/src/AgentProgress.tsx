import { useEffect, useRef, useState } from 'react';
import { openProgress, type ProgressScope, type ProgressSnapshot } from './progressStream';

/** Parent keys this view by session, request revision and attempt identity. */
export function AgentProgress({ scope, request }: {
  scope: ProgressScope; request: (path: string, signal: AbortSignal) => Promise<Response>;
}) {
  const [snapshot, setSnapshot] = useState<ProgressSnapshot | null>(null);
  const [notice, setNotice] = useState('Connecting to saved progress…');
  const [connected, setConnected] = useState(false);
  const [reconnect, setReconnect] = useState(0);
  const cancel = useRef<(() => void) | null>(null);
  const transport = useRef(request); transport.current = request;
  const { tenant_id, request_id, project_id, attempt_id, revision } = scope;
  useEffect(() => {
    let live = true;
    setSnapshot(null); setNotice('Connecting to saved progress…'); setConnected(true);
    const query = new URLSearchParams({ project_id, attempt_id, revision: String(revision) });
    const wait = openProgress(signal => transport.current(`/v1/requests/${encodeURIComponent(request_id)}/progress?${query}`, signal),
      { tenant_id, request_id, project_id, attempt_id, revision }, value => {
        if (live) { setSnapshot(value); setNotice('Saved progress received.'); }
      });
    cancel.current = wait.cancel;
    wait.promise.then(code => {
      if (live) {
        if (code !== 'complete' && code !== 'wait_limit') setSnapshot(null);
        setNotice(code === 'complete' ? 'Saved attempt finished. No automatic approval or deployment.'
          : code === 'wait_limit' ? 'Progress window ended. Last saved snapshot below; reconnect without restarting work.'
          : 'Scope or session changed, or progress became unavailable. Refresh saved state.');
      }
    }).catch(() => {
      if (live) {
        setSnapshot(null);
        setNotice('Stopped waiting locally or progress was invalid. Remote inference cancellation is unverified. Read saved state.');
      }
    }).finally(() => { if (live) setConnected(false); });
    return () => { live = false; wait.cancel(); cancel.current = null; };
  }, [tenant_id, request_id, project_id, attempt_id, revision, reconnect]);
  return <section className="proposal" aria-label="Agent progress">
    <h4>Agent progress</h4>
    <p role="status" aria-live="polite">{notice}</p>
    {snapshot && <>
      <p>{snapshot.source === 'fixture_stream' ? 'Synthetic stream fixture, not a live model.'
        : snapshot.source === 'provider_stream' ? 'Provider-stream adapter progress. This feed contains no raw model tokens.'
        : 'Saved status only. No native model-stream evidence for this attempt.'}</p>
      <p><strong>{snapshot.state}</strong> · {snapshot.phase} · {snapshot.received_bytes} buffered bytes · {snapshot.deltas} content/argument deltas</p>
      {snapshot.deadline_elapsed && !snapshot.terminal && <p>Local deadline elapsed. Saved terminal state has not yet been recorded.</p>}
      {snapshot.response && <p>Validated saved response: <strong>{snapshot.response.route}</strong>. Review its exact proposal below.</p>}
    </>}
    <p className="muted">Partial JSON, tool arguments and reasoning stay off this feed. Schema-valid proposals still require host policy and exact human approval.</p>
    <button className="secondary" onClick={() => connected ? cancel.current?.() : setReconnect(value => value + 1)}>
      {connected ? 'Stop watching locally' : 'Reconnect to saved progress'}
    </button>
  </section>;
}
