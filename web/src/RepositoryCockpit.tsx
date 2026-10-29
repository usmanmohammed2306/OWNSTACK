import React, {useEffect, useState} from 'react';
import {repositoryCheckLabel} from './review';

export type RepositoryCheck = {
  id: string; state: string; patch_hash: string; context_hash: string; error_code: string | null;
  report: {passed: boolean; required_tests: string[]; observed_tests: Record<string, boolean>; diff?: string;
    upstream_passed?: boolean; customer_release?: {passed:boolean; status:string; assessments:{requirement_key:string;case_id:string;regression:boolean;candidate_passed:boolean}[]}} | null;
};
export type RepositoryReview = {
  binding: {case_id: string; title: string; source_url: string; base_commit: string};
  context_hash: string; verification_id: string | null; candidate_origin?: string;
  customer_release?: {requirement_ids:string[];requirements_sha256:string} | null;
  checks: RepositoryCheck[];
};
type Props = {
  item: {id: string; status: string; patch_hash: string | null; human_decision: string | null; current_checks_usable:boolean; request?:{project_id:string|null}; repository?: RepositoryReview | null};
  engineer: boolean;
  request: <T>(path: string, options?: RequestInit) => Promise<T>;
  refresh: (id: string, signal: AbortSignal) => Promise<void>;
};
type Case = {id: string; title: string};

