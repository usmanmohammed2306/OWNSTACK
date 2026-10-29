import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Activity, ArrowLeft, ArrowRight, ArrowUpRight, CheckCircle2, Clock3, Code2, FileText, Fingerprint, Layers3, LockKeyhole, Search, ShieldCheck, XCircle, LayoutDashboard } from 'lucide-react';
import { ChangeScope } from './ChangeScope';
import { accessRequestText, changeStatus, changeTitle, personName, projectName } from './changePresentation';
import { requestLabel, hasApprovalHistory } from './workflowPresentation';
import { ProductSignals } from './ProductSignals';
import { WorkspaceHome } from './WorkspaceHome';
import { SpatialShell } from './SpatialShell';
import { observedNeedCount } from './spatialWorkspaceModel';
import type { SpatialRecord } from './spatialRecords';
import { AccountGate, type CustomerSession } from './AccountGate';
import { AccountSettings } from './WorkspaceAccounts';
import { RequestComposer } from './RequestComposer';
import { BoundaryInspector } from './BoundaryInspector';
import { PatchDiff } from './PatchDiff';
import { BoundedRepair } from './BoundedRepair';
import { ApprovalReview } from './ApprovalReview';
import { People } from './People';
import {Teams} from './Teams';
import { AccessInspector } from './AccessInspector';
import { RevokeReview } from './RevokeReview';
import { ProposalRefresh } from './ProposalRefresh';
import { Assurance } from './Assurance';
import { AgentProgress } from './AgentProgress';
import { AgentInvestigation } from './AgentInvestigation';
import {LocalAgentReview} from './LocalAgentReview';
import {RepositoryCockpit, type RepositoryReview} from './RepositoryCockpit';
import {ReleaseAssurance} from './ReleaseAssurance';
import {Organization} from './Organization';
import {RequestPatterns} from './RequestPatterns';
import {CodeReview} from './CodeReview';
import {ChangeAgent} from './ChangeAgent';
import {CustomerRepositoryRequest} from './CustomerRepositoryRequest';
import {CustomerPortal} from './CustomerPortal';
import './customer-workspace.css';
import { currentPatchCheck, effectiveVariationState, filterRequests, type RequestFilter } from './review';
import { sameProposal, sameSession, submissionForIntent, type PendingSubmission, type ProposalIdentity } from './responseIdentity';
import './studio.css';
import './calm-workspace.css';
import './agent-workspace.css';
import './spatial-workspace.css';
import './arctic-workspace.css';
import './agent-studio.css';
import './solid-workspace.css';
import './workspace-studio.css';
import './organization-workspace.css';

type Session = CustomerSession;
type Request = { id: string; requester_id?:string;team_id?:string; text: string; kind: string; project_id: string | null; viewer_id: string | null; expires_at: string | null; status: string; revision: number; current_attempt_id: string | null; accepted_proposal_id: string | null };
type Proposal = { id: string; route: string; reason: string; proposal_hash: string; preview_hash: string | null; status: string; contract_id: string | null; contract_version: number | null };
type Preview = { before: boolean; after: boolean; approval_quorum?:number; visible_documents: { id: string; title: string }[]; expires_at: string; snapshot_hash: string; matches_saved_proposal: boolean; limitations: string; counterfactual: { checks: number; intended_delta_observed: boolean; unexpected_delta_count: number } };
type Attempt = { id: string; number: number; state: string; model_id: string; error_code: string | null; latency_ms: number | null };
type Variation = { id: string; project_id: string; viewer_id: string; state: string; expires_at: string };
type Engineering = { id: string; request_id: string; status: string; patch_hash: string | null; human_decision: string | null;requested_by?:string;request_text?:string;thumbnail?:{path:string;code:string} };
type EngineeringDetail = { id: string; request: Request; status: string; patch: { edits: { path: string; old: string; new: string }[] } | null; patch_hash: string | null; human_decision: string | null; current_checks_usable: boolean; repository?: RepositoryReview | null; checks: { subject_hash: string; result: { passed: boolean; stdout: string; stderr: string; runner: string }; limitation: string }[] };
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
    const detail = typeof body.detail === 'string' ? body.detail : Array.isArray(body.detail)
      ? body.detail.map((item: {loc?: string[];msg?: string}) => `${item.loc?.slice(1).join(' ') || 'Request'}: ${item.msg || 'Invalid value'}`).join('. ')
      : typeof body.detail?.message==='string'?body.detail.message:response.statusText;
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}
function formatTime(value: string | null) { return value ? new Date(value).toLocaleString() : 'Not set'; }
function accessPrompt(tenant: string) { return ['atlas','nova'].includes(tenant) ? `Give ${tenant}-contractor read-only access to Project ${tenant === 'nova' ? 'Nova' : 'Atlas'} until the selected expiry.` : 'Give a teammate read-only access to this project until the selected expiry.'; }
function statusClass(value: string) { return ['active', 'accepted', 'checks_passed', 'approved'].includes(value) ? 'good' : ['failed', 'refused', 'checks_failed', 'revoked', 'expired'].includes(value) ? 'bad' : 'neutral'; }

