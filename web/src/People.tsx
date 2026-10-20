import { useEffect, useRef, useState } from 'react';
import { boundedResponse, type BoundedResponse } from './responseDeadline';

type Member = { id: string; role: string; enabled: boolean };
type Audit = { id: string; subject_id: string; action: string; created_at: string };

export function People({ request }: {
  request: <T>(path: string, options?: RequestInit) => Promise<T>;
}) {
  const [members, setMembers] = useState<Member[]>([]);
  const [audit, setAudit] = useState<Audit[]>([]);
  const [selection, setSelection] = useState<Member | null>(null);
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState('');
  const active = useRef<BoundedResponse<unknown> | null>(null);
  const mounted = useRef(false);
  const writing = useRef(false);
  const lifetime = useRef(0);
  async function wait<T>(path: string, options?: RequestInit): Promise<T> {
    const current = boundedResponse(signal => request<T>(path, { ...options, signal }));
    active.current = current;
    return current.promise;
  }
  async function refresh() {
    const version = lifetime.current;
    const rows = await wait<Member[]>('/v1/members');
    if (!mounted.current || version !== lifetime.current) return;
    const events = await wait<Audit[]>('/v1/members/audit');
    if (mounted.current && version === lifetime.current) { setMembers(rows); setAudit(events); setLoaded(true); }
  }
  useEffect(() => {
    mounted.current = true;
    let current = true;
    refresh()
      .catch(err => { if (current) setError(String(err)); });
    return () => { current = false; mounted.current = false; lifetime.current++; active.current?.cancel(); };
  }, []);
  async function change() {
    if (!selection || writing.current) return;
    writing.current = true;
    setBusy(true); setError('');
    try {
      await wait(`/v1/members/${encodeURIComponent(selection.id)}/access`, {
        method: 'POST', body: JSON.stringify({ enabled: !selection.enabled }),
      });
      if (!mounted.current) return;
      setSelection(null); await refresh();
    } catch (err) { if (mounted.current) setError(String(err)); }
    finally { writing.current = false; if (mounted.current) setBusy(false); }
  }
  return <section className="panel" aria-label="Workspace people">
    <h2>People and access</h2>
    <p className="muted">Manage identities in your workspace. Disabling a person ends their sessions. Re-enabling requires a fresh sign-in.</p>
    {error && <p role="alert" className="alert error">{error}</p>}
    {error && <button className="secondary" disabled={busy} onClick={() => { setError(''); void refresh().catch(err => setError(String(err))); }}>Refresh saved access</button>}
    <p role="status" aria-live="polite">{busy ? 'Saving access change…' : !loaded && !error ? 'Loading people…' : ''}</p>
    {members.map(member => <div className="convergence-card" key={member.id}>
      <div><h3>{member.id}</h3><p>{member.role} · {member.enabled ? 'Enabled' : 'Disabled'}</p></div>
      {['contractor', 'engineer', 'member'].includes(member.role) && <button className="secondary"
        disabled={busy} onClick={() => setSelection(member)}>{member.enabled ? 'Disable access' : 'Enable access'}</button>}
    </div>)}
    {selection && <div className="review-verdict" role="group" aria-label="Confirm account change">
      <h3>{selection.enabled ? 'Disable' : 'Enable'} {selection.id}?</h3>
      <p>{selection.enabled ? 'All current sessions and local tokens will stop working.' : 'Previous sessions remain revoked. This person must sign in again.'}</p>
      <div className="button-row"><button className="primary" disabled={busy} onClick={change}>Confirm {selection.enabled ? 'disable' : 'enable'}</button>
        <button className="secondary" disabled={busy} onClick={() => setSelection(null)}>Cancel</button></div>
    </div>}
    <h3>Recent identity changes</h3>
    {audit.length ? audit.map(event => <p key={event.id}>{event.subject_id} · {event.action.replaceAll('_', ' ')} · {new Date(event.created_at).toLocaleString()}</p>) : loaded && <p className="muted">No saved identity changes.</p>}
  </section>;
}
