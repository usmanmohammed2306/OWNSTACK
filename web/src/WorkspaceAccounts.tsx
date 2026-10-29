import { useEffect, useRef, useState } from 'react';
import { Check, Copy, KeyRound, Plus, Ticket } from 'lucide-react';
import { boundedResponse, type BoundedResponse } from './responseDeadline';
import type { CustomerSession } from './AccountGate';
type Transport = <T>(path: string, options?: RequestInit) => Promise<T>;
type Invitation = {id:string;role:string;expires_at:string;used:boolean;revoked:boolean};

export function InvitationManager({ request }: {request:Transport}) {
  const [rows,setRows]=useState<Invitation[]>([]),[role,setRole]=useState('member'),[code,setCode]=useState('');
  const [teams,setTeams]=useState<{id:string;name:string}[]>([]),[team,setTeam]=useState('');
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[copied,setCopied]=useState(false);
  const active=useRef<BoundedResponse<unknown>|null>(null),mounted=useRef(false),writing=useRef(false);
  async function call<T>(path:string, options?:RequestInit) {
    const pending=boundedResponse(signal=>request<T>(path,{...options,signal}));active.current=pending;return pending.promise;
  }
  async function refresh(){const saved=await call<Invitation[]>('/v1/accounts/invitations');const groups=await call<{id:string;name:string}[]>('/v1/teams');if(mounted.current){setRows(saved);setTeams(groups);setTeam(previous=>groups.some(g=>g.id===previous)?previous:groups.find(g=>g.name==='General')?.id||groups[0]?.id||'');}}
  useEffect(()=>{let current=true;mounted.current=true;void refresh().catch(e=>{if(current)setError(String(e));});
    return()=>{current=false;mounted.current=false;active.current?.cancel();};},[]);
  async function create(){
    if(writing.current)return;writing.current=true;setBusy(true);setError('');setCopied(false);
    try{const saved=await call<{token:string}>('/v1/accounts/invitations',{method:'POST',body:JSON.stringify({role,days:2,team_id:team})});
      if(!mounted.current)return;setCode(saved.token);await refresh();}
    catch(e){if(mounted.current)setError(String(e));}finally{writing.current=false;if(mounted.current)setBusy(false);}
  }
  async function revoke(id:string){
    if(writing.current)return;writing.current=true;setBusy(true);setError('');
    try{await call(`/v1/accounts/invitations/${id}/revoke`,{method:'POST'});if(mounted.current){setCode('');await refresh();}}
    catch(e){if(mounted.current)setError(String(e));}finally{writing.current=false;if(mounted.current)setBusy(false);}
  }
  return <section className="invitation-manager" aria-labelledby="invite-title"><div className="panel-heading"><h3 id="invite-title">Invite your team</h3><Ticket size={20}/></div>
    <p className="tiny">One account. Your workspace only. Expires in two days.</p>
    <div className="button-row"><label>Account role<select value={role} disabled={busy} onChange={e=>setRole(e.target.value)}><option value="member">Member</option><option value="contractor">Contractor</option><option value="engineer">Engineer</option><option value="manager">Manager</option></select></label>
      <label>Team<select aria-label="Invitation team" value={team} disabled={busy} onChange={e=>setTeam(e.target.value)}>{teams.map(t=><option key={t.id} value={t.id}>{t.name}</option>)}</select></label>
      <button className="primary" disabled={busy||!team} onClick={()=>void create()}><Plus size={15}/>Create invitation</button></div>
    {role==='engineer'&&<p className="tiny">Engineers can prepare code and run checks. They cannot approve access or deploy.</p>}
    {role==='manager'&&<p className="tiny">Managers can review assigned teams. They cannot accept code or deploy.</p>}
    {code&&<div className="invitation-code"><p className="tiny">Share privately. This code is shown only now.</p><code>{code}</code><button className="secondary" onClick={()=>{void navigator.clipboard.writeText(code).then(()=>setCopied(true)).catch(()=>setError('Could not copy. Select the code and copy it manually.'));}}>{copied?<Check size={14}/>:<Copy size={14}/>} {copied?'Copied':'Copy code'}</button></div>}
    {error&&<p className="alert error" role="alert">{error}</p>}
    {busy&&<p className="tiny" role="status">Saving invitation…</p>}
    <details className="technical-disclosure"><summary>Invitations ({rows.length})</summary>{rows.map(row=>{
      const status=row.used?'Used':row.revoked?'Revoked':Date.parse(row.expires_at)<=Date.now()?'Expired':'Pending';
      return <div className="invitation-row" key={row.id}><span>{row.role}<small>{status} · {new Date(row.expires_at).toLocaleDateString()}</small></span>{status==='Pending'&&<button className="text-button" disabled={busy} onClick={()=>void revoke(row.id)}>Revoke</button>}</div>;
    })}</details>
  </section>;
}