function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [restoring, setRestoring] = useState(true);
  const sessionRef = useRef<Session | null>(null);
  sessionRef.current = session;
  const [tab, setTab] = useState<'journey' | 'access' | 'engineering' | 'convergence' | 'ledger' | 'demo' | 'people' | 'assurance' | 'account'>('demo');
  const [homeReset,setHomeReset]=useState(0),[organizationInitial,setOrganizationInitial]=useState<'people'|'access'>('people'),[engineeringTools,setEngineeringTools]=useState(false);
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
  const [organization,setOrganization]=useState<{nodes:SpatialRecord[];as_of:string;truncated:boolean}|null>(null);
  const [mapSelection,setMapSelection]=useState<SpatialRecord|null>(null);
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
  const [requestProject,setRequestProject]=useState('');
  const [requestFocused, setRequestFocused] = useState(false);
  const [repositoryRequest,setRepositoryRequest]=useState<string|null>(null);
  const [viewer, setViewer] = useState('atlas-contractor');
  const [expiry, setExpiry] = useState(() => { const date = new Date(Date.now() + 2 * 86400000); return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16); });
  const [busy, setBusy] = useState('');
  const [requestAgentState,setRequestAgentState]=useState<'idle'|'working'|'review'|'error'>('idle');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [query, setQuery] = useState('');
  const [requestFilter, setRequestFilter] = useState<RequestFilter>('all');
  const [lastSync, setLastSync] = useState<number | null>(null);
  const [syncFailed, setSyncFailed] = useState(false);
  const pageHeading = useRef<HTMLHeadingElement>(null);
  const workspaceElement = useRef<HTMLElement>(null);
  const detailHeading = useRef<HTMLHeadingElement>(null);
  const current = useMemo(() => requests.find(r => r.id === selected) || null, [requests, selected]);
  const previewIsHistorical = hasApprovalHistory(current?.status || '', proposal?.status);
  const proposalIdentity: ProposalIdentity | null = session && current && proposal && current.accepted_proposal_id === proposal.id
    ? { session, requestId: current.id, proposalId: proposal.id, proposalHash: proposal.proposal_hash } : null;
  proposalIdentityRef.current = proposalIdentity;
  const preview = sameProposal(previewRecord?.identity || null, proposalIdentity) ? previewRecord!.data : null;
  const filteredRequests = useMemo(() => filterRequests(requests.map(request => ({ ...request, status: changeStatus(request) })), query, requestFilter), [requests, query, requestFilter]);
  const effectiveVariations = variations.map(v => ({ ...v, state: effectiveVariationState(v.state, v.expires_at, Date.now()) }));
  const activeVariations = effectiveVariations.filter(v => v.state === 'active');
  const pastVariations = effectiveVariations.filter(v => v.state !== 'active');
  const shownActiveGrants=mapSelection?.station==='access'?activeVariations.filter(v=>'grant:'+v.id===mapSelection.id):activeVariations;
  const shownPastGrants=mapSelection?.station==='access'?pastVariations.filter(v=>'grant:'+v.id===mapSelection.id):pastVariations;
  const visibleEvents = events.filter(event => !selected || event.request_id === selected);
  const projectId = session?.project_id || (session?.tenant_id === 'nova' ? 'nova-project' : session?.tenant_id === 'atlas' ? 'atlas-project' : '');
  const navigation = [
    { id: 'demo' as const, label: 'New request', description: 'Describe the outcome. Your agent will find the path.', icon: LayoutDashboard, allowed: true },
    { id: 'journey' as const, label: session?.role === 'contractor' ? 'Your project' : 'Requests', description: session?.role === 'contractor' ? 'Documents available to your account.' : 'Prepare, preview, then approve.', icon: Layers3, allowed: session?.role !== 'product_owner' },
    { id: 'access' as const, label: 'Access', description: 'Current grants and access checks.', icon: LockKeyhole, allowed: ['admin', 'engineer', 'member','manager'].includes(session?.role || '') },
    { id: 'engineering' as const, label: 'Code review', description: 'Review code and checks before a human decision.', icon: Code2, allowed: ['admin', 'engineer','manager'].includes(session?.role || '') },
    { id: 'convergence' as const, label: 'Product signals', description: 'Find repeated needs. Decide what belongs in the product.', icon: Activity, allowed: ['admin', 'engineer', 'product_owner','manager'].includes(session?.role || '') },
    { id: 'ledger' as const, label: 'Activity', description: 'Saved events and actual host checks.', icon: FileText, allowed: !['contractor', 'product_owner'].includes(session?.role || '') },
    { id: 'people' as const, label: 'People', description: 'Teams and workspace access.', icon: LockKeyhole, allowed: ['admin','manager','engineer'].includes(session?.role||'') },
    { id: 'assurance' as const, label: session?.release_assurance_enabled?'Release checks':'Assurance', description: 'Reviewed requirements and saved checks.', icon: ShieldCheck, allowed: ['admin', 'engineer','manager'].includes(session?.role || '') },
    { id: 'account' as const, label: 'Your account', description: 'Your identity and passphrase.', icon: LockKeyhole, allowed: true },
  ].filter(item => item.allowed);
  function navigate(target: typeof tab) { setError(''); setNotice('');
    if(target==='access'||target==='people'){setOrganizationInitial(target==='access'?'access':'people');setTab('people');return;}
    if(target==='convergence'&&sessionRef.current?.role!=='product_owner')target='journey';
    setTab(target);if(target==='journey')setRequestFocused(false);
    if(target==='engineering'){engineeringIdRef.current=null;setEngineeringDetail(null);setEngineeringTools(false);}
  }
  function home(){navigate('demo');setHomeReset(n=>n+1);}
  useEffect(() => { window.scrollTo({ top: 0, behavior: 'instant' }); pageHeading.current?.focus({ preventScroll: true }); }, [tab]);
  useEffect(() => {
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const animation = workspaceElement.current?.animate?.([{ opacity: .7, transform: 'translateY(5px)' }, { opacity: 1, transform: 'translateY(0)' }], { duration: 220, easing: 'cubic-bezier(.2,.7,.2,1)' });
    return () => animation?.cancel();
  }, [tab, requestFocused]);
  useEffect(() => { if (requestFocused) detailHeading.current?.focus(); }, [requestFocused, current?.id]);

  function clearWorkspace() {
    refreshGeneration.current++; requestGeneration.current++; engineeringGeneration.current++; previewGeneration.current++;
    choose(null); engineeringIdRef.current = null; proposalIdentityRef.current = null; pendingSubmission.current = null;
    setRequests([]); setVariations([]); setEvents([]); setEngineering([]); setEngineeringDetail(null);setOrganization(null);setMapSelection(null);
    setConvergence([]); setObservations([]); setInferenceBudget(null); setAttempts([]); setProposal(null);
    setPreviewRecord(null); setHostDocuments(null); setManualBase(null); setManualSource(''); setRationales({}); setRequestOpen(false);
    setLastSync(null); setSyncFailed(false); setRequestFocused(false);
  }

  async function refresh(activeSession = sessionRef.current, force = false) {
    if (!activeSession || !sameSession(activeSession, sessionRef.current) || (refreshInFlight.current !== null && !force)) return;
    const generation = ++refreshGeneration.current;
    refreshInFlight.current = generation;
    const isCurrent = () => generation === refreshGeneration.current && sameSession(activeSession, sessionRef.current);
    try {
      const fresh=await api<Session>('/v1/session',activeSession);
      if(!isCurrent())return;
      if(!sameSession(fresh,activeSession)){
        acceptSession(fresh);setNotice('Your team access changed. Saved views were cleared.');
        void refresh(fresh,true);return;
      }
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
      // A member can submit requests but cannot read engineering, budget or audit diagnostics.
      const diagnostics = ['admin', 'engineer','manager'].includes(activeSession.role);
      // Apply a complete refresh together. A failed collection request keeps the saved view intact.
      const [r, v, ev, eng, conv, budget, observed,org] = await Promise.all([
        api<Request[]>('/v1/requests', activeSession), api<Variation[]>('/v1/variations', activeSession),
        api<Event[]>('/v1/events', activeSession), diagnostics ? api<Engineering[]>('/v1/engineering', activeSession) : Promise.resolve([]),
        diagnostics ? api<Convergence[]>('/v1/convergence', activeSession) : Promise.resolve([]), ['admin','engineer'].includes(activeSession.role) ? api<InferenceBudget>('/v1/inference-budget', activeSession) : Promise.resolve(null),
        diagnostics ? api<HostObservation[]>('/v1/host-observations', activeSession) : Promise.resolve([]),
        diagnostics ? api<{nodes:SpatialRecord[];as_of:string;truncated:boolean}>('/v1/workspace-map',activeSession) : Promise.resolve(null),
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
      setRequests(r); setVariations(v); setEvents(ev); setEngineering(eng); setConvergence(conv);setOrganization(org);
      if(engineeringDetailRef.current&&!eng.some(row=>row.id===engineeringDetailRef.current?.id)){
        engineeringGeneration.current++;engineeringIdRef.current=null;setEngineeringDetail(null);setManualBase(null);setManualSource('');setMapSelection(null);
      }
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
      if(err instanceof ApiError&&[403,404].includes(err.status))clearWorkspace();
      if (err instanceof ApiError && err.status === 401) { sessionRef.current = null; setSession(null); clearWorkspace(); }
      // Retrying connection status clears on refresh success. Mutation/review
      // errors have their own lifetime and must not be cleared by a poll.
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
  useEffect(() => { void refresh(session, true); setViewer(session && ['atlas','nova'].includes(session.tenant_id) ? `${session.tenant_id}-contractor` : ''); setRequestText(accessPrompt(session?.tenant_id || 'atlas')); }, [session?.csrf_token,session?.scope_version]);
  useEffect(() => {
    if (!session || session.role === 'contractor') return;
    const timer = setInterval(() => { void refresh(); }, 3000);
    return () => clearInterval(timer);
  }, [session?.csrf_token,session?.scope_version,session?.role]);

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

  function acceptSession(next: Session) {
    clearWorkspace(); setError(''); setNotice(''); sessionRef.current = next; setSession(next);setRequestProject(next.project_id||''); setTab('demo'); setQuery(''); setRequestFilter('all');
  }

  async function createRequest() {
    if (!session || !sameSession(session, sessionRef.current)) return;
    const activeSession = session;
    await action('create request', async () => {
      const body = { text: requestText, kind, project_id: requestProject||projectId, viewer_id: kind === 'access' ? viewer : null,
        expires_at: kind === 'access' ? new Date(expiry).toISOString() : null };
      const intent = JSON.stringify(body);
      const submission = submissionForIntent(pendingSubmission.current, intent, idempotency);
      pendingSubmission.current = submission;
      const result = await api<{ id: string }>('/v1/requests', activeSession, { method: 'POST', headers: { 'Idempotency-Key': submission.key }, body: intent });
      if (!sameSession(activeSession, sessionRef.current)) return;
      if (pendingSubmission.current === submission) pendingSubmission.current = null;
      requestGeneration.current++; previewGeneration.current++;
      choose(result.id); setProposal(null); setPreviewRecord(null); setRequestOpen(false); navigate('journey'); setRequestFocused(true);
      setNotice('Request saved. Start the agent when you’re ready.');
    });
  }

  async function interpret() {
    if (!current || !session) return;
    const activeSession = session, requestId = current.id;
    await action('interpret', async () => {
      const result = await api<{ status: string; attempt_id: string }>(`/v1/requests/${requestId}/interpret`, activeSession, { method: 'POST' });
      if (sameSession(activeSession, sessionRef.current) && selectedRef.current === requestId) setNotice(result.status === 'accepted' ? 'Your proposal is saved.' : 'The agent is preparing your proposal. You can leave and return.');
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
      const outcome=await api<{status:string}>(`/v1/proposals/${identity.proposalId}/approve`, session, { method: 'POST', headers: { 'Idempotency-Key': idempotency() }, body: JSON.stringify({ proposal_hash: identity.proposalHash }) });
      if (sameSession(identity.session, sessionRef.current) && selectedRef.current === identity.requestId) setNotice(outcome.status==='awaiting_second_approval'?'Your review is saved. A different administrator must approve before access changes.':'Access approved for this person, project and end time.');
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
    setEngineeringTools(!item.patch_hash);
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
    setRequestFocused(true);
    setNotice(''); setError('');
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

  const agentPanel = session && current && ['admin', 'engineer'].includes(session.role) ? session.ai_mode==='off'?<LocalAgentReview key={`local:${session.csrf_token}:${current.id}:${current.revision}`} id={current.id} revision={current.revision} onState={setRequestAgentState} request={(path,options)=>api(path,session,options)} prepared={async()=>{await refresh(session,true);await selectRequest(current.id);}}/>:<AgentInvestigation key={`investigate:${session.csrf_token}:${current.id}:${current.revision}`} scope={{ tenant: session.tenant_id, request: current.id, revision: current.revision }} mode={session.ai_mode} remainingCalls={inferenceBudget?.remaining_calls} request={(path, options) => api(path, session, options)} onPrepare={() => void interpret()} preparing={!!busy || current.status === 'interpreting'} allowPrepare={!current.accepted_proposal_id} prepared={!!current.accepted_proposal_id} feature={current.kind === 'feature'}/> : null;

  if (!session) return <SpatialShell key="signed-out" role="guest" tenant="platform" focus="demo" counts={{}} navigate={() => {}}>
    <AccountGate ready={!restoring} request={(path, options) => api(path, null, options)} signedIn={acceptSession}/>
  </SpatialShell>;

  const spatialItems:SpatialRecord[]=[...(organization?.nodes||[
    {id:'role:'+session.role,station:'demo' as const,title:session.role.replaceAll('_',' '),description:'Your workspace role',status:'role',kind:'role',parent:'organization'},
    {id:'person:'+session.user_id,station:'demo' as const,title:session.display_name||session.user_id,description:session.role.replaceAll('_',' '),status:'signed in',kind:'person',parent:'role:'+session.role}]),
    ...navigation.filter(n=>['ledger','assurance'].includes(n.id)).map(n=>({id:'action:'+n.id,station:(n.id==='assurance'?'engineering':'journey') as 'engineering'|'journey',title:n.id==='assurance'?'Checks & evidence':n.label,description:n.description,status:'Tool',kind:'action'})),
    ...(session.role==='contractor'?[{id:'action:journey',station:'journey' as const,title:session.project_name||'Your project',description:'Open the documents your account can access',status:'Protected read',kind:'action'}]:[]),
    ...requests.map(r=>({id:'request:'+r.id,station:'journey' as const,title:r.text.slice(0,60),description:r.text,status:changeStatus(r),by:r.requester_id?`Requested by ${personName(r.requester_id)}`:undefined,related:r.requester_id?['person:'+r.requester_id]:[]})),
    ...engineering.map(w=>({id:'code:'+w.id,station:'engineering' as const,title:w.thumbnail?.path.split('/').pop()||'Feature request',description:w.request_text||'Saved engineering work',status:w.status,by:w.requested_by?`Requested by ${personName(w.requested_by)}`:undefined,code:w.thumbnail?.code,path:w.thumbnail?.path,related:['request:'+w.request_id]})),
    ...variations.map(v=>({id:'grant:'+v.id,station:'access' as const,title:personName(v.viewer_id),description:`${projectName(v.project_id)} · ${formatTime(v.expires_at)}`,status:effectiveVariationState(v.state,v.expires_at,Date.now()),related:['person:'+v.viewer_id]})),
    ...convergence.filter(r=>(r.your_tenant_request_count||r.affected_tenant_count||0)>0).map(r=>({id:'pattern:'+r.need_key,station:'convergence' as const,title:r.need_key==='pdf-export'?'PDF export':'Temporary access',description:`${session.role==='product_owner'?r.affected_tenant_count:r.your_tenant_request_count} ${session.role==='product_owner'?'workspaces':'saved requests'}`,status:r.decision||'Review needed',related:requests.filter(q=>r.need_key==='pdf-export'?q.kind==='feature'&&q.text.toLowerCase().includes('pdf'):q.kind==='access').map(q=>'request:'+q.id)})),
  ];

  return <SpatialShell key={`${session.user_id}:${session.csrf_token}:${session.scope_version}`} role={session.role} user={session.user_id} tenant={session.tenant_id} workspaceName={session.workspace_name} focus={tab}
    homeReset={homeReset}
    requestAgentState={requestAgentState}
    planCommand={session.role==='manager'?undefined:{start:(text,key,signal)=>api('/v1/agent/planner',session,{method:'POST',body:JSON.stringify({text}),headers:{'Idempotency-Key':key},signal}),
      read:(key,signal)=>api('/v1/agent/planner/saved/'+encodeURIComponent(key),session,{signal}),
      retry:(id,generation,signal)=>api(`/v1/agent/planner/${id}/retry`,session,{method:'POST',body:JSON.stringify({generation}),signal}),
      cancel:(text,key,generation)=>api('/v1/agent/planner/cancel-command',session,{method:'POST',body:JSON.stringify({text,generation}),headers:{'Idempotency-Key':key}})}}
    draftRequest={(preset,text)=>{setKind(preset);setRequestProject(projectId);setRequestText(text);setRequestOpen(true);}}
    items={spatialItems} mapAsOf={organization?.as_of} mapTruncated={organization?.truncated}
    refreshMap={()=>refresh(session,true)}
    openTeams={['admin','engineer','manager'].includes(session.role)?()=>navigate('people'):undefined}
    inspectItem={item=>{setMapSelection(item);if(item.kind==='action'){const dest=navigation.find(n=>n.id===item.id.slice(7));if(dest)navigate(dest.id);}else if(item.station==='engineering'){navigate('engineering');void openEngineering(item.id.slice(5));}else if(item.station==='journey'){setQuery('');setRequestFilter('all');navigate('journey');void selectRequest(item.id.slice(8));}else navigate(item.station);}}
    counts={{ journey: lastSync && !['contractor', 'product_owner'].includes(session.role) ? requests.length : null,
      access: lastSync && ['admin', 'engineer', 'member'].includes(session.role) ? activeVariations.length : null,
      engineering: lastSync && ['admin', 'engineer'].includes(session.role) ? engineering.length : null,
      convergence: lastSync && ['admin', 'engineer', 'product_owner'].includes(session.role) ? observedNeedCount(session.role, convergence) : null }} navigate={navigate}>
    <div className="app-shell"><a className="skip-link" href="#workspace-main">Skip to workspace</a>
    <aside className="sidebar"><button className="brand" aria-label="OwnStack home" onClick={home}><span className="brand-mark"><Layers3 size={22}/></span><span>OwnStack</span></button>
      <div className="workspace-switch"><span className="avatar">{session.tenant_id.slice(0,1).toUpperCase()}</span><span>{session.tenant_id === 'platform' ? 'Platform' : session.tenant_id[0].toUpperCase() + session.tenant_id.slice(1)}<small>Workspace</small></span></div>
      <div className="sidebar-bottom"><details className="account-details" onKeyDown={event=>{if(event.key==='Escape'){event.currentTarget.open=false;event.currentTarget.querySelector('summary')?.focus();}}}><summary aria-label={`Account menu for ${personName(session.display_name || session.user_id)}`}><span className="avatar">{(session.display_name || session.user_id).slice(0,1).toUpperCase()}</span><span>{personName(session.display_name || session.user_id)}<small>{session.role === 'admin' ? 'Administrator' : session.role.replaceAll('_', ' ')}</small></span></summary><div className="account-actions"><button className="text-button" aria-label="Account settings" onClick={event=>{event.currentTarget.closest('details')?.removeAttribute('open');navigate('account');}}>Account settings</button><button className="text-button" aria-label="Sign out" disabled={!!busy} onClick={signOut}>Sign out</button><details><summary>Service details</summary><p className="tiny">Account: {session.user_id}</p><p className="tiny">{session.ai_mode === 'nebius' ? 'Request provider: Nebius · NVIDIA Nemotron' : session.ai_mode === 'off' ? 'Remote request generation is paused. The local trained planner is separate.' : 'Synthetic test environment, not live provider AI.'}</p>{inferenceBudget && <p className="tiny">{inferenceBudget.remaining_calls ?? 0} approved provider calls remaining.</p>}</details></div></details></div>
    </aside>
    <main ref={workspaceElement} className={tab === 'demo' ? 'main main--home' : 'main'} id="workspace-main"><header className="topbar"><h1 ref={pageHeading} tabIndex={-1}>{tab==='people'?'Organization':tab==='journey'||tab==='convergence'?'Requests':tab==='engineering'?'Code review':tab==='account'?'Your account':tab==='assurance'?'Release checks':tab==='ledger'?'Activity':'Workspace'}</h1>
        {tab!=='demo'&&<button className="inspection-close" aria-label={tab==='journey'&&requestFocused?'Back to requests':tab==='engineering'&&engineeringDetail?'Back to code reviews':'Back to home'} onClick={()=>{if(tab==='journey'&&requestFocused)setRequestFocused(false);else if(tab==='engineering'&&engineeringDetail){engineeringIdRef.current=null;setEngineeringDetail(null);setEngineeringTools(false);}else home();}}><ArrowLeft size={16}/><span>Back</span></button>}
      </header>
      {syncFailed && <div className="alert error" role="status">Could not refresh. Displayed records may be out of date.</div>}
      {error && <div className="alert error" role="alert"><XCircle size={16}/>{error}<button onClick={() => setError('')}>Dismiss</button></div>}
      {notice && <div className="alert notice" role="status"><CheckCircle2 size={16}/>{notice}<button onClick={() => setNotice('')}>Dismiss</button></div>}
      {busy && <div className="alert notice" role="status"><Clock3 size={16}/>Working on {busy}…</div>}
      <RequestComposer open={requestOpen} close={() => setRequestOpen(false)} kind={kind} setKind={setKind} text={requestText} setText={setRequestText} project={requestProject||projectId} projectLabel={session.projects?.find(p=>p.id===(requestProject||projectId))?.name||session.project_name} projects={session.projects} setProject={setRequestProject} viewer={viewer} setViewer={setViewer} expiry={expiry} setExpiry={setExpiry} busy={!!busy} error={error} save={createRequest}/>
      <div hidden={tab !== 'demo'}><WorkspaceHome tenant={session.tenant_id} workspaceName={session.workspace_name} role={session.role} requests={requests} loaded={!!lastSync} navigate={navigate} newRequest={(preset, text) => { setError(''); if (preset) { setKind(preset); setRequestText(text || (preset === 'access' ? accessPrompt(session.tenant_id) : 'Add PDF export for this project.')); } setRequestOpen(true); }} selectRequest={id => { setQuery(''); setRequestFilter('all'); navigate('journey'); void selectRequest(id); }}/></div>
      {tab === 'journey' && session.role === 'contractor' && <div className="content-grid"><section className="panel span-three"><div className="panel-heading"><div><p className="eyebrow">YOUR PROJECT</p><h2>Project documents</h2></div><LockKeyhole size={20}/></div><p className="muted">Open the documents your account can access.</p><button className="secondary" onClick={inspectHost}>Open documents</button>{hostDocuments && <ul className="doc-list">{hostDocuments.map(d => <li key={d.id}><FileText size={15}/>{d.title}</li>)}</ul>}</section></div>}
      {tab === 'journey' && session.role !== 'contractor' && session.role !== 'product_owner' && <div className="content-grid">
        <section className="panel span-three request-workspace">{!requestFocused && <><div className="panel-heading"><h2>Your requests</h2><button className="primary" disabled={!!busy} onClick={() => setRequestOpen(true)}>New request <ArrowRight size={16}/></button></div>
          <div className="request-tools"><label className="request-search"><Search size={16}/><input aria-label="Search requests" placeholder="Find a request…" value={query} onChange={e => setQuery(e.target.value)}/></label><label className="filter-label">Show<select aria-label="Filter requests" value={requestFilter} onChange={e => setRequestFilter(e.target.value as RequestFilter)}><option value="all">All requests</option><option value="attention">Needs attention</option><option value="active">Active</option><option value="closed">Closed / refused</option></select></label><span className="tiny">{filteredRequests.length} of {requests.length} requests</span></div>
          <div className="request-list request-gallery">{filteredRequests.length ? filteredRequests.map(r => <button key={r.id} title={r.text} aria-label={`Open request: ${r.text}`} className={selected === r.id ? 'request-item selected' : 'request-item'} onClick={() => { void selectRequest(r.id); }}><span className={`mini-object ${r.kind === 'feature' ? 'mini-code' : 'mini-key'}`}>{r.kind === 'feature' ? <Code2 size={22}/> : <LockKeyhole size={22}/>}</span><span className={'pill ' + statusClass(changeStatus(r))}>{session.release_assurance_enabled&&r.kind==='feature'?'Customer change':requestLabel(changeStatus(r))}</span><strong>{changeTitle(r.kind)}</strong><small>{r.text} <ArrowUpRight size={12}/></small></button>) : <p className="empty">{requests.length ? 'No matching requests.' : 'No requests yet. Create your first request.'}</p>}</div></>}
          {requestFocused && <div className="request-detail">{current ? <><div className="detail-top"><span className="eyebrow">{projectName(current.project_id)}</span><span className={'pill ' + statusClass(changeStatus(current))}>{session.release_assurance_enabled&&current.kind==='feature'?'Customer change':requestLabel(changeStatus(current))}</span></div><h3 ref={detailHeading} tabIndex={-1}>{changeTitle(current.kind)}</h3>
            <p className="customer-request">{current.text}</p>
            <RequestPatterns key={`${session.csrf_token}:${current.id}:${current.revision}`} id={current.id} revision={current.revision} role={session.role} request={(path,options)=>api(path,session,options)} changed={async()=>{if(sameSession(session,sessionRef.current)&&selectedRef.current===current.id){setPreviewRecord(null);await refresh(session,true);await selectRequest(current.id);}}}/>
            {session.release_assurance_enabled&&current.kind==='feature'&&['admin','engineer','manager'].includes(session.role)&&<CustomerRepositoryRequest key={`agent:${session.csrf_token}:${current.id}:${current.revision}`} requestId={current.id} projectId={current.project_id||''} role={session.role} aiMode={session.ai_mode} request={(path,options)=>api(path,session,options)} onConnected={connected=>setRepositoryRequest(old=>connected?current.id:old===current.id?null:old)} openReview={id=>{navigate('engineering');void openEngineering(id);}}/>}
            {current.kind === 'access' && <ChangeScope project={current.project_id} viewer={current.viewer_id} expiry={current.expires_at}/>}
            {!(session.release_assurance_enabled&&current.kind==='feature')&&(agentPanel ? current.accepted_proposal_id ? <details className="request-advanced agent-archive"><summary>Agent activity</summary>{agentPanel}</details> : agentPanel
              : !current.accepted_proposal_id && <p className="muted">Your workspace admin or engineer can investigate this request.</p>)}
            {proposal && !(proposal.route==='engineering'&&repositoryRequest===current.id) && <div className="proposal"><div className="proposal-head"><h4>{proposal.route === 'configure' ? proposal.status === 'ready' ? 'Ready for your review' : changeStatus(current) === 'expired' ? 'This access has ended' : current.status === 'revoked' ? 'This access was revoked' : 'Access approved' : proposal.route === 'engineering' ? 'This change needs code' : 'This request needs a different approach'}</h4><ShieldCheck size={19}/></div>
              {proposal.route === 'refuse' && <p>{proposal.reason}</p>}
              {session.role === 'member' && (proposal.status === 'ready' || proposal.route === 'engineering') && <p className="muted">{proposal.route === 'engineering' ? 'Your engineering team reviews this change.' : 'Your workspace administrator reviews this access.'}</p>}
              {proposal.route === 'configure' && proposal.status === 'ready' && ['admin', 'engineer'].includes(session.role) && <div className="button-row">{!preview ? <button className="primary" disabled={!!busy} onClick={previewProposal}>Preview access <ArrowRight size={15}/></button> : <ApprovalReview key={`${proposal.proposal_hash}:${preview?.snapshot_hash}`} enabled={!!preview?.matches_saved_proposal && proposal.status === 'ready' && session.role === 'admin'} busy={!!busy} admin={session.user_id} project={current.project_id} viewer={current.viewer_id} proposalHash={proposal.proposal_hash} contract={proposal.contract_id} version={proposal.contract_version} preview={preview} approve={approveProposal}/>}</div>}
              {proposal.route === 'configure' && proposal.status !== 'ready' && <button className="secondary" onClick={() => navigate('access')}>View access<ArrowRight size={15}/></button>}
              {proposal.route === 'engineering' && ['admin', 'engineer'].includes(session.role) && <button className="primary" onClick={() => inspectEngineeringRequest(current.id)}>Review code <ArrowRight size={14}/></button>}</div>}
            {preview && <div className="preview"><h4>{previewIsHistorical ? 'Saved access preview' : 'Access preview'} <span className="tiny">{previewIsHistorical ? 'Snapshot, not current access' : 'Not active yet'}</span></h4><div className="comparison"><div><small>NOW</small><strong>{preview.before ? 'Can read' : 'No access'}</strong></div><ArrowRight size={18}/><div><small>IF APPROVED</small><strong>{preview.after ? 'Can read' : 'No access'}</strong></div></div><p>{preview.visible_documents.map(d => d.title).join(', ') || 'No documents'} · until {formatTime(preview.expires_at)}</p>{!preview.matches_saved_proposal && <p className="alert error">The preview has changed. Refresh before approval.</p>}<details><summary>Checks & limitations</summary><p className="tiny">{preview.counterfactual.checks} comparisons · {preview.counterfactual.unexpected_delta_count} unexpected effects.</p><p className="tiny">{preview.limitations}</p></details>{!previewIsHistorical && <button className="text-button" disabled={!!busy} onClick={previewProposal}>Refresh preview</button>}</div>}
            <details className="request-advanced"><summary>Details & recovery</summary>
            {!current.accepted_proposal_id && <details className="technical-disclosure"><summary>Other ways to prepare</summary>
            {!current.accepted_proposal_id && session.ai_mode === 'off' && <div className="manual-guidance"><Code2 size={18}/><p>{session.role === 'engineer' ? current.kind === 'feature' ? 'Prepare this code change manually, then check and review the exact patch.' : 'Prepare this access proposal manually. Admin approval is still required.' : 'An engineer can take over if the agent cannot prepare this change.'}</p></div>}
            {!current.accepted_proposal_id && ['admin', 'engineer'].includes(session.role) && session.ai_mode !== 'off' && <button className="primary" onClick={interpret} disabled={!!busy || inferenceBudget?.remaining_calls === 0 || current.status === 'interpreting'}>{current.status === 'interpreting' ? 'Worker processing…' : inferenceBudget?.remaining_calls === 0 ? 'Approved call limit reached' : 'Prepare proposal with AI'} <ArrowRight size={16}/></button>}
            {current.status === 'interpreting' && <button className="secondary" disabled={!!busy} onClick={() => action('cancel local attempt', async () => { await api(`/v1/requests/${current.id}/cancel`, session, { method: 'POST' }); setNotice('Local attempt canceled. Remote inference cancellation is unverified.'); })}>Cancel local attempt</button>}
            {!current.accepted_proposal_id && session.role === 'engineer' && ['new','failed','refused'].includes(current.status) && <button className="primary" onClick={manualHandoff} disabled={!!busy}>Prepare without AI <ArrowRight size={16}/></button>}
            </details>}
            <details className="technical-disclosure" key={`technical:${current.id}:${current.revision}`}><summary><Fingerprint size={15}/> Evidence & technical details</summary>
            <div className="hash-line"><span>Request · revision {current.revision}</span><code>{current.id}</code></div>
            {['admin', 'engineer'].includes(session.role) && <BoundaryInspector request={current} proposal={proposal} preview={preview} events={events} observations={observations} openLedger={() => navigate('ledger')}/>}
            {current.current_attempt_id && current.project_id && ['admin', 'engineer'].includes(session.role) &&
              <AgentProgress key={`${session.csrf_token}:${current.id}:${current.revision}:${current.current_attempt_id}`}
                scope={{ tenant_id: session.tenant_id, request_id: current.id, project_id: current.project_id,
                  attempt_id: current.current_attempt_id, revision: current.revision }}
                request={(path, signal) => fetch(path, { signal, credentials: 'same-origin', headers: { Accept: 'text/event-stream' } })}/>}
            {!!attempts.length && <details className="attempts"><summary>Saved attempts ({attempts.length})</summary>{attempts.map(a => <div className="attempt" key={a.id}><Clock3 size={14}/><span>#{a.number} {a.model_id}</span><span className={'pill ' + statusClass(a.state)}>{a.state}</span>{a.error_code && <small>{a.error_code}</small>}</div>)}</details>}
            {proposal && <div className="hash-line"><span>Exact proposal · {proposal.contract_id || proposal.route} {proposal.contract_version ? `v${proposal.contract_version}` : ''}</span><code>{proposal.proposal_hash}</code><p>{proposal.reason}</p></div>}
            </details>
            {proposal?.route === 'configure' && proposal.status === 'ready' && ['admin', 'engineer'].includes(session.role) &&
              <details className="technical-disclosure"><summary>Host data changed?</summary><ProposalRefresh key={`${session.csrf_token}:${proposal.id}:${current.revision}`} disabled={!!busy} canRefresh={session.role === 'engineer'}
                identity={{ actor: session.user_id, tenant: session.tenant_id, requestId: current.id, revision: current.revision, proposalId: proposal.id, proposalHash: proposal.proposal_hash }}
                request={(path, options) => api(path, session, options)} onChanged={async () => {
                  if (sameSession(session, sessionRef.current) && selectedRef.current === current.id) {
                    setPreviewRecord(null); setNotice('New proposal revision saved without AI. Fresh admin preview and approval are required.'); await refresh(session, true);
                  }
                }}/></details>}
            </details>
          </> : <p className="empty">Loading this request…</p>}</div>}
        </section>
      </div>}
      {tab === 'access' && ['admin', 'engineer', 'member'].includes(session.role) && <div className="content-grid">
        <section className="panel span-three host-panel"><div className="panel-heading"><h2>Workspace access</h2><LockKeyhole size={20}/></div>
          <details className="technical-disclosure"><summary>Test a protected read</summary><p className="muted">Reads use {session.user_id}, not the contractor. Sign in as the contractor to test their actual access.</p><button className="secondary" disabled={!!busy} onClick={inspectHost}>Read as {session.user_id}</button>
          {hostDocuments && <ul className="doc-list">{hostDocuments.map(d => <li key={d.id}><FileText size={15}/>{d.title}</li>)}</ul>}
          </details>
          {['admin', 'engineer'].includes(session.role) && <details className="technical-disclosure"><summary>Check someone’s access</summary><AccessInspector key={`${session.user_id}:${session.tenant_id}:${session.csrf_token}:${projectId}`} tenant={session.tenant_id} project={projectId} initialViewer={viewer} request={(path, options) => api(path, session, options)}/></details>}
          <div className="divider"/><div className="section-label"><h3>Active grants</h3><span className="count-badge">{shownActiveGrants.length}</span></div>{shownActiveGrants.length ? shownActiveGrants.map(v => <div className="variation" key={v.id}><div><strong>{v.viewer_id}</strong><small>{v.project_id}<br/>Until {formatTime(v.expires_at)}</small></div><span className="pill good">active</span>{session.role === 'admin' && <RevokeReview key={`${session.csrf_token}:${v.id}`} variation={v} disabled={!!busy} request={(path, options) => api(path, session, options)} onChanged={async () => { if (sameSession(session, sessionRef.current)) { setNotice('Reviewed grant revoked. Other grants and roles remain unchanged.'); await refresh(session, true); } }}/>}</div>) : <div className="empty-state"><div className="empty-stack"><ShieldCheck size={28}/></div><h3>No active temporary grant</h3></div>}
          <details className="variation-history"><summary>Past grants <span>{shownPastGrants.length}</span></summary><div className="history-scroll">{shownPastGrants.map(v => <div className="variation" key={v.id}><div><strong>{v.viewer_id}</strong><small>{v.project_id} · {formatTime(v.expires_at)}</small></div><span className={'pill ' + statusClass(v.state)}>{v.state}</span></div>)}</div></details><p className="tiny">Expiry display uses this device's clock. The host checks actual access.</p>
        </section>
      </div>}
      {tab==='engineering'&&!engineeringTools&&<CodeReview items={engineering} detail={engineeringDetail} role={session.role} changed={async()=>{if(engineeringIdRef.current)await refreshAfterRepair(engineeringIdRef.current,new AbortController().signal);}} open={id=>void openEngineering(id)} back={()=>{engineeringIdRef.current=null;setEngineeringDetail(null);}} request={(path,options)=>api(path,session,options)}/>}
      {tab === 'engineering' && engineeringTools && <div className="content-grid"><section className="panel span-one"><div className="panel-heading"><h2>Work items</h2><Code2 size={20}/></div><div className="work-list">{engineering.length ? engineering.map(w => <button className={'work-item' + (engineeringDetail?.id === w.id ? ' selected' : '')} aria-pressed={engineeringDetail?.id === w.id} key={w.id} onClick={() => openEngineering(w.id)}><span className={'pill ' + statusClass(w.status)}>{w.status.replaceAll('_', ' ')}</span><strong>{w.request_text||'Customer change'}</strong><small>{w.request_id.slice(0,8)}</small></button>) : <p className="empty">New features appear here after preparation.</p>}</div></section>
        <section className="panel span-two"><div className="panel-heading"><h2>Review this change</h2><ShieldCheck size={20}/></div>{engineeringDetail ? <><p>{engineeringDetail.request.text}</p><div className="code-journey" aria-label="Code review progress"><div className={engineeringDetail.patch?.edits.length ? 'observed' : ''}><Code2 size={22}/><strong>{engineeringDetail.patch?.edits.length ? `${new Set(engineeringDetail.patch.edits.map(edit => edit.path)).size} file(s) changed` : 'No draft yet'}</strong></div><ArrowRight size={15}/><div className={engineeringDetail.current_checks_usable ? 'observed' : ''}><ShieldCheck size={22}/><strong>{engineeringDetail.current_checks_usable ? 'Checks passed' : 'Checks needed'}</strong></div><ArrowRight size={15}/><div><LockKeyhole size={22}/><strong>Not released</strong></div></div>
          {session.role !== 'engineer' && <p className="tiny">Read-only. An engineer prepares and checks the code.</p>}
          <div className="review-verdict"><span className={'pill ' + (engineeringDetail.current_checks_usable ? 'good' : 'neutral')}>{engineeringDetail.current_checks_usable ? 'Current checks verified' : 'Verification needed'}</span>{!engineeringDetail.repository && <details><summary>Verification details</summary><p>Saved hash checks: {currentPatchCheck(engineeringDetail.patch_hash, engineeringDetail.checks)}. Historical passes do not cover changed code or verification policy. The server rechecks provenance.</p></details>}</div>
          <RepositoryCockpit key={`${session.csrf_token}:${engineeringDetail.id}`} item={engineeringDetail} engineer={session.role === 'engineer'} request={(path, options) => api(path, session, options)} refresh={refreshAfterRepair}/>
          {!engineeringDetail.repository && session.role === 'engineer' && <div className="button-row">{['needs_engineer','draft_failed'].includes(engineeringDetail.status) && <button className="primary" disabled={!!busy || session.ai_mode === 'off' || inferenceBudget?.remaining_calls === 0} onClick={() => engineeringAction('draft')}>Draft change <ArrowRight size={15}/></button>}{['drafted','checks_failed'].includes(engineeringDetail.status) && <button className="primary" disabled={!!busy} onClick={() => engineeringAction('verify')}>Run checks <ArrowRight size={15}/></button>}</div>}
          {!engineeringDetail.repository && session.role === 'engineer' && <details className="technical-disclosure"><summary>Engineer tools</summary><div className="button-row"><button className="secondary" disabled={!!busy || !['needs_engineer','draft_failed','drafting','checks_failed'].includes(engineeringDetail.status)} onClick={loadManualSource}>Edit manually</button><button className="secondary" disabled={!!busy || !['drafted','checks_failed','checks_passed'].includes(engineeringDetail.status)} onClick={() => engineeringAction('verify')}>Recheck current code</button></div><p className="tiny">{engineeringDetail.status.replaceAll('_', ' ')} · {engineeringDetail.patch_hash || 'No patch saved'}</p></details>}
          {manualBase && <div className="manual-editor"><p className="tiny">Only {manualBase.path} can change. This source replaces the owned fixture in a disposable check environment, not the live app.</p><label>Complete replacement source<textarea value={manualSource} onChange={e => setManualSource(e.target.value)} rows={14} spellCheck={false}/></label><button className="primary" onClick={submitManualPatch} disabled={!!busy || manualSource === manualBase.source}>Save manual patch</button></div>}
          {!engineeringDetail.repository && !!engineeringDetail.patch?.edits.length && <details className="code-disclosure"><summary>Review code changes</summary>{engineeringDetail.patch.edits.map((edit,index) => <PatchDiff key={`${engineeringDetail.patch_hash}:${index}`} path={edit.path} before={edit.old} after={edit.new}/>)}</details>}
          {!engineeringDetail.repository && <><details className="technical-disclosure"><summary>Check history ({engineeringDetail.checks.length})</summary>{engineeringDetail.checks.map((check, index) => <div className="check-result" key={index}><span className={'pill ' + (check.result.passed ? 'good' : 'bad')}>{check.result.passed ? 'checks passed' : 'checks failed'}</span><span className="tiny">{check.result.runner} · {check.subject_hash === engineeringDetail.patch_hash ? 'Current patch' : 'Historical patch, not the current candidate'} · {check.subject_hash.slice(0,16)}</span><details><summary>View check output</summary><pre>{check.result.stderr || check.result.stdout}</pre></details><p className="tiny">{check.limitation}</p></div>)}</details></>}
          {!engineeringDetail.repository && <details className="technical-disclosure"><summary>Repair workflow</summary><BoundedRepair key={`${session.user_id}:${session.tenant_id}:${session.csrf_token}:${engineeringDetail.id}`} session={session} item={engineeringDetail} remainingCalls={inferenceBudget?.remaining_calls} parentBusy={!!busy} request={(path, options) => api(path, session, options)} onChanged={refreshAfterRepair}/></details>}
          {!engineeringDetail.human_decision && session.role === 'engineer' && <div className="decision-row"><button className="primary" disabled={!!busy || engineeringDetail.status !== 'checks_passed' || !engineeringDetail.current_checks_usable} onClick={() => engineeringAction('decide', { decision: 'accept_for_manual_release', patch_hash: engineeringDetail.patch_hash, verification_id: engineeringDetail.repository?.verification_id, context_hash: engineeringDetail.repository?.context_hash })}>Accept for release review <ArrowRight size={15}/></button><details className="technical-disclosure"><summary>Other decisions</summary><div className="button-row"><button className="secondary" disabled={!!busy} onClick={() => engineeringAction('decide', { decision: 'reject' })}>Reject</button><button className="secondary" disabled={!!busy} onClick={() => engineeringAction('decide', { decision: 'take_over' })}>Take over</button></div></details></div>}
          {engineeringDetail.human_decision === 'accept_for_manual_release' && <button className="secondary" disabled={!!busy||!engineeringDetail.current_checks_usable} onClick={downloadArtifact}>Download release handoff</button>}
          <p className="tiny">Acceptance records a decision. It does not merge or deploy code.</p></> : <div className="empty large">Choose a work item to inspect the real request, exact candidate code, independent checks, and limitations.</div>}</section></div>}
      {tab === 'convergence' && <ProductSignals rows={mapSelection?.station==='convergence'?convergence.filter(r=>'pattern:'+r.need_key===mapSelection.id):convergence} canDecide={session.role === 'product_owner'} busy={!!busy} rationales={rationales} setRationale={(key, value) => setRationales(previous => ({ ...previous, [key]: value }))} decide={(key, decision) => void decideConvergence(key, decision)}/>}
      {tab === 'ledger' && <div className="content-grid"><section className="panel span-three"><div className="panel-heading"><h2>Request history</h2><FileText size={20}/></div>{['admin','engineer'].includes(session.role) && selected && <a className="secondary" href={`/v1/requests/${selected}/proof`} download>Export selected request proof</a>}<p className="tiny">Exports can contain private request text and code. Review before sharing.</p><div className="timeline">{visibleEvents.length ? visibleEvents.map(e => <div className="timeline-item" key={e.id}><div className="timeline-node"/><div><small>{formatTime(e.created_at)}</small><h3>{e.type.replaceAll('.', ' · ').replaceAll('_', ' ')}</h3><details><summary>Event data</summary><code>{JSON.stringify(e.payload)}</code><small>{e.request_id}</small></details></div></div>) : <p className="empty">No events yet.</p>}</div><details><summary>Host access checks ({observations.length})</summary><p className="tiny">Latest 500 tenant-local API checks, not previews or confirmed delivery.</p><div className="timeline">{observations.map(o => <div className="timeline-item" key={o.id}><div className="timeline-node"/><small>{formatTime(o.observed_at)} · {o.actor_id}</small><h3>{o.allowed ? 'Allowed' : 'Denied'}: {o.action}</h3><code>{o.project_id} · {o.basis} · {o.variation_id || 'no variation'}</code></div>)}</div></details></section></div>}
      {tab==='people'&&<Organization key={`${session.csrf_token}:${organizationInitial}`} role={session.role} initial={organizationInitial} projects={session.projects||[]} openRequest={id=>{navigate('journey');void selectRequest(id);}} request={(path,options)=>api(path,session,options)} target={setViewer} requestAccess={(user,project)=>{setViewer(user);setRequestProject(project);setKind('access');setRequestText(accessRequestText(session.projects?.find(p=>p.id===project)?.name||projectName(project)));setRequestOpen(true);}}/>}
      {tab === 'account' && <AccountSettings key={`${session.user_id}:${session.csrf_token}`} session={session} request={(path, options)=>api(path, session, options)} changed={acceptSession}/>}
      {tab === 'assurance' && ['admin', 'engineer','manager'].includes(session.role) && <>
        {session.release_assurance_enabled&&<ReleaseAssurance key={`release:${session.user_id}:${session.tenant_id}:${session.csrf_token}:${session.scope_version}`} role={session.role} tenantId={session.tenant_id} userId={session.user_id} projects={session.projects||[]} request={(path,options)=>api(path,session,options)}/>}
        <details open={!session.release_assurance_enabled}><summary>Workspace diagnostics</summary><Assurance key={`${session.user_id}:${session.csrf_token}`} tenant={session.tenant_id} request={(path, options) => api(path, session, options)}/></details>
      </>}
    </main>
  </div></SpatialShell>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode>{window.location.pathname==='/customer'?<CustomerPortal/>:<App/>}</React.StrictMode>);
