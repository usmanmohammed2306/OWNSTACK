import { useEffect, useRef, useState } from 'react';
import { boundedResponse, type BoundedResponse } from './responseDeadline';
import { submissionForIntent, type PendingSubmission } from './responseIdentity';
import {CustomerRequirementForm} from './CustomerRequirementForm';
import { parseReleaseDraft, releaseCanApprove, releaseCanRead, releaseCanWrite, releaseCheckRows,
  releaseEvidenceIdentity, releaseFailedCases, releaseHash, releaseIntent, releaseRequirementIdentity,
  releaseRequirementRows, releaseReviewAllowed, releaseStateText,
  type ReleaseCheck, type ReleaseExpectation, type ReleaseRequirement } from './releaseAssuranceState';

type Transport = <T>(path: string, options?: RequestInit) => Promise<T>;
type Project = { id: string; name: string };

/** Parent must key this component by session identity and current team scope.
 * This panel never runs code, calls inference or promotes a passing check.
 */
export function ReleaseAssurance({ role, projects, request,tenantId,userId }: { role: string; projects: Project[]; request: Transport;tenantId:string;userId:string }) {
  const [tab, setTab] = useState<'requirements' | 'checks'>('requirements');
  const [projectId, setProjectId] = useState(projects[0]?.id || '');
  const [requirements, setRequirements] = useState<ReleaseRequirement[]>([]), [checks, setChecks] = useState<ReleaseCheck[]>([]);
  const [requirementId, setRequirementId] = useState(''), [checkId, setCheckId] = useState('');
  const [baseline, setBaseline] = useState(''), [candidate, setCandidate] = useState('');
  const [sources,setSources]=useState<{project_id:string;label:string;sha256:string}[]>([]);
  const [requirementAck, setRequirementAck] = useState(''), [evidenceAck, setEvidenceAck] = useState('');
  const [busy, setBusy] = useState(false), [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(''), [notice, setNotice] = useState('');
  const generation = useRef(0), writing = useRef<number | null>(null), mounted = useRef(false);
  const pending = useRef<BoundedResponse<unknown> | null>(null), submission = useRef<PendingSubmission | null>(null);
  const transport = useRef(request); transport.current = request;
  const scope = JSON.stringify([role, projects.map(project => project.id).sort()]);
  const scopeRef = useRef(scope); scopeRef.current = scope;
  const available = requirements.filter(row => row.project_id === projectId);
  const approved = available.filter(row => row.state === 'approved');
  const savedChecks = checks.filter(row => row.project_id === projectId);
  const selectedRequirement = available.find(row => row.id === requirementId) || null;
  const selectedCheck = savedChecks.find(row => row.id === checkId) || null;
  const failedCases = releaseFailedCases(selectedCheck);

  async function refresh() {
    if (writing.current !== null || !releaseCanRead(role)) return;
    const current = ++generation.current, expectedScope = scopeRef.current;
    pending.current?.cancel(); setBusy(true); setError('');
    const operation = boundedResponse(signal => Promise.all([
      transport.current<unknown>('/v1/release/requirements', { signal }),
      transport.current<unknown>('/v1/release/checks', { signal }),
      transport.current<{project_id:string;label:string;sha256:string}[]>('/v1/release/sources',{signal}),
    ]));
    pending.current = operation;
    try {
      const [nextRequirements, nextChecks,nextSources] = await operation.promise;
      if (!mounted.current || current !== generation.current || expectedScope !== scopeRef.current) return;
      const ids = projects.map(project => project.id);
      if (!releaseRequirementRows(nextRequirements, ids) || !releaseCheckRows(nextChecks, ids))
        throw new Error('Saved release records did not match the current project scope.');
      if(!Array.isArray(nextSources)||nextSources.some(s=>!s||!ids.includes(s.project_id)||!releaseHash(s.sha256)||typeof s.label!=='string'))throw new Error('Source catalog did not match project scope.');
      setSources(nextSources);setRequirements(nextRequirements); setChecks(nextChecks); setLoaded(true);
    } catch (failure) {
      if (mounted.current && current === generation.current && expectedScope === scopeRef.current) setError(String(failure));
    } finally {
      if (mounted.current && current === generation.current) { pending.current = null; setBusy(false); }
    }
  }
  useEffect(() => {
    mounted.current = true; generation.current++; pending.current?.cancel(); writing.current = null; setBusy(false);
    setRequirements([]); setChecks([]); setRequirementId(''); setCheckId('');
    setRequirementAck(''); setEvidenceAck(''); setNotice(''); setError(''); setLoaded(false);
    setSources([]);setBaseline(''); setCandidate(''); submission.current = null;
    setProjectId(previous => projects.some(project => project.id === previous) ? previous : projects[0]?.id || '');
    void refresh();
    return () => { mounted.current = false; generation.current++; pending.current?.cancel(); };
  }, [scope]);

  function selectProject(id: string) {
    setProjectId(id); setRequirementId(''); setCheckId(''); setRequirementAck(''); setEvidenceAck('');
    setBaseline(''); setCandidate(''); setNotice(''); setError(''); submission.current = null;
  }
  async function mutate(path: string, body: object, validate: (value: unknown) => boolean, done: (value: unknown) => void) {
    if (writing.current !== null || !releaseCanWrite(role)) return;
    pending.current?.cancel();
    const current = ++generation.current, expectedScope = scopeRef.current;
    writing.current = current;
    setBusy(true); setError(''); setNotice('');
    const operation = boundedResponse(signal => transport.current<unknown>(path,
      { method: 'POST', body: JSON.stringify(body), signal }));
    pending.current = operation; let accepted = false;
    try {
      const result = await operation.promise;
      if (!mounted.current || current !== generation.current || expectedScope !== scopeRef.current) return;
      if (!validate(result)) throw new Error('Saved response did not match this exact action. Refresh before continuing.');
      done(result); accepted = true;
    } catch (failure) {
      if (mounted.current && current === generation.current && expectedScope === scopeRef.current)
        setError(`${String(failure)} Refresh saved records before retrying an uncertain request.`);
    } finally {
      if (writing.current === current) writing.current = null;
      if (mounted.current && current === generation.current) { pending.current = null; setBusy(false); }
    }
    if (accepted) await refresh();
  }
  function saveDraft(value:unknown) {
    if (!projectId || !releaseCanWrite(role)) return;
    let spec;
    try { spec = parseReleaseDraft(JSON.stringify(value)); } catch (failure) { setError(String(failure)); return; }
    void mutate('/v1/release/requirements', { project_id: projectId, spec },
      value => releaseRequirementRows([value], [projectId]), value => {
        const row = value as ReleaseRequirement; setRequirementId(row.id);
        setNotice('Draft saved. A different administrator must review and approve the exact requirement.');
      });
  }
  function approve() {
    const row = selectedRequirement;
    if (!row || !releaseCanApprove(role) || requirementAck !== releaseRequirementIdentity(row)) return;
    void mutate(`/v1/release/requirements/${encodeURIComponent(row.id)}/approve`, { expected_hash: row.requirement_hash },
      value => releaseRequirementRows([value], [row.project_id]) && (value as ReleaseRequirement).id === row.id
        && (value as ReleaseRequirement).requirement_hash === row.requirement_hash,
      () => { setRequirementAck(''); setNotice('Exact requirement approved. Existing checks remain historical.'); });
  }
  function queue() {
    if (!projectId || !releaseHash(baseline) || !releaseHash(candidate) || !approved.length) return;
    const ids = approved.map(row => row.id).sort();
    const intent = releaseIntent(projectId, baseline, candidate, ids);
    const existing = savedChecks.find(row => releaseIntent(row.project_id, row.baseline_sha256, row.candidate_sha256, row.requirement_ids) === intent);
    if (existing && ['queued', 'running', 'passed', 'regression', 'baseline_failed'].includes(existing.state)) {
      setCheckId(existing.id); setNotice('These inputs already have a saved check. Open it below; no duplicate was queued.'); return;
    }
    const submissionIntent = existing && ['blocked', 'canceled'].includes(existing.state) ? `${intent}:retry:${existing.id}` : intent;
    submission.current = submissionForIntent(submission.current, submissionIntent, () => crypto.randomUUID());
    void mutate('/v1/release/checks', { project_id: projectId, baseline_sha256: baseline, candidate_sha256: candidate,
      requirement_ids: ids, idempotency_key: submission.current.key },
      value => releaseCheckRows([value], [projectId]) && releaseIntent((value as ReleaseCheck).project_id,
        (value as ReleaseCheck).baseline_sha256, (value as ReleaseCheck).candidate_sha256, (value as ReleaseCheck).requirement_ids) === intent,
      value => { setCheckId((value as ReleaseCheck).id); setNotice('Saved for the local operator. The browser does not execute repository code.'); });
  }
  function cancel() {
    const row = selectedCheck; if (!row || !['queued', 'running'].includes(row.state)) return;
    void mutate(`/v1/release/checks/${encodeURIComponent(row.id)}/cancel`, { expected_revision: row.revision },
      value => releaseCheckRows([value], [row.project_id]) && (value as ReleaseCheck).id === row.id,
      () => { setEvidenceAck(''); setNotice('Saved cancellation. Stopping the remote process is not verified by this action.'); });
  }
  function decide(decision: 'accept_for_manual_release' | 'reject') {
    const row = selectedCheck;
    if (!row || !row.evidence_hash || evidenceAck !== releaseEvidenceIdentity(row) || row.decision) return;
    if (decision === 'accept_for_manual_release' && !releaseReviewAllowed(row, role)) return;
    void mutate(`/v1/release/checks/${encodeURIComponent(row.id)}/decide`,
      { expected_revision: row.revision, evidence_hash: row.evidence_hash, decision },
      value => releaseCheckRows([value], [row.project_id]) && (value as ReleaseCheck).id === row.id
        && (value as ReleaseCheck).evidence_hash === row.evidence_hash,
      () => { setEvidenceAck(''); setNotice('Human decision saved. No code was merged or deployed.'); });
  }
  function observed(value: ReleaseExpectation) {
    return <span>HTTP {value.status_code} · {value.visible_fields.length ? value.visible_fields.join(', ') : 'no resource fields'}</span>;
  }
  if (!releaseCanRead(role)) return <section className="panel"><h2>Release checks</h2><p>This view requires engineer, manager or administrator access.</p></section>;
  return <section className="panel span-three" aria-labelledby="release-title">
    <div className="button-row"><h2 id="release-title">Protect customer behavior</h2>
      <button type="button" className="secondary" disabled={busy} onClick={() => void refresh()}>Refresh saved records</button></div>
    <p className="muted">Review requirements. Check a proposed release. Keep the evidence.</p>
    <label>Project<select value={projectId} disabled={busy} onChange={event => selectProject(event.target.value)}>
      {!projects.length && <option value="">No visible projects</option>}
      {projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
    {role === 'manager' && <p className="tiny">Manager view: inspection only.</p>}
    <div className="button-row" role="group" aria-label="Release assurance sections">
      <button type="button" className="secondary" aria-pressed={tab === 'requirements'} onClick={() => setTab('requirements')}>Requirements</button>
      <button type="button" className="secondary" aria-pressed={tab === 'checks'} onClick={() => setTab('checks')}>Checks</button></div>
    {busy && <p role="status">Waiting for a bounded server response…</p>}
    {error && <p role="alert" className="alert error">{error}</p>}
    {notice && <p role="status" className="alert notice">{notice}</p>}
    {tab === 'requirements' ? <>
      {loaded && !available.length && <p>No saved requirements for this project.</p>}
      {!!available.length && <label>Saved requirement<select disabled={busy} value={requirementId} onChange={event => { setRequirementId(event.target.value); setRequirementAck(''); }}>
        <option value="">Choose a requirement</option>{available.map(row => <option key={row.id} value={row.id}>{row.spec.title} · v{row.spec.version} · {row.state}</option>)}</select></label>}
      {selectedRequirement && <article aria-label="Exact requirement review">
        <h3>{selectedRequirement.spec.title}</h3><p>{selectedRequirement.spec.customer_tenant_id} · {selectedRequirement.spec.cases.length} cases · {selectedRequirement.state}</p>
        <p className="tiny">Source: {selectedRequirement.spec.source_ref} · Owner: {selectedRequirement.spec.owner_id}</p>
        <p className="tiny">Requirement expiry: {selectedRequirement.spec.expires_at ? new Date(selectedRequirement.spec.expires_at).toLocaleString() : 'No expiry set'}</p>
        <div style={{ overflowX: 'auto' }}><table><thead><tr><th scope="col">Case</th><th scope="col">Tenant</th><th scope="col">Expected</th></tr></thead>
          <tbody>{selectedRequirement.spec.cases.map(item => <tr key={item.case_id}><th scope="row">{item.title}</th><td>{item.input.resource_tenant_id} · {item.kind}</td><td>{observed(item.expected)}</td></tr>)}</tbody></table></div>
        <details><summary>Exact requirement and digest</summary><code style={{ overflowWrap: 'anywhere' }}>{selectedRequirement.requirement_hash}</code>
          <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(selectedRequirement.spec, null, 2)}</pre></details>
        {releaseCanApprove(role) && selectedRequirement.state === 'draft' && <div role="group" aria-label="Approve exact requirement">
          <label><input type="checkbox" checked={requirementAck === releaseRequirementIdentity(selectedRequirement)} disabled={busy}
            onChange={event => setRequirementAck(event.target.checked ? releaseRequirementIdentity(selectedRequirement) : '')}/>
            I reviewed these exact expectations and their digest.</label>
          <button type="button" className="primary" disabled={busy || requirementAck !== releaseRequirementIdentity(selectedRequirement)} onClick={approve}>Approve exact requirement</button>
          <p className="tiny">The author cannot approve their own requirement.</p></div>}
      </article>}
      {releaseCanWrite(role) && <details><summary>Draft a requirement revision</summary>
        <CustomerRequirementForm key={`${projectId}:${tenantId}:${userId}`} tenant={tenantId} owner={userId} existing={available} busy={busy} onSave={saveDraft}/></details>}
    </> : <>
      {releaseCanWrite(role) && <details open={!savedChecks.length}><summary>Check a proposed release</summary>
        <p className="tiny">All {approved.length} approved requirements in this project will be included. Source files stay on the operator host.</p>
        <label>Current release<select value={baseline} disabled={busy} onChange={event=>setBaseline(event.target.value)}><option value="">Choose registered source</option>{sources.filter(s=>s.project_id===projectId).map(s=><option key={s.sha256} value={s.sha256}>{s.label} · {s.sha256.slice(0,8)}</option>)}</select></label>
        <label>Proposed release<select value={candidate} disabled={busy} onChange={event=>setCandidate(event.target.value)}><option value="">Choose registered source</option>{sources.filter(s=>s.project_id===projectId).map(s=><option key={s.sha256} value={s.sha256}>{s.label} · {s.sha256.slice(0,8)}</option>)}</select></label>
        {!sources.some(s=>s.project_id===projectId)&&<p>Ask your engineer to register the two reviewed source snapshots with the local onboarding CLI.</p>}
        <button type="button" className="primary" disabled={busy || !projectId || !approved.length || !releaseHash(baseline) || !releaseHash(candidate)} onClick={queue}>Queue independent check</button></details>}
      {loaded && !savedChecks.length && <p>No saved release checks for this project.</p>}
      {!!savedChecks.length && <label>Saved check<select disabled={busy} value={checkId} onChange={event => { setCheckId(event.target.value); setEvidenceAck(''); }}>
        <option value="">Choose a saved check</option>{savedChecks.map(row => <option key={row.id} value={row.id}>{releaseStateText(row.state)} · {row.candidate_sha256.slice(0, 10)} · {row.id.slice(0, 6)}</option>)}</select></label>}
      {selectedCheck && <article aria-label="Saved release evidence">
        <h3>{releaseStateText(selectedCheck.state)}</h3><p className="tiny">{selectedCheck.requirement_ids.length} {selectedCheck.requirement_ids.length===1?'requirement':'requirements'} · revision {selectedCheck.revision} · Not released</p>
        {selectedCheck.reason && <p>{selectedCheck.reason}</p>}
        {selectedCheck.decision && <p>Human decision: {selectedCheck.decision === 'reject' ? 'Rejected' : 'Accepted for manual release'}</p>}
        {failedCases.map(item => <article key={`${item.requirement_key}/${item.case_id}`} className="alert error" style={{ display: 'block' }}>
          <h4>{item.requirement_key} / {item.case_id}</h4>
          <p>Expected: {observed(item.expected)}</p><p>Baseline: {observed(item.observed_baseline)}</p><p>Candidate: {observed(item.observed_candidate)}</p></article>)}
        <details><summary>Exact source and evidence</summary><p>Baseline: <code style={{ overflowWrap: 'anywhere' }}>{selectedCheck.baseline_sha256}</code></p>
          <p>Candidate: <code style={{ overflowWrap: 'anywhere' }}>{selectedCheck.candidate_sha256}</code></p>
          <p>Evidence: <code style={{ overflowWrap: 'anywhere' }}>{selectedCheck.evidence_hash || 'Not saved yet'}</code></p>
          {selectedCheck.report && <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(selectedCheck.report, null, 2)}</pre>}</details>
        {releaseCanWrite(role) && ['queued', 'running'].includes(selectedCheck.state) && <button type="button" className="secondary" disabled={busy} onClick={cancel}>Cancel saved check</button>}
        {releaseCanWrite(role) && selectedCheck.report && selectedCheck.evidence_hash && !selectedCheck.decision && <div role="group" aria-label="Review exact release evidence">
          <label><input type="checkbox" disabled={busy} checked={evidenceAck === releaseEvidenceIdentity(selectedCheck)}
            onChange={event => setEvidenceAck(event.target.checked ? releaseEvidenceIdentity(selectedCheck) : '')}/>I reviewed this exact evidence and its limitations.</label>
          <div className="button-row"><button type="button" className="primary" disabled={busy || !releaseReviewAllowed(selectedCheck, role) || evidenceAck !== releaseEvidenceIdentity(selectedCheck)} onClick={() => decide('accept_for_manual_release')}>Accept for manual release</button>
            <button type="button" className="secondary" disabled={busy || evidenceAck !== releaseEvidenceIdentity(selectedCheck)} onClick={() => decide('reject')}>Reject this evidence</button></div>
          <p className="tiny">Acceptance records a decision. It does not merge or deploy code.</p></div>}
      </article>}
    </>}
    <p className="tiny">Source stays with your operator. Checks produce evidence; a human decides what to release.</p>
  </section>;
}
