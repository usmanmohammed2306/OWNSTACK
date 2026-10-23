import { useEffect, useRef, useState } from 'react';
import { boundedResponse, type BoundedResponse } from './responseDeadline';
import { validAccessForecast, type AccessForecast } from './accessForecast';

type AccessSnapshot = {
  tenant_id: string; project_id: string; viewer_id: string; viewer_role: string;
  allowed: boolean; reason: string; variation_id: string | null; evaluated_at: string;
  diagnostic_only: boolean; notice: string; forecast: AccessForecast;
};
const reasons: Record<string, string> = {
  account_disabled: 'The account is disabled. Existing grants cannot bypass sign-in.',
  role_access: 'The same-tenant role permits this read; no temporary grant is needed.',
  active_grant: 'A matching, active temporary grant permits this read at the checked time.',
  no_current_access: 'No role or currently valid grant permits this read. Grants may be missing, expired, revoked or outside scope.',
};

/** Read-only troubleshooting. Never use this snapshot to authorize a document read. */
export function AccessInspector({ tenant, project, initialViewer, request }: {
  tenant: string; project: string; initialViewer: string;
  request: <T>(path: string, options?: RequestInit) => Promise<T>;
}) {
  const [viewer, setViewer] = useState(initialViewer);
  const [snapshot, setSnapshot] = useState<AccessSnapshot | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const generation = useRef(0);
  const pending = useRef<BoundedResponse<AccessSnapshot> | null>(null);
  useEffect(() => () => { generation.current++; pending.current?.cancel(); }, []);
  function changeViewer(value: string) {
    generation.current++; pending.current?.cancel(); pending.current = null;
    setViewer(value); setSnapshot(null); setError(''); setBusy(false);
  }
  async function inspect() {
    if (pending.current || !viewer.trim()) return;
    const target = viewer.trim(), version = ++generation.current;
    setSnapshot(null); setError(''); setBusy(true);
    const operation = boundedResponse(signal => request<AccessSnapshot>(
      `/v1/host/projects/${encodeURIComponent(project)}/access-review?viewer_id=${encodeURIComponent(target)}`, { signal }));
    pending.current = operation;
    try {
      const result = await operation.promise;
      if (version !== generation.current) return;
      if (result.tenant_id !== tenant || result.project_id !== project || result.viewer_id !== target
          || result.diagnostic_only !== true || typeof result.allowed !== 'boolean'
          || !validAccessForecast(result.forecast, result.evaluated_at, result.allowed)) {
        throw new Error('Response did not match the inspected identity. Check again.');
      }
      setSnapshot(result);
    } catch (err) { if (version === generation.current) setError(String(err)); }
    finally {
      if (version === generation.current) { pending.current = null; setBusy(false); }
    }
  }
  return <div className="manual-editor" aria-label="Read-only access inspector">
    <h3>Why can they access this?</h3>
    <p className="tiny">Check an identity in your tenant without signing in as them. This does not read documents or grant access.</p>
    <label>Viewer identity<input value={viewer} maxLength={200} onChange={event => changeViewer(event.target.value)}
      autoComplete="off" spellCheck={false}/></label>
    <button className="secondary" disabled={busy || !viewer.trim()} onClick={inspect}>
      {busy ? 'Checking host policy…' : 'Check access'}
    </button>
    {busy && <p role="status">Waiting for the host policy snapshot…</p>}
    {error && <p role="alert" className="alert error">{error}</p>}
    {snapshot && <div role="status" aria-live="polite">
      <p><span className={'pill ' + (snapshot.allowed ? 'good' : 'bad')}>{snapshot.allowed ? 'Allowed at check time' : 'Denied at check time'}</span></p>
      <p>{reasons[snapshot.reason] || 'Inspect the host policy for this identity.'}</p>
      <p className="tiny">{snapshot.viewer_id} · {project} · {new Date(snapshot.evaluated_at).toLocaleString()}
        {snapshot.variation_id ? ` · grant ${snapshot.variation_id}` : ''}</p>
      <p className="tiny">{snapshot.notice} Recheck after changing grants or accounts.</p>
      <div className="manual-editor" aria-label="Conditional access forecast">
        <h4>When will access change?</h4>
        {snapshot.forecast.status === 'predicted_change' && snapshot.forecast.next_change && <p>
          Predicted to become <strong>{snapshot.forecast.next_change.allowed ? 'allowed' : 'denied'}</strong> at{' '}
          <time dateTime={snapshot.forecast.next_change.at}>{new Date(snapshot.forecast.next_change.at).toLocaleString()}</time>.
        </p>}
        {snapshot.forecast.status === 'no_scheduled_change' && <p>No scheduled access change through{' '}
          <time dateTime={snapshot.forecast.through}>{new Date(snapshot.forecast.through).toLocaleString()}</time>.
          {' '}This does not mean access is permanent.</p>}
        {snapshot.forecast.status === 'unavailable' && <p>Forecast unavailable. Do not infer an expiry from an incomplete schedule.</p>}
        <p className="tiny">{snapshot.forecast.notice}</p>
      </div>
    </div>}
  </div>;
}