export function RepositoryCockpit({item, engineer, request, refresh}: Props) {
  const [cases, setCases] = useState<Case[]>([]), [selected, setSelected] = useState('');
  const [code, setCode] = useState(''), [origin, setOrigin] = useState('model');
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [requirements,setRequirements]=useState<{id:string;project_id:string;state:string}[]>([]);
  const repository = item.repository;
  const current = repository?.checks.find(check => check.id === repository.verification_id);
  useEffect(() => {
    const controller = new AbortController();
    request<Case[]>('/v1/repository-cases', {signal: controller.signal})
      .then(rows => {if (!controller.signal.aborted) {setCases(rows); setSelected(rows[0]?.id || '');}})
      .catch(() => { /* Optional local capability stays hidden on other builds. */ });
    return () => controller.abort();
  }, [item.id]);
  useEffect(()=>{
    const controller=new AbortController();setRequirements([]);
    if(repository?.binding.case_id==='pallets__flask-4160') {
      request<{id:string;project_id:string;state:string}[]>('/v1/release/requirements',{signal:controller.signal})
        .then(rows=>{if(!controller.signal.aborted)setRequirements(rows.filter(r=>r.project_id===item.request?.project_id&&r.state==='approved'));})
        .catch(()=>{});
    }
    return ()=>controller.abort();
  },[item.id,item.request?.project_id,repository?.binding.case_id,repository?.customer_release?.requirements_sha256]);
  useEffect(() => {
    if (item.status !== 'checking' || !repository) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {await refresh(item.id, controller.signal);setError('');} catch (e) {
        if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'Could not refresh saved checks.');
      }
      if (!controller.signal.aborted) timer = setTimeout(poll, 750);
    };
    timer = setTimeout(poll, 500);
    return () => {controller.abort(); clearTimeout(timer);};
  }, [item.id, item.status, repository?.verification_id]);
  async function act(path: string, body?: unknown) {
    setBusy(true); setError('');
    try {
      await request(path, {method: 'POST', body: JSON.stringify(body)});
      await refresh(item.id, new AbortController().signal);
    } catch(e) {setError(e instanceof Error ? e.message : 'Could not save this action.');}
    finally {setBusy(false);}
  }
  async function loadExample() {
    if (!repository) return;
    setBusy(true); setError('');
    try {
      const result = await request<{patch: unknown}>(`/v1/repository-cases/${repository.binding.case_id}/example`);
      setCode(JSON.stringify(result.patch, null, 2)); setOrigin('model');
    } catch(e) {setError(e instanceof Error ? e.message : 'Could not load the saved example.');}
    finally {setBusy(false);}
  }
  if (!repository && (!engineer || !cases.length || item.status !== 'needs_engineer')) return null;
  if (!repository) return <details className="technical-disclosure"><summary>Check a repository change</summary>
    <label>Published case<select aria-label="Repository case" value={selected} onChange={e => setSelected(e.target.value)}>
      {cases.map(row => <option key={row.id} value={row.id}>{row.title}</option>)}
    </select></label>
    <button className="secondary" disabled={busy || !selected} onClick={() => void act(`/v1/engineering/${item.id}/repository`, {case_id: selected})}>Use this case</button>
    {error && <p role="alert">{error}</p>}
  </details>;
  const ready = !item.human_decision && item.status !== 'checking';
  const passed = current?.report?.required_tests.filter(name => current.report?.observed_tests[name]).length;
  return <section className="repository-review" aria-label="Repository review">
    <a href={repository.binding.source_url} target="_blank" rel="noreferrer">{repository.binding.title}</a>
    <p className="tiny">Pinned source {repository.binding.base_commit.slice(0, 12)} · Local evaluation</p>
    {repository.binding.case_id==='pallets__flask-4160'&&<div aria-label="Customer release coverage">
      <p>{repository.customer_release?`${repository.customer_release.requirement_ids.length} approved customer requirements attached`:'Customer requirements are not attached'}</p>
      {engineer&&ready&&requirements.length>0&&<button className="secondary" disabled={busy} onClick={()=>void act(`/v1/engineering/${item.id}/release-assurance`,{requirement_ids:requirements.map(r=>r.id)})}>Use current approved requirements</button>}
      {current?.report?.customer_release&&<div role="status">
        <strong>Customer checks {current.report.customer_release.passed?'passed':current.report.customer_release.status==='failed'?'found a regression':'blocked'}</strong>
        <p className="tiny">Upstream issue tests {current.report.upstream_passed?'passed':'did not pass'} · Nothing deployed</p>
        {current.report.customer_release.assessments.some(a=>!a.candidate_passed)&&<ul>{current.report.customer_release.assessments.filter(a=>!a.candidate_passed).map(a=><li key={`${a.requirement_key}:${a.case_id}`}>{a.case_id.replaceAll('-',' ')}</li>)}</ul>}
      </div>}
    </div>}
    {current && <div role="status" aria-live="polite"><strong>{repositoryCheckLabel(current.state,item.current_checks_usable)}</strong>
      {current.report && <span> · {passed}/{current.report.required_tests.length} required checks</span>}
      {current.error_code && <p>{current.error_code.replaceAll('_', ' ').toLowerCase()}</p>}
    </div>}
    {current?.state==='passed'&&!item.current_checks_usable&&<p className="repository-stale-notice">This saved run does not verify the current change. Release handoff is unavailable.</p>}
    {current?.report?.diff && <details><summary>Review checked patch</summary><pre className="diff-lines" tabIndex={0} aria-label="Checked repository diff">{current.report.diff}</pre></details>}
    {engineer && ready && <details open={!item.patch_hash}><summary>Candidate code</summary>
      <p className="tiny">Supply bounded edits. The saved example uses no new AI call.</p>
      <button className="secondary" disabled={busy} onClick={() => void loadExample()}>Load saved test patch</button>
      <label>Candidate edits<textarea aria-label="Repository candidate edits" rows={10} spellCheck={false} value={code} onChange={e => setCode(e.target.value)}/></label>
      <label>Candidate source<select aria-label="Candidate source" value={origin} onChange={e => setOrigin(e.target.value)}><option value="model">AI-assisted or supplied model candidate</option><option value="human">I wrote this candidate</option></select></label>
      <button className="secondary" disabled={busy || !code.trim()} onClick={() => {
        try {const patch = JSON.parse(code); void act(`/v1/engineering/${item.id}/manual-patch`, {patch, candidate_origin: origin});}
        catch {setError('Enter valid JSON edits before saving.');}
      }}>Save candidate</button>
    </details>}
    {engineer && !item.human_decision && <div className="button-row">
      {item.status === 'drafted' && <button className="primary" disabled={busy} onClick={() => void act(`/v1/engineering/${item.id}/verify`)}>Check candidate</button>}
      {current && ['failed','blocked','timed_out','canceled','superseded'].includes(current.state) && <button className="secondary" disabled={busy} onClick={() => void act(`/v1/engineering/${item.id}/repository/retry`, {verification_id: current.id})}>Retry these checks</button>}
      {current && ['queued','running','recovering','recovery_blocked'].includes(current.state) && <button className="secondary" disabled={busy} onClick={() => void act(`/v1/engineering/${item.id}/repository/cancel`, {verification_id: current.id})}>Stop accepting this attempt</button>}
    </div>}
    {error && <p role="alert">{error}</p>}
    <details><summary>Check history ({repository.checks.length})</summary>{repository.checks.map(check => <div key={check.id}>
      <p>{check.state} · {check.patch_hash.slice(0, 10)}{check.id === repository.verification_id ? ' · selected attempt' : ' · historical'}</p>
      {check.error_code && <p>{check.error_code.replaceAll('_',' ').toLowerCase()}</p>}
      {check.report && <><small>{check.report.required_tests.filter(name => check.report?.observed_tests[name]).length}/{check.report.required_tests.length} required checks passed</small>
        {check.report.customer_release&&<p className="tiny">Customer checks {check.report.customer_release.passed?'passed':check.report.customer_release.status==='failed'?'found a regression':'blocked'} · {check.report.customer_release.assessments.filter(a=>a.regression).length} regressions</p>}
        {check.report.required_tests.some(name => !check.report?.observed_tests[name]) && <details><summary>Unpassed required checks</summary><ul>{check.report.required_tests.filter(name => !check.report?.observed_tests[name]).map(name => <li key={name}><code>{name}</code></li>)}</ul></details>}
      </>}
    </div>)}</details>
  </section>;
}
