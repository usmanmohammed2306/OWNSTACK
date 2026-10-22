import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Activity, ArrowRight, ArrowUpRight, CheckCircle2, Clock3, Code2, FileText, Fingerprint, Layers3, LockKeyhole, Search, ShieldCheck, XCircle } from 'lucide-react';
import './style.css';
import './workbench.css';
import { ScopeScene } from './ScopeScene';
import { WorkspaceHome } from './WorkspaceHome';
import { RequestComposer } from './RequestComposer';
import { BoundaryInspector } from './BoundaryInspector';
import { PatchDiff } from './PatchDiff';
import { BoundedRepair } from './BoundedRepair';
import { CommandMenu } from './CommandMenu';
import { ApprovalReview } from './ApprovalReview';
import { People } from './People';
import { AccessInspector } from './AccessInspector';
import { RevokeReview } from './RevokeReview';
import { currentPatchCheck, effectiveVariationState, filterRequests, type RequestFilter } from './review';
import { sameProposal, sameSession, submissionForIntent, type PendingSubmission, type ProposalIdentity } from './responseIdentity';
import './experience.css';

type Session = { csrf_token: string; user_id: string; tenant_id: string; role: string; ai_mode: string };
type Request = { id: string; text: string; kind: string; project_id: string | null; viewer_id: string | null; expires_at: string | null; status: string; revision: number; current_attempt_id: string | null; accepted_proposal_id: string | null };
type Proposal = { id: string; route: string; reason: string; proposal_hash: string; preview_hash: string | null; status: string; contract_id: string | null; contract_version: number | null };
type Preview = { before: boolean; after: boolean; visible_documents: { id: string; title: string }[]; expires_at: string; snapshot_hash: string; matches_saved_proposal: boolean; limitations: string; counterfactual: { checks: number; intended_delta_observed: boolean; unexpected_delta_count: number } };
type Attempt = { id: string; number: number; state: string; model_id: string; error_code: string | null; latency_ms: number | null };
type Variation = { id: string; project_id: string; viewer_id: string; state: string; expires_at: string };
type Engineering = { id: string; request_id: string; status: string; patch_hash: string | null; human_decision: string | null };
type EngineeringDetail = { id: string; request: Request; status: string; patch: { edits: { path: string; old: string; new: string }[] } | null; patch_hash: string | null; human_decision: string | null; current_checks_usable: boolean; checks: { subject_hash: string; result: { passed: boolean; stdout: string; stderr: string; runner: string }; limitation: string }[] };
type Event = { id: string; request_id: string; type: string; payload: Record<string, unknown>; created_at: string };
type InferenceBudget = { mode: string; reserved_calls: number; max_live_calls: number; remaining_calls: number | null; note: string };
type Convergence = { need_key: string; your_tenant_request_count: number; affected_tenant_count: number | null; decision: string | null; observed_granted_reads: number | null; usage_scope: string; note: string };
type HostObservation = { id: string; project_id: string; actor_id: string; variation_id: string | null; action: string; allowed: boolean; basis: string; observed_at: string };

function idempotency() { return crypto.randomUUID(); }
class ApiError extends Error { constructor(public status: number, detail: string) { super(`${status}: ${detail}`); } }
async function api<T>(path: string, session: Session | null, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { ...options, credentials: 'same-origin', headers: { 'Content-Type': 'application/json', ...(session ? { 'X-CSRF-Token': session.csrf_token } : {}), ...options.headers } });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new ApiError(response.status, body.detail || response.statusText);
  }
  return response.json() as Promise<T>;
}
function formatTime(value: string | null) { return value ? new Date(value).toLocaleString() : 'Not set'; }
function accessPrompt(tenant: string) { return `Give ${tenant}-contractor read-only access to Project ${tenant === 'nova' ? 'Nova' : 'Atlas'} until the selected expiry.`; }
function statusClass(value: string) { return ['active', 'accepted', 'checks_passed', 'approved'].includes(value) ? 'good' : ['failed', 'refused', 'checks_failed', 'revoked', 'expired'].includes(value) ? 'bad' : 'neutral'; }

