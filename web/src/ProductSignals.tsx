import { useState } from 'react';
import { ArrowRight, Layers3, MessageSquare, ShieldCheck, Users } from 'lucide-react';

type Signal = { need_key: string; your_tenant_request_count: number; affected_tenant_count: number | null;
  decision: string | null; observed_granted_reads: number | null; usage_scope: string; note: string };
const labels: Record<string, string> = { promote: 'Consider for the shared product', keep_separate: 'Keep customer-specific', retire: 'Retire this variation' };

export function ProductSignals({ rows, canDecide, busy, rationales, setRationale, decide }: {
  rows: Signal[]; canDecide: boolean; busy: boolean; rationales: Record<string, string>;
  setRationale: (key: string, value: string) => void; decide: (key: string, decision: string) => void;
}) {
  const [choices, setChoices] = useState<Record<string, string>>({});
  return <section className="signals-view" aria-label="Product signals">
    <div className="signals-intro"><span className="starter-icon lilac"><Layers3 size={25}/></span><div><h2>Find the shared need.</h2><p>See what customers keep asking for. Decide what belongs in your product.</p></div></div>
    {!rows.length && <div className="panel empty-state"><MessageSquare size={30}/><h3>No repeated needs yet</h3><p>Saved requests will help you see the patterns.</p></div>}
    {rows.map(row => <article className="panel signal-card" key={row.need_key}>
      <div className="panel-heading"><h3>{row.need_key === 'pdf-export' ? 'PDF export' : row.need_key === 'temporary-project-view' ? 'Temporary project access' : 'Customer change'}</h3>
        <span className="pill neutral">{row.decision ? labels[row.decision] || 'Decision recorded' : 'For review'}</span></div>
      <div className="signal-metrics"><div><MessageSquare size={19}/><strong>{row.your_tenant_request_count}</strong><span>Assigned-team requests</span></div>
        {row.affected_tenant_count !== null && <div><Users size={19}/><strong>{row.affected_tenant_count}</strong><span>Customer workspaces</span></div>}
        {row.observed_granted_reads !== null && <div><ShieldCheck size={19}/><strong>{row.observed_granted_reads}</strong><span>Granted read checks</span></div>}</div>
      <details><summary>What these numbers mean</summary><p className="tiny">{row.note}</p><p className="tiny">{row.usage_scope === 'all_tenants' ? 'Aggregate across workspaces.' : 'Your assigned teams only.'} Read checks can include retries. They do not measure distinct people or customer demand.</p><code>{row.need_key}</code></details>
      {canDecide && <form onSubmit={event => { event.preventDefault(); if (choices[row.need_key] && (rationales[row.need_key] || '').trim().length >= 10 && !busy) decide(row.need_key, choices[row.need_key]); }}>
        <label>Product decision<select required value={choices[row.need_key] || ''} onChange={event => setChoices(previous => ({ ...previous, [row.need_key]: event.target.value }))}><option value="" disabled>Choose a direction</option>{Object.entries(labels).map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select></label>
        {choices[row.need_key] && <><label>Why this direction?<textarea required minLength={10} maxLength={2000} rows={2} value={rationales[row.need_key] || ''} onChange={event => setRationale(row.need_key, event.target.value)}/></label>
          <button className="primary" disabled={busy || (rationales[row.need_key] || '').trim().length < 10}>Save decision<ArrowRight size={15}/></button><p className="tiny">Records your choice. Does not change or release the product.</p></>}
      </form>}
    </article>)}
  </section>;
}
