import { useEffect, useRef, useState } from 'react';
import { boundedResponse, type BoundedResponse } from './responseDeadline';
type Spec = { key: string; title: string; description: string; filters: string[]; required: string[] };
type Snapshot = { report: string; tenant_id: string; scope: Record<string, string>; evaluated_at: string;
  items: Record<string, unknown>[]; truncated: boolean; notice: string };

/** Reports explain saved state. They never perform the operations they describe. */
export function Assurance({ tenant, request }: { tenant: string; request: <T>(path: string, options?: RequestInit) => Promise<T> }) {
  const [specs, setSpecs] = useState<Spec[]>([]), [selected, setSelected] = useState('');
  const [scope, setScope] = useState<Record<string, string>>({});
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null), [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const generation = useRef(0), pending = useRef<BoundedResponse<unknown> | null>(null);
  const spec = specs.find(item => item.key === selected);
  useEffect(() => {
    const version = ++generation.current;
    const operation = boundedResponse(signal => request<Spec[]>('/v1/assurance/catalogue', { signal }));
    pending.current = operation; setBusy(true);
    operation.promise.then(data => {
      if (version !== generation.current) return;
      if (!Array.isArray(data) || data.some(s => typeof s.key !== 'string' || typeof s.title !== 'string'
          || !Array.isArray(s.filters) || !Array.isArray(s.required))) throw new Error('Invalid report catalogue');
      setSpecs(data); setSelected(data[0]?.key || '');
    }).catch(err => { if (version === generation.current) setError(String(err)); })
      .finally(() => { if (version === generation.current) { pending.current = null; setBusy(false); } });
    return () => { generation.current++; operation.cancel(); pending.current?.cancel(); };
  }, []);
  function clear() { generation.current++; pending.current?.cancel(); pending.current = null; setSnapshot(null); setError(''); setBusy(false); }
  async function inspect() {
    if (!spec || pending.current) return;
    const params = Object.fromEntries(spec.filters.filter(key => scope[key]?.trim()).map(key => [key, scope[key].trim()]));
    if (spec.required.some(key => !params[key])) { setError('Complete the required scope fields.'); return; }
    const version = ++generation.current;
    setSnapshot(null); setError(''); setBusy(true);
    const operation = boundedResponse(signal => request<Snapshot>(`/v1/assurance/${encodeURIComponent(spec.key)}?${new URLSearchParams(params)}`, { signal }));
    pending.current = operation;
    try {
      const result = await operation.promise;
      if (version !== generation.current) return;
      if (result.tenant_id !== tenant || result.report !== spec.key || !Array.isArray(result.items)
          || result.items.some(item => !item || typeof item !== 'object' || Array.isArray(item))
          || typeof result.notice !== 'string' || typeof result.truncated !== 'boolean'
          || !Number.isFinite(Date.parse(result.evaluated_at)) || !result.scope || typeof result.scope !== 'object'
          || JSON.stringify(Object.entries(result.scope).sort()) !== JSON.stringify(Object.entries(params).sort())) {
        throw new Error('Report did not match the selected tenant and scope.');
      }
      setSnapshot(result);
    } catch (err) { if (version === generation.current) setError(String(err)); }
    finally { if (version === generation.current) { pending.current = null; setBusy(false); } }
  }
  const columns = snapshot?.items.length ? [...new Set(snapshot.items.flatMap(item => Object.keys(item)))] : [];
  return <section className="panel span-three"><h2>Assurance workbench</h2>
    <p>Inspect approval, access, evidence and recovery records. These reports change nothing and never run AI.</p>
    <label>Diagnostic report<select value={selected} onChange={event => { clear(); setSelected(event.target.value); setScope({}); }}>
      {specs.map(item => <option key={item.key} value={item.key}>{item.title}</option>)}</select></label>
    <p className="tiny">{spec?.description}</p>
    {spec?.filters.map(key => <label key={key}>{key.replaceAll('_', ' ')}{spec.required.includes(key) ? ' (required)' : ' (optional)'}
      <input value={scope[key] || ''} maxLength={200} onChange={event => { clear(); setScope(old => ({ ...old, [key]: event.target.value })); }}/></label>)}
    <button className="secondary" disabled={busy || !spec} onClick={inspect}>{busy ? 'Reading saved records…' : 'Run read-only report'}</button>
    {busy && <p role="status">Waiting for a bounded report…</p>}
    {error && <p role="alert" className="alert error">{error}</p>}
    {snapshot && <div role="status"><p>Checked {new Date(snapshot.evaluated_at).toLocaleString()} · {snapshot.items.length} returned rows</p>
      {snapshot.truncated && <p className="alert notice">Source-row limit reached. This is not a complete audit.</p>}
      <p className="tiny">{snapshot.notice}</p>
      {snapshot.items.length ? <div style={{ overflowX: 'auto' }}><table><thead><tr>{columns.map(key => <th key={key} scope="col">{key.replaceAll('_', ' ')}</th>)}</tr></thead>
        <tbody>{snapshot.items.map((item, i) => <tr key={i}>{columns.map(key => <td key={key}>
          {item[key] == null ? 'Not recorded' : typeof item[key] === 'object' ? JSON.stringify(item[key]) : String(item[key])}</td>)}</tr>)}</tbody></table></div>
        : <p>No matching findings in the checked rows. This is not a clean bill of health.</p>}</div>}
  </section>;
}