function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [restoring, setRestoring] = useState(true);
  const sessionRef = useRef<Session | null>(null);
  sessionRef.current = session;
  const [username, setUsername] = useState('atlas-admin');
  const [password, setPassword] = useState('');
  const [tab, setTab] = useState<'journey' | 'engineering' | 'convergence' | 'ledger' | 'demo' | 'people'>('journey');
  const [requests, setRequests] = useState<Request[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const selectedRef = useRef<string | null>(null);
  function choose(id: string | null) { selectedRef.current = id; setSelected(id); }
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [previewRecord, setPreviewRecord] = useState<{ identity: ProposalIdentity; data: Preview } | null>(null);
  const proposalIdentityRef = useRef<ProposalIdentity | null>(null);
  const previewGeneration = useRef(0);
  const refreshGeneration = useRef(0);
  const refreshInFlight = useRef<number | null>(null);
  const requestGeneration = useRef(0);
  const actionGeneration = useRef(0);
  const hostReadGeneration = useRef(0);
  const pendingSubmission = useRef<PendingSubmission | null>(null);
  const [attempts, setAttempts] = useState<Attempt[]>([]);
  const [variations, setVariations] = useState<Variation[]>([]);
  const [engineering, setEngineering] = useState<Engineering[]>([]);
  const [engineeringDetail, setEngineeringDetail] = useState<EngineeringDetail | null>(null);
  const engineeringIdRef = useRef<string | null>(null);
  const engineeringGeneration = useRef(0);
  const engineeringDetailRef = useRef<EngineeringDetail | null>(null);
  engineeringDetailRef.current = engineeringDetail;
  const [manualBase, setManualBase] = useState<{ path: string; source: string } | null>(null);
  const [manualSource, setManualSource] = useState('');
  const [events, setEvents] = useState<Event[]>([]);
  const [convergence, setConvergence] = useState<Convergence[]>([]);
  const [rationales, setRationales] = useState<Record<string, string>>({});
  const [observations, setObservations] = useState<HostObservation[]>([]);
  const [inferenceBudget, setInferenceBudget] = useState<InferenceBudget | null>(null);
  const [hostDocuments, setHostDocuments] = useState<{ id: string; title: string }[] | null>(null);
  const [kind, setKind] = useState<'access' | 'feature'>('access');
  const [requestText, setRequestText] = useState(accessPrompt('atlas'));
  const [requestOpen, setRequestOpen] = useState(false);
  const [viewer, setViewer] = useState('atlas-contractor');
  const [expiry, setExpiry] = useState(() => { const date = new Date(Date.now() + 2 * 86400000); return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16); });
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [query, setQuery] = useState('');
  const [requestFilter, setRequestFilter] = useState<RequestFilter>('all');
  const [lastSync, setLastSync] = useState<number | null>(null);
  const [syncFailed, setSyncFailed] = useState(false);
  const pageHeading = useRef<HTMLHeadingElement>(null);
  const current = useMemo(() => requests.find(r => r.id === selected) || null, [requests, selected]);
  const proposalIdentity: ProposalIdentity | null = session && current && proposal && current.accepted_proposal_id === proposal.id
    ? { session, requestId: current.id, proposalId: proposal.id, proposalHash: proposal.proposal_hash } : null;
  proposalIdentityRef.current = proposalIdentity;
  const preview = sameProposal(previewRecord?.identity || null, proposalIdentity) ? previewRecord!.data : null;
  const filteredRequests = useMemo(() => filterRequests(requests, query, requestFilter), [requests, query, requestFilter]);
  const effectiveVariations = variations.map(v => ({ ...v, state: effectiveVariationState(v.state, v.expires_at, Date.now()) }));
  const activeVariations = effectiveVariations.filter(v => v.state === 'active');
  const pastVariations = effectiveVariations.filter(v => v.state !== 'active');
  const visibleEvents = events.filter(event => !selected || event.request_id === selected);
  const projectId = session?.tenant_id === 'nova' ? 'nova-project' : 'atlas-project';
  const navigation = [
    { id: 'demo' as const, label: 'Workspace', description: 'Your customer changes, in one place.', icon: ShieldCheck, allowed: true },
    { id: 'journey' as const, label: session?.role === 'contractor' ? 'Your project' : 'Requests', description: 'From a customer need to a reviewed, scoped change.', icon: Layers3, allowed: session?.role !== 'product_owner' },
    { id: 'engineering' as const, label: 'Code review', description: 'Inspect the patch. Check the evidence. Make the decision.', icon: Code2, allowed: !['contractor', 'product_owner'].includes(session?.role || '') },
    { id: 'convergence' as const, label: 'Product signals', description: 'Find repeated needs. Decide what belongs in the product.', icon: Activity, allowed: session?.role !== 'contractor' },
    { id: 'ledger' as const, label: 'Activity', description: 'Saved events and actual host checks.', icon: FileText, allowed: !['contractor', 'product_owner'].includes(session?.role || '') },
    { id: 'people' as const, label: 'People', description: 'Manage workspace access and inspect identity changes.', icon: LockKeyhole, allowed: session?.role === 'admin' },
  ].filter(item => item.allowed);
  function navigate(target: typeof tab) { setError(''); setNotice(''); setTab(target); }
  useEffect(() => { window.scrollTo({ top: 0, behavior: 'instant' }); pageHeading.current?.focus({ preventScroll: true }); }, [tab]);

  function clearWorkspace() {
    refreshGeneration.current++; requestGeneration.current++; engineeringGeneration.current++; previewGeneration.current++;
    choose(null); engineeringIdRef.current = null; proposalIdentityRef.current = null; pendingSubmission.current = null;
    setRequests([]); setVariations([]); setEvents([]); setEngineering([]); setEngineeringDetail(null);
    setConvergence([]); setObservations([]); setInferenceBudget(null); setAttempts([]); setProposal(null);
    setPreviewRecord(null); setHostDocuments(null); setManualBase(null); setManualSource(''); setRationales({}); setRequestOpen(false);
    setLastSync(null); setSyncFailed(false);
  }

  async function refresh(activeSession = sessionRef.current, force = false) {
    if (!activeSession || !sameSession(activeSession, sessionRef.current) || (refreshInFlight.current !== null && !force)) return;
    const generation = ++refreshGeneration.current;
    refreshInFlight.current = generation;
    const isCurrent = () => generation === refreshGeneration.current && sameSession(activeSession, sessionRef.current);
    try {
      if (activeSession.role === 'contractor') {
        setRequests([]); setVariations([]); setEvents([]); setEngineering([]); setConvergence([]); setObservations([]);
        setInferenceBudget(null); choose(null); setProposal(null); setPreviewRecord(null); setAttempts([]);
        setLastSync(null); setSyncFailed(false);
        return;
      }
      if (activeSession.role === 'product_owner') {
        const [conv, budget] = await Promise.all([
          api<Convergence[]>('/v1/convergence', activeSession), api<InferenceBudget>('/v1/inference-budget', activeSession),
        ]);
        if (!isCurrent()) return;
        setConvergence(conv); setInferenceBudget(budget);
        setRequests([]); setVariations([]); setEvents([]); setEngineering([]); setObservations([]);
        setLastSync(Date.now()); setSyncFailed(false);
        return;
      }
      // Apply a complete refresh together. A failed collection request keeps the saved view intact.
      const [r, v, ev, eng, conv, budget, observed] = await Promise.all([
        api<Request[]>('/v1/requests', activeSession), api<Variation[]>('/v1/variations', activeSession),
        api<Event[]>('/v1/events', activeSession), api<Engineering[]>('/v1/engineering', activeSession),
        api<Convergence[]>('/v1/convergence', activeSession), api<InferenceBudget>('/v1/inference-budget', activeSession),
        api<HostObservation[]>('/v1/host-observations', activeSession),
      ]);
      if (!isCurrent()) return;
      const nextId = r.some(item => item.id === selectedRef.current) ? selectedRef.current : r[0]?.id || null;
      const selectedRequest = r.find(item => item.id === nextId);
      const item = engineeringDetailRef.current;
      const itemGeneration = engineeringGeneration.current;
      const [a, p, detail] = await Promise.all([
        nextId ? api<Attempt[]>(`/v1/requests/${nextId}/attempts`, activeSession) : Promise.resolve([]),
        selectedRequest?.accepted_proposal_id ? api<Proposal>(`/v1/proposals/${selectedRequest.accepted_proposal_id}`, activeSession) : Promise.resolve(null),
        item && ['drafting', 'checking', 'repairing'].includes(item.status) ? api<EngineeringDetail>(`/v1/engineering/${item.id}`, activeSession) : Promise.resolve(null),
      ]);
      if (!isCurrent()) return;
      setRequests(r); setVariations(v); setEvents(ev); setEngineering(eng); setConvergence(conv);
      setInferenceBudget(budget); setObservations(observed);
      if (detail && engineeringGeneration.current === itemGeneration && engineeringIdRef.current === detail.id) setEngineeringDetail(detail);
      if (selectedRef.current !== nextId) setPreviewRecord(null);
      requestGeneration.current++;
      choose(nextId); setAttempts(a); setProposal(p);
      if (!p) setPreviewRecord(null);
      setLastSync(Date.now()); setSyncFailed(false);
    } catch (err) {
      if (!isCurrent()) return;
      setSyncFailed(true);
      if (err instanceof ApiError && err.status === 401) { sessionRef.current = null; setSession(null); clearWorkspace(); }
      setError(String(err));
    } finally {
      if (refreshInFlight.current === generation) refreshInFlight.current = null;
    }
  }

  useEffect(() => {
    let mounted = true;
    sessionStorage.removeItem('ownstack-session');
    api<Session>('/v1/session', null).then(saved => { if (mounted) { sessionRef.current = saved; setSession(saved); setTab('demo'); } })
      .catch(() => {}).finally(() => { if (mounted) setRestoring(false); });
    return () => { mounted = false; };
  }, []);
  useEffect(() => { void refresh(session, true); setViewer(`${session?.tenant_id || 'atlas'}-contractor`); setRequestText(accessPrompt(session?.tenant_id || 'atlas')); }, [session?.csrf_token]);
  useEffect(() => {
    if (!session || session.role === 'contractor') return;
    const timer = setInterval(() => { void refresh(); }, 3000);
    return () => clearInterval(timer);
  }, [session?.csrf_token]);

  async function action(label: string, task: () => Promise<void>) {
    const generation = ++actionGeneration.current;
    const startedSession = sessionRef.current;
    const startedRequest = selectedRef.current, startedEngineering = engineeringIdRef.current;
    refreshGeneration.current++;
    setBusy(label); setError(''); setNotice('');
    try { await task(); if (generation === actionGeneration.current) await refresh(sessionRef.current, true); }
    catch (err) {
      if (generation === actionGeneration.current && startedRequest === selectedRef.current && startedEngineering === engineeringIdRef.current
        && (sameSession(startedSession, sessionRef.current) || (!startedSession && !sessionRef.current))) setError(String(err));
    } finally { if (generation === actionGeneration.current) setBusy(''); }
  }

  async function signIn() {
    await action('sign in', async () => {
      const next = await api<Session>('/v1/session', null, { method: 'POST', body: JSON.stringify({ username, password }) });
      setPassword('');
      clearWorkspace(); sessionRef.current = next; setSession(next); setTab('demo'); setQuery(''); setRequestFilter('all');
    });
  }

  async function createRequest() {
    if (!session || !sameSession(session, sessionRef.current)) return;
    const activeSession = session;
    await action('create request', async () => {
      const body = { text: requestText, kind, project_id: projectId, viewer_id: kind === 'access' ? viewer : null,
        expires_at: kind === 'access' ? new Date(expiry).toISOString() : null };
      const intent = JSON.stringify(body);
      const submission = submissionForIntent(pendingSubmission.current, intent, idempotency);
      pendingSubmission.current = submission;
      const result = await api<{ id: string }>('/v1/requests', activeSession, { method: 'POST', headers: { 'Idempotency-Key': submission.key }, body: intent });
      if (!sameSession(activeSession, sessionRef.current)) return;
      if (pendingSubmission.current === submission) pendingSubmission.current = null;
      requestGeneration.current++; previewGeneration.current++;
      choose(result.id); setProposal(null); setPreviewRecord(null); setRequestOpen(false); navigate('journey');
      setNotice('Request saved. Interpretation has not started yet.');
    });
  }

  async function interpret() {
    if (!current || !session) return;
    const activeSession = session, requestId = current.id;
    await action('interpret', async () => {
      const result = await api<{ status: string; attempt_id: string }>(`/v1/requests/${requestId}/interpret`, activeSession, { method: 'POST' });
      if (sameSession(activeSession, sessionRef.current) && selectedRef.current === requestId) setNotice(`Saved attempt ${result.attempt_id}. The worker will process it.`);
    });
  }

  async function manualHandoff() {
    if (!current || !session) return;
    const activeSession = session, requestId = current.id;
    await action('manual handoff', async () => {
      const result = await api<{ status: string; ai_call: boolean }>(`/v1/requests/${requestId}/manual-handoff`, activeSession,
        { method: 'POST', headers: { 'Idempotency-Key': idempotency() } });
      if (sameSession(activeSession, sessionRef.current) && selectedRef.current === requestId) setNotice(`Engineer created a ${result.status} proposal without an AI call.`);
    });
  }

  async function previewProposal() {
    const identity = proposalIdentity;
    if (!identity || !sameProposal(identity, proposalIdentityRef.current) || selectedRef.current !== identity.requestId) return;
    const generation = ++previewGeneration.current;
    setPreviewRecord(null);
    await action('preview', async () => {
      const result = await api<Preview>(`/v1/proposals/${identity.proposalId}/preview`, session, { method: 'POST' });
      if (generation !== previewGeneration.current || selectedRef.current !== identity.requestId || !sameSession(identity.session, sessionRef.current)
        || !sameProposal(identity, proposalIdentityRef.current)) return;
      setPreviewRecord({ identity, data: result });
    });
  }

  async function approveProposal() {
    const identity = proposalIdentity;
    if (!identity || !proposal || !preview || !preview.matches_saved_proposal || preview.snapshot_hash !== proposal.preview_hash
      || session?.role !== 'admin' || proposal.status !== 'ready' || selectedRef.current !== identity.requestId
      || !sameSession(identity.session, sessionRef.current) || !sameProposal(identity, proposalIdentityRef.current)) {
      setError('The selected proposal needs a fresh matching preview before approval.');
      return;
    }
    await action('approve', async () => {
      await api(`/v1/proposals/${identity.proposalId}/approve`, session, { method: 'POST', headers: { 'Idempotency-Key': idempotency() }, body: JSON.stringify({ proposal_hash: identity.proposalHash }) });
      if (sameSession(identity.session, sessionRef.current) && selectedRef.current === identity.requestId) setNotice('Exact proposal approved. The owned host fixture now enforces it.');
    });
  }

  async function inspectHost() {
    if (!session) return;
    const activeSession = session, generation = ++hostReadGeneration.current;
    setHostDocuments(null);
    await action('host read', async () => {
      const docs = await api<{ id: string; title: string }[]>(`/v1/host/projects/${projectId}/documents`, activeSession);
      if (generation !== hostReadGeneration.current || !sameSession(activeSession, sessionRef.current)) return;
      setHostDocuments(docs); setNotice(`The protected host API allowed this read as ${activeSession.user_id}.`);
    });
  }

  async function openEngineering(id: string) {
    if (!session) return;
    const activeSession = session, generation = ++engineeringGeneration.current;
    engineeringIdRef.current = id; setEngineeringDetail(null); setManualBase(null); setManualSource('');
    await action('open work item', async () => {
      const detail = await api<EngineeringDetail>(`/v1/engineering/${id}`, activeSession);
      if (generation === engineeringGeneration.current && engineeringIdRef.current === id && sameSession(activeSession, sessionRef.current)) {
        engineeringGeneration.current++; setEngineeringDetail(detail);
      }
    });
  }

  function inspectEngineeringRequest(requestId: string) {
    const item = engineering.find(work => work.request_id === requestId);
    if (!item) { setError('No saved engineering item found yet. Refresh the request before continuing.'); return; }
    navigate('engineering');
    void openEngineering(item.id);
  }

  async function refreshAfterRepair(itemId: string, signal: AbortSignal) {
    const activeSession = sessionRef.current;
    if (!activeSession || engineeringIdRef.current !== itemId) return;
    const generation = ++engineeringGeneration.current;
    const detail = await api<EngineeringDetail>(`/v1/engineering/${itemId}`, activeSession, { signal });
    if (generation !== engineeringGeneration.current || engineeringIdRef.current !== itemId || !sameSession(activeSession, sessionRef.current)) return;
    setEngineeringDetail(detail);
    void refresh(activeSession, true);
  }

  async function loadManualSource() {
    if (!engineeringDetail || !session) return;
    const id = engineeringDetail.id, activeSession = session, generation = ++engineeringGeneration.current;
    await action('load source', async () => {
      const source = await api<{ path: string; source: string }>('/v1/engineering-source', activeSession);
      if (generation !== engineeringGeneration.current || engineeringIdRef.current !== id || !sameSession(activeSession, sessionRef.current)) return;
      setManualBase(source); setManualSource(source.source);
    });
  }

  async function submitManualPatch() {
    if (!engineeringDetail || !manualBase || !session) return;
    const id = engineeringDetail.id, activeSession = session, generation = ++engineeringGeneration.current;
    await action('manual patch', async () => {
      const patch = { edits: [{ path: manualBase.path, old: manualBase.source, new: manualSource }] };
      await api(`/v1/engineering/${id}/manual-patch`, activeSession,
        { method: 'POST', body: JSON.stringify({ patch }) });
      const detail = await api<EngineeringDetail>(`/v1/engineering/${id}`, activeSession);
      if (generation !== engineeringGeneration.current || engineeringIdRef.current !== id || !sameSession(activeSession, sessionRef.current)) return;
      engineeringGeneration.current++; setEngineeringDetail(detail);
      setManualBase(null); setManualSource('');
      setNotice('Engineer patch saved without AI. Run independent checks before a decision.');
    });
  }

  async function selectRequest(id: string) {
    if (!session) return;
    const activeSession = session, generation = ++requestGeneration.current;
    refreshGeneration.current++; previewGeneration.current++;
    choose(id); setPreviewRecord(null); setProposal(null); setAttempts([]);
    try {
      const [request, a] = await Promise.all([
        api<Request>(`/v1/requests/${id}`, activeSession), api<Attempt[]>(`/v1/requests/${id}/attempts`, activeSession),
      ]);
      const p = request.accepted_proposal_id ? await api<Proposal>(`/v1/proposals/${request.accepted_proposal_id}`, activeSession) : null;
      if (generation !== requestGeneration.current || selectedRef.current !== id || !sameSession(activeSession, sessionRef.current)) return;
      setRequests(rows => rows.some(row => row.id === id) ? rows.map(row => row.id === id ? request : row) : [request, ...rows]);
      setAttempts(a); setProposal(p);
    } catch (err) {
      if (generation === requestGeneration.current && selectedRef.current === id && sameSession(activeSession, sessionRef.current)) setError(String(err));
    }
  }

  async function signOut() {
    const activeSession = session;
    await action('sign out', async () => {
      await api('/v1/session/logout', activeSession, { method: 'POST' });
      if (!sameSession(activeSession, sessionRef.current)) return;
      setSession(null); sessionRef.current = null; clearWorkspace();
    });
  }

  async function downloadArtifact() {
    if (!engineeringDetail || !session) return;
    const id = engineeringDetail.id, activeSession = session, generation = engineeringGeneration.current;
    await action('download artifact', async () => {
      const artifact = await api<object>(`/v1/engineering/${id}/artifact`, activeSession);
      if (generation !== engineeringGeneration.current || engineeringIdRef.current !== id || !sameSession(activeSession, sessionRef.current)) return;
      const url = URL.createObjectURL(new Blob([JSON.stringify(artifact, null, 2)], { type: 'application/json' }));
      const link = document.createElement('a'); link.href = url; link.download = `ownstack-release-${id}.json`; link.click();
      URL.revokeObjectURL(url);
    });
  }

  async function engineeringAction(suffix: string, body?: object) {
    if (!engineeringDetail || !session) return;
    const id = engineeringDetail.id, activeSession = session, generation = ++engineeringGeneration.current;
    await action(suffix, async () => {
      await api(`/v1/engineering/${id}/${suffix}`, activeSession, { method: 'POST', body: body ? JSON.stringify(body) : undefined });
      const detail = await api<EngineeringDetail>(`/v1/engineering/${id}`, activeSession);
      if (generation === engineeringGeneration.current && engineeringIdRef.current === id && sameSession(activeSession, sessionRef.current)) {
        engineeringGeneration.current++; setEngineeringDetail(detail);
      }
    });
  }

  async function decideConvergence(needKey: string, decision: string) {
    if (!session) return;
    const activeSession = session;
    await action('convergence decision', async () => {
      await api(`/v1/convergence/${needKey}/decide`, activeSession, { method: 'POST', body: JSON.stringify({ decision, rationale: rationales[needKey] || '' }) });
      if (sameSession(activeSession, sessionRef.current)) setNotice(`Recorded ${decision}. Nothing was automatically promoted.`);
    });
  }

  if (!session) return <div className="login-shell"><div className="brand-mark">O<span>·</span></div><div className="login-card">
    <p className="eyebrow">WELCOME TO OWNSTACK</p><h1>Make change.<br /><em>Keep control.</em></h1>
    <p className="muted">Your customer needs something different.<br/>Your app can make room for it.</p>
    <label>Identity<select value={username} onChange={e => setUsername(e.target.value)}>
      {['atlas-admin', 'atlas-contractor', 'atlas-engineer', 'nova-admin', 'nova-contractor', 'platform-owner'].map(name => <option key={name}>{name}</option>)}
    </select></label><label>Password<input value={password} type="password" autoComplete="current-password" onChange={e => setPassword(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !busy && !restoring) void signIn(); }} /></label>
    <button className="primary wide" onClick={signIn} disabled={!!busy || restoring}>{restoring ? 'Restoring session…' : 'Enter workbench'} <ArrowRight size={16} /></button>
    {error && <p className="alert error" role="alert">{error}</p>}
    <p className="tiny">Synthetic Atlas and Nova workspaces. Judge access instructions are supplied with the demo.</p>
  </div><div className="login-aside"><div className="login-architecture"><ScopeScene compact/><p className="tiny">Explore the architecture, then enter your workspace.<br/>Local reference build. Synthetic tenants. Real approval boundaries.</p></div></div></div>;

  return <div className="app-shell"><a className="skip-link" href="#workspace-main">Skip to workspace</a>
    <aside className="sidebar"><div className="brand"><span className="brand-mark small">O<span>·</span></span><span>OwnStack<small>CONTROL ROOM</small></span></div>
      <div className="sidebar-label">WORKSPACE <span>{String(navigation.findIndex(item => item.id === tab) + 1).padStart(2,'0')} / {String(navigation.length).padStart(2,'0')}</span></div>
      <nav aria-label="Main navigation">
        {navigation.map(item => <button key={item.id} aria-current={tab === item.id ? 'page' : undefined} className={tab === item.id ? 'active' : ''} onClick={() => navigate(item.id)}><item.icon size={18}/>{item.label}{tab === item.id && <span className="nav-indicator"/>}</button>)}
      </nav>
      <div className="sidebar-principle"><div className="principle-orbit"><LockKeyhole size={22}/></div><p>Adapt the edge.<br/><strong>Keep the core.</strong></p><small>MODEL PROPOSES<br/>HOST ENFORCES</small></div>
      <div className="sidebar-bottom"><div className="identity"><div className="avatar">{session.user_id.slice(0,1).toUpperCase()}</div><span>{session.user_id}<small>{session.tenant_id} · {session.role}</small></span></div>
        <button className="text-button" disabled={!!busy} onClick={signOut}>Sign out / switch identity</button></div>
    </aside>
    <main className={tab === 'demo' ? 'main main--home' : 'main'} id="workspace-main"><header className="topbar"><div><span className="breadcrumb">OWNSTACK <span className="breadcrumb-slash">/</span> {session.tenant_id.toUpperCase()}</span><h1 ref={pageHeading} tabIndex={-1}>{tab === 'demo' ? 'Workspace' : tab === 'journey' ? session.role === 'contractor' ? 'Your project' : 'Requests' : tab === 'engineering' ? 'Code review' : tab === 'convergence' ? 'Product signals' : tab === 'people' ? 'People' : 'Activity'}</h1></div>
      <div className="top-tags"><span className="tag"><span className="dot"/> {session.tenant_id.toUpperCase()}</span><span className={'tag ' + (session.ai_mode === 'nebius' ? 'live' : 'fixture')}>{session.ai_mode === 'nebius' ? 'LIVE NEBIUS' : session.ai_mode === 'off' ? 'AI OFF' : 'SYNTHETIC MODEL'}</span>{session.ai_mode === 'nebius' && inferenceBudget && <span className="tag" title={inferenceBudget.note}>{inferenceBudget.remaining_calls} live calls left</span>}</div></header>
      <div className="workspace-toolbar"><p>{navigation.find(item => item.id === tab)?.description}</p><CommandMenu items={[...navigation.map(item => ({ ...item, run: () => navigate(item.id) })), ...requests.map(request => ({ id: request.id, label: request.text, description: `${request.id} · ${request.status}`, run: () => { setQuery(''); setRequestFilter('all'); navigate('journey'); void selectRequest(request.id); } }))]}/></div>
      <div className="runtime-strip"><span><i className={syncFailed ? 'sync-dot warning' : 'sync-dot'}/>{session.role === 'contractor' ? 'Access checked on every read' : syncFailed ? 'Refresh failed · saved view may be stale' : lastSync ? `Synced ${new Date(lastSync).toLocaleTimeString()}` : 'Reading saved state…'}</span><span>{session.ai_mode === 'off' ? 'AI paused · manual paths available' : session.ai_mode === 'fixture' ? 'Synthetic model · not live evidence' : 'Runtime inference enabled'}{session.ai_mode === 'nebius' && inferenceBudget && ` · ${inferenceBudget.reserved_calls}/${inferenceBudget.max_live_calls} call slots reserved`}</span></div>
      {error && <div className="alert error" role="alert"><XCircle size={16}/>{error}<button onClick={() => setError('')}>Dismiss</button></div>}
      {notice && <div className="alert notice" role="status"><CheckCircle2 size={16}/>{notice}<button onClick={() => setNotice('')}>Dismiss</button></div>}
      {busy && <div className="alert notice" role="status"><Clock3 size={16}/>Working on {busy}…</div>}
      <RequestComposer open={requestOpen} close={() => setRequestOpen(false)} kind={kind} setKind={value => { setKind(value); setRequestText(value === 'access' ? accessPrompt(session.tenant_id) : 'Add PDF export for this project.'); }} text={requestText} setText={setRequestText} project={projectId} viewer={viewer} setViewer={setViewer} expiry={expiry} setExpiry={setExpiry} busy={!!busy} error={error} save={createRequest}/>
      {tab === 'demo' && <WorkspaceHome tenant={session.tenant_id} role={session.role} mode={session.ai_mode} requests={requests} activeCount={activeVariations.length} engineeringCount={engineering.length} loaded={!!lastSync} navigate={navigate} newRequest={() => { setError(''); setRequestOpen(true); }} selectRequest={id => { setQuery(''); setRequestFilter('all'); navigate('journey'); void selectRequest(id); }}/>}
      {tab === 'journey' && session.role === 'contractor' && <div className="content-grid"><section className="panel span-three"><div className="panel-heading"><div><p className="eyebrow">HOST APP / CONTRACTOR</p><h2>Project documents</h2></div><LockKeyhole size={20}/></div><p className="muted">Your access is decided on every read by the host API. It can expire or be revoked without refreshing a browser flag.</p><button className="secondary" onClick={inspectHost}>Test protected read</button>{hostDocuments && <ul className="doc-list">{hostDocuments.map(d => <li key={d.id}><FileText size={15}/>{d.title}</li>)}</ul>}</section></div>}
      {tab === 'journey' && session.role !== 'contractor' && session.role !== 'product_owner' && <div className="content-grid">
        <section className="panel span-three request-launch"><div><h2>A small change starts here.</h2><p className="muted">Create a request, review its scope, then decide.</p></div><button className="primary" disabled={!!busy} onClick={() => setRequestOpen(true)}>New request <ArrowRight size={16}/></button></section>
        <section className="panel span-three request-workspace"><div className="panel-heading"><div><p className="eyebrow">SAVED WORK</p><h2>Your requests</h2></div><Fingerprint size={20}/></div>
          <div className="request-tools"><label className="request-search"><Search size={16}/><input aria-label="Search requests" placeholder="Search intent, ID or status…" value={query} onChange={e => setQuery(e.target.value)}/></label><label className="filter-label">Show<select aria-label="Filter requests" value={requestFilter} onChange={e => setRequestFilter(e.target.value as RequestFilter)}><option value="all">All requests</option><option value="attention">Needs attention</option><option value="active">Active</option><option value="closed">Closed / refused</option></select></label><span className="tiny">{filteredRequests.length} of {requests.length} requests</span></div>
          <div className="request-layout"><div className="request-list">{filteredRequests.length ? filteredRequests.map(r => <button key={r.id} aria-pressed={selected === r.id} className={selected === r.id ? 'request-item selected' : 'request-item'} onClick={() => { void selectRequest(r.id); }}><span className={'pill ' + statusClass(r.status)}>{r.status.replaceAll('_', ' ')}</span><strong>{r.text}</strong><small>{r.id.slice(0,8)} · revision {r.revision} <ArrowUpRight size={12}/></small></button>) : <p className="empty">{requests.length ? 'No matching requests. Clear your search or change the filter.' : 'No requests yet. Start with New request.'}</p>}</div>
          <div className="request-detail">{current ? <><div className="detail-top"><span className="mono">{current.id}</span><span className={'pill ' + statusClass(current.status)}>{current.status}</span></div><h3>{current.text}</h3><div className="facts"><div><small>PROJECT</small><strong>{current.project_id || 'none'}</strong></div><div><small>VIEWER</small><strong>{current.viewer_id || 'none'}</strong></div><div><small>EXPIRES</small><strong>{formatTime(current.expires_at)}</strong></div></div>
            <details className="boundary-disclosure"><summary>Inspect this request's evidence</summary><BoundaryInspector request={current} proposal={proposal} preview={preview} events={events} observations={observations} openLedger={() => navigate('ledger')}/></details>
            {!current.accepted_proposal_id && session.ai_mode === 'off' && <div className="manual-guidance"><Code2 size={18}/><p><strong>Inference is paused. Work can continue.</strong>{session.role === 'engineer' ? ' Use the manual engineer path below. Approval still belongs to a tenant admin.' : ' An engineer can prepare this request without AI. Sign in as your tenant engineer, then return as admin for exact approval.'}</p></div>}
            {!current.accepted_proposal_id && session.ai_mode !== 'off' && <button className="primary" onClick={interpret} disabled={!!busy || inferenceBudget?.remaining_calls === 0 || current.status === 'interpreting'}>{current.status === 'interpreting' ? 'Worker processing…' : inferenceBudget?.remaining_calls === 0 ? 'Approved call limit reached' : 'Start interpretation'} <ArrowRight size={16}/></button>}
            {current.status === 'interpreting' && <button className="secondary" disabled={!!busy} onClick={() => action('cancel local attempt', async () => { await api(`/v1/requests/${current.id}/cancel`, session, { method: 'POST' }); setNotice('Local attempt canceled. Remote inference cancellation is unverified.'); })}>Cancel local attempt</button>}
            {!current.accepted_proposal_id && session.role === 'engineer' && ['new','failed','refused'].includes(current.status) && <button className="primary" onClick={manualHandoff} disabled={!!busy}>Prepare without AI <ArrowRight size={16}/></button>}
            {!!attempts.length && <details className="attempts"><summary>Saved attempts ({attempts.length})</summary>{attempts.map(a => <div className="attempt" key={a.id}><Clock3 size={14}/><span>#{a.number} {a.model_id}</span><span className={'pill ' + statusClass(a.state)}>{a.state}</span>{a.error_code && <small>{a.error_code}</small>}</div>)}</details>}
            {proposal && <div className="proposal"><div className="proposal-head"><h4>Proposal</h4><span className={'pill ' + statusClass(proposal.route)}>{proposal.route}</span></div><p>{proposal.reason}</p><div className="hash-line"><span>EXACT PROPOSAL HASH</span><code>{proposal.proposal_hash}</code></div>{proposal.route === 'configure' && <><p className="muted">Contract {proposal.contract_id} v{proposal.contract_version}</p><div className="button-row"><button className="secondary" onClick={previewProposal}>Run host preview</button><ApprovalReview key={`${proposal.proposal_hash}:${preview?.snapshot_hash}`} enabled={!!preview?.matches_saved_proposal && proposal.status === 'ready' && session.role === 'admin'} busy={!!busy} admin={session.user_id} project={current.project_id} viewer={current.viewer_id} proposalHash={proposal.proposal_hash} contract={proposal.contract_id} version={proposal.contract_version} preview={preview} approve={approveProposal}/></div></>}{proposal.route === 'engineering' && <button className="secondary" onClick={() => inspectEngineeringRequest(current.id)}>Open Engineer Cockpit <ArrowRight size={14}/></button>}</div>}
            {preview && <div className="preview"><h4>Predicted effect, not observation</h4><div className="comparison"><div><small>BEFORE</small><strong>{preview.before ? 'Can read' : 'Denied'}</strong></div><ArrowRight size={18}/><div><small>AFTER</small><strong>{preview.after ? 'Can read' : 'Denied'}</strong></div></div><p>Would reveal {preview.visible_documents.map(d => d.title).join(', ') || 'nothing'} until {formatTime(preview.expires_at)}.</p><div className="replay-stat"><ShieldCheck size={16}/><span>{preview.counterfactual.checks} host-policy comparisons · {preview.counterfactual.unexpected_delta_count} unexpected effects · expiry replayed</span></div><span className={'pill ' + (preview.matches_saved_proposal ? 'good' : 'bad')}>{preview.matches_saved_proposal ? 'Matches saved proposal' : 'Preview changed'}</span><p className="tiny">{preview.limitations}</p></div>}
          </> : <p className="empty">Select a request to inspect its saved state.</p>}</div></div>
        </section>
        <section className="panel span-three host-panel"><div className="panel-heading"><div><p className="eyebrow">HOST APP</p><h2>Access & active grants</h2></div><LockKeyhole size={20}/></div><p className="muted">Reads use your signed-in identity: {session.user_id} ({session.role}). An admin or engineer's read does not prove contractor access. Switch to the contractor to check their actual access.</p><button className="secondary" disabled={!!busy} onClick={inspectHost}>Read as {session.user_id}</button>
          {hostDocuments && <ul className="doc-list">{hostDocuments.map(d => <li key={d.id}><FileText size={15}/>{d.title}</li>)}</ul>}
          {['admin', 'engineer'].includes(session.role) && <AccessInspector key={`${session.user_id}:${session.tenant_id}:${session.csrf_token}:${projectId}`} tenant={session.tenant_id} project={projectId} initialViewer={viewer} request={(path, options) => api(path, session, options)}/>}
          <div className="divider"/><div className="section-label"><h3>Active variations</h3><span className="count-badge">{activeVariations.length}</span></div>{activeVariations.length ? activeVariations.map(v => <div className="variation" key={v.id}><div><strong>{v.viewer_id}</strong><small>{v.project_id}<br/>Until {formatTime(v.expires_at)}</small></div><span className="pill good">active</span>{session.role === 'admin' && <RevokeReview key={`${session.csrf_token}:${v.id}`} variation={v} disabled={!!busy} request={(path, options) => api(path, session, options)} onChanged={async () => { if (sameSession(session, sessionRef.current)) { setNotice('Reviewed grant revoked. Other grants and roles remain unchanged.'); await refresh(session, true); } }}/>}</div>) : <p className="empty">No currently active variations in the loaded tenant state.</p>}
          <details className="variation-history"><summary>Past variations <span>{pastVariations.length}</span></summary><div className="history-scroll">{pastVariations.map(v => <div className="variation" key={v.id}><div><strong>{v.viewer_id}</strong><small>{v.project_id} · {formatTime(v.expires_at)}</small></div><span className={'pill ' + statusClass(v.state)}>{v.state}</span></div>)}</div></details><p className="tiny">Expiry display uses this device's clock. Host time and policy remain authoritative.</p>
        </section>
      </div>}
      {tab === 'engineering' && <div className="content-grid"><section className="panel span-one"><div className="panel-heading"><div><p className="eyebrow">BOUNDED CHANGE</p><h2>Work items</h2></div><Code2 size={20}/></div><div className="work-list">{engineering.length ? engineering.map(w => <button className={'work-item' + (engineeringDetail?.id === w.id ? ' selected' : '')} aria-pressed={engineeringDetail?.id === w.id} key={w.id} onClick={() => openEngineering(w.id)}><span className={'pill ' + statusClass(w.status)}>{w.status}</span><strong>PDF export request</strong><small>{w.request_id.slice(0,8)}</small></button>) : <p className="empty">A new feature request creates a work item here.</p>}</div></section>
        <section className="panel span-two"><div className="panel-heading"><div><p className="eyebrow">ENGINEER COCKPIT</p><h2>Patch, checks, decision</h2></div><ShieldCheck size={20}/></div>{engineeringDetail ? <><p>{engineeringDetail.request.text}</p><div className="facts"><div><small>STATE</small><strong>{engineeringDetail.status}</strong></div><div><small>PATCH HASH</small><strong className="hash-short">{engineeringDetail.patch_hash?.slice(0,16) || 'Not drafted'}</strong></div><div><small>RELEASE</small><strong>Not deployed</strong></div></div>
          {session.role !== 'engineer' && <p className="tiny">Read-only cockpit. Sign in as an engineer to edit, check or record a release decision.</p>}
          <div className="review-verdict"><span className={'pill ' + (engineeringDetail.current_checks_usable ? 'good' : 'neutral')}>{engineeringDetail.current_checks_usable ? 'Current external checks verified' : 'Current verification required'}</span><p>Saved hash checks: {currentPatchCheck(engineeringDetail.patch_hash, engineeringDetail.checks)}. Historical passes do not cover a changed patch, oracle or supervisor. The server must verify current provenance before acceptance.</p></div>
          <div className="button-row"><button className="secondary" disabled={session.role !== 'engineer' || !!busy || session.ai_mode === 'off' || inferenceBudget?.remaining_calls === 0 || !['needs_engineer','draft_failed'].includes(engineeringDetail.status)} onClick={() => engineeringAction('draft')}>Draft bounded patch</button><button className="secondary" disabled={session.role !== 'engineer' || !!busy || !['needs_engineer','draft_failed','drafting','checks_failed'].includes(engineeringDetail.status)} onClick={loadManualSource}>Write patch without AI</button><button className="secondary" disabled={session.role !== 'engineer' || !!busy || !['drafted','checks_failed','checks_passed'].includes(engineeringDetail.status)} onClick={() => engineeringAction('verify')}>Run isolated checks</button></div>
          {manualBase && <div className="manual-editor"><p className="tiny">Only {manualBase.path} can change. This source replaces the owned fixture in a disposable check environment, not the live app.</p><label>Complete replacement source<textarea value={manualSource} onChange={e => setManualSource(e.target.value)} rows={14} spellCheck={false}/></label><button className="primary" onClick={submitManualPatch} disabled={!!busy || manualSource === manualBase.source}>Save manual patch</button></div>}
          {engineeringDetail.patch && <PatchDiff key={engineeringDetail.patch_hash} path={engineeringDetail.patch.edits[0].path} before={engineeringDetail.patch.edits[0].old} after={engineeringDetail.patch.edits[0].new}/>}
          {engineeringDetail.checks.map((check, index) => <div className="check-result" key={index}><span className={'pill ' + (check.result.passed ? 'good' : 'bad')}>{check.result.passed ? 'checks passed' : 'checks failed'}</span><span className="tiny">{check.result.runner} · {check.subject_hash === engineeringDetail.patch_hash ? 'Current patch' : 'Historical patch, not the current candidate'} · {check.subject_hash.slice(0,16)}</span><details><summary>View check output</summary><pre>{check.result.stderr || check.result.stdout}</pre></details><p className="tiny">{check.limitation}</p></div>)}
          <BoundedRepair key={`${session.user_id}:${session.tenant_id}:${session.csrf_token}:${engineeringDetail.id}`} session={session} item={engineeringDetail} remainingCalls={inferenceBudget?.remaining_calls} parentBusy={!!busy} request={(path, options) => api(path, session, options)} onChanged={refreshAfterRepair}/>
          {!engineeringDetail.human_decision && <div className="button-row decision-row"><button className="primary" disabled={session.role !== 'engineer' || !!busy || engineeringDetail.status !== 'checks_passed' || !engineeringDetail.current_checks_usable} onClick={() => engineeringAction('decide', { decision: 'accept_for_manual_release', patch_hash: engineeringDetail.patch_hash })}>Accept for manual release</button><button className="secondary" disabled={session.role !== 'engineer' || !!busy} onClick={() => engineeringAction('decide', { decision: 'reject' })}>Reject</button><button className="secondary" disabled={session.role !== 'engineer' || !!busy} onClick={() => engineeringAction('decide', { decision: 'take_over' })}>Take over without AI</button></div>}
          {engineeringDetail.human_decision === 'accept_for_manual_release' && <button className="secondary" disabled={!!busy} onClick={downloadArtifact}>Download checked release handoff</button>}
          <p className="tiny">Acceptance records a decision. It does not merge or deploy code.</p></> : <div className="empty large">Choose a work item to inspect the real request, exact candidate code, independent checks, and limitations.</div>}</section></div>}
      {tab === 'convergence' && <div className="content-grid"><section className="panel span-three"><div className="panel-heading"><div><p className="eyebrow">PRODUCT DECISION</p><h2>Repeated needs, human choice</h2></div><Activity size={20}/></div><p className="muted">A convergence signal is not permission to change the shared product. Cross-tenant details are never shown here.</p>{convergence.map(c => <div className="convergence-card" key={c.need_key}><div><span className="pill neutral">CANDIDATE</span><h3>{c.need_key === 'pdf-export' ? 'PDF export' : 'Temporary project access'}</h3><p>{c.affected_tenant_count === null ? `${c.your_tenant_request_count} request(s) in your tenant` : `${c.affected_tenant_count} tenant(s) with this request`}. Current decision: {c.decision || 'none'}.</p>{c.observed_granted_reads !== null && <p>{c.observed_granted_reads} observed granted API read(s), {c.usage_scope === 'all_tenants' ? 'aggregate across tenants' : 'your tenant only'}.</p>}<p>{c.note}</p></div>{session.role === 'product_owner' && <div><label>Decision rationale<textarea maxLength={2000} value={rationales[c.need_key] || ''} onChange={e => setRationales({ ...rationales, [c.need_key]: e.target.value })}/></label><div className="button-row">{['promote','keep_separate','retire'].map(choice => <button className="secondary" disabled={!!busy || (rationales[c.need_key] || '').trim().length < 10} key={choice} onClick={() => decideConvergence(c.need_key, choice)}>{choice.replace('_',' ')}</button>)}</div></div>}</div>)}</section></div>}
      {tab === 'ledger' && <div className="content-grid"><section className="panel span-three"><div className="panel-heading"><div><p className="eyebrow">DURABLE EVENTS</p><h2>What actually happened</h2></div><FileText size={20}/></div>{['admin','engineer'].includes(session.role) && selected && <a className="secondary" href={`/v1/requests/${selected}/proof`} download>Export selected request proof</a>}<p className="tiny">Events for selected request: {selected || 'none'}. Export may contain private tenant text; review before sharing. Verify its digest offline; this is not a signed attestation or release.</p><div className="timeline">{visibleEvents.length ? visibleEvents.map(e => <div className="timeline-item" key={e.id}><div className="timeline-node"/><div><small>{formatTime(e.created_at)} · {e.request_id.slice(0,8)}</small><h3>{e.type}</h3><code>{JSON.stringify(e.payload)}</code></div></div>) : <p className="empty">No events yet.</p>}</div><h2>Observed host authorization</h2><p className="muted">Latest 500 tenant-local API checks. No previews. An allowed check is not proof a person received or used the response.</p><div className="timeline">{observations.map(o => <div className="timeline-item" key={o.id}><div className="timeline-node"/><small>{formatTime(o.observed_at)} · {o.actor_id}</small><h3>{o.allowed ? 'Allowed' : 'Denied'}: {o.action}</h3><code>{o.project_id} · {o.basis} · {o.variation_id || 'no variation'}</code></div>)}</div></section></div>}
      {tab === 'people' && session.role === 'admin' && <People key={`${session.user_id}:${session.csrf_token}`} request={(path, options) => api(path, session, options)}/>}
      <footer>OwnStack reference build · Synthetic customer data · Preview is not observation · A patch is not a release</footer>
    </main>
  </div>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