export function AccountSettings({session,request,changed}:{session:CustomerSession;request:Transport;changed:(session:CustomerSession)=>void}){
  const [current,setCurrent]=useState(''),[next,setNext]=useState(''),[confirm,setConfirm]=useState('');
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  const active=useRef<BoundedResponse<unknown>|null>(null),mounted=useRef(false),writing=useRef(false);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;active.current?.cancel();};},[]);
  async function save(){
    if(writing.current)return;if(next!==confirm){setError('The new passphrases do not match.');return;}
    writing.current=true;setBusy(true);setError('');const pending=boundedResponse(signal=>request<CustomerSession>('/v1/accounts/password',
      {method:'POST',body:JSON.stringify({current_password:current,password:next}),signal}));active.current=pending;
    try{const updated=await pending.promise;if(mounted.current){setCurrent('');setNext('');setConfirm('');changed(updated);}}
    catch(e){if(mounted.current)setError(String(e));}finally{writing.current=false;if(mounted.current)setBusy(false);}
  }
  return <section className="panel" aria-labelledby="account-settings-title"><h2 id="account-settings-title">Your account</h2><div className="account-facts"><strong>{session.display_name||session.user_id}</strong><span>@{session.user_id}</span><span>{session.workspace_name||session.tenant_id}</span></div>
    {session.role==='admin'&&<GovernanceSettings request={request}/>}
    <details className="technical-disclosure"><summary><KeyRound size={15}/> Change passphrase</summary><p className="tiny">Your other sessions will be signed out.</p>
      <form onSubmit={e=>{e.preventDefault();void save();}}><label>Current passphrase<input required type="password" autoComplete="current-password" value={current} maxLength={256} onChange={e=>setCurrent(e.target.value)}/></label>
        <label>New passphrase<input required type="password" autoComplete="new-password" minLength={16} maxLength={128} value={next} onChange={e=>setNext(e.target.value)}/></label>
        <label>Confirm new passphrase<input required type="password" autoComplete="new-password" minLength={16} maxLength={128} value={confirm} onChange={e=>setConfirm(e.target.value)}/></label>
        {error&&<p className="alert error" role="alert">{error}</p>}<button className="primary" disabled={busy}>{busy?'Updating…':'Update passphrase'}</button></form></details>
  </section>;
}

function GovernanceSettings({request}:{request:Transport}){
  const [saved,setSaved]=useState<number|null>(null),[choice,setChoice]=useState(1),[busy,setBusy]=useState(false),[error,setError]=useState('');
  useEffect(()=>{let current=true;const abort=new AbortController();void request<{approval_quorum:number}>('/v1/governance',{signal:abort.signal}).then(r=>{if(current){setSaved(r.approval_quorum);setChoice(r.approval_quorum);}}).catch(()=>{if(current)setError('Could not load the approval policy.');});return()=>{current=false;abort.abort();};},[]);
  async function save(){if(busy||saved===null)return;setBusy(true);setError('');try{const r=await request<{approval_quorum:number}>('/v1/governance',{method:'POST',body:JSON.stringify({approval_quorum:choice,expected_quorum:saved})});setSaved(r.approval_quorum);}catch(e){setError(e instanceof Error?e.message:'Could not save.');}finally{setBusy(false);}}
  return <details className="technical-disclosure"><summary>Access approval policy</summary><p className="tiny">Applies to future proposals. Existing grants keep their captured policy. A second administrator must be provisioned by your operator before choosing two reviewers.</p>
    <label>Required administrators<select value={choice} disabled={saved===null||busy} onChange={e=>setChoice(Number(e.target.value))}><option value={1}>One administrator</option><option value={2}>Two administrators, requester excluded</option></select></label>
    {error&&<p role="alert">{error}</p>}<button className="secondary" disabled={busy||saved===null||saved===choice} onClick={()=>void save()}>{busy?'Saving…':'Save approval policy'}</button></details>;
}
