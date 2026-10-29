import {useEffect,useRef,useState} from 'react';
import {Bell,Building2,Contact,CreditCard,Handshake,Plus,Receipt,Users,X} from 'lucide-react';
import {boundedResponse} from './responseDeadline';

type Member={user_id:string;name:string;role:'member'|'manager';account_role:string;account_enabled:boolean;enabled:boolean;revision:number};
type Team={id:string;name:string;members:Member[];projects:{id:string;name:string}[];can_read_reviews:boolean};
type Account={id:string;role:string;enabled:boolean};
type Transport=<T>(path:string,options?:RequestInit)=>Promise<T>;
function teamIcon(name:string){const s=name.toLowerCase();return s.includes('payment')?CreditCard:s.includes('notif')?Bell:s.includes('billing')?Receipt:s==='crm'?Contact:s.includes('deal')?Handshake:Building2;}

/** The API owns every grant. Disclosures keep administration out of the main map. */
export function Teams({request,role}:{request:Transport;role:string}){
  const admin=role==='admin',[teams,setTeams]=useState<Team[]>([]),[accounts,setAccounts]=useState<Account[]>([]);
  const [selected,setSelected]=useState(''),[creating,setCreating]=useState(false),[name,setName]=useState('');
  const [user,setUser]=useState(''),[kind,setKind]=useState<'member'|'manager'>('member'),[draft,setDraft]=useState<Record<string,string>>({});
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[loaded,setLoaded]=useState(false);
  const mounted=useRef(false),writing=useRef(false),generation=useRef(0),pending=useRef<{cancel:()=>void}[]>([]);
  async function call<T>(path:string,options?:RequestInit){const task=boundedResponse(signal=>request<T>(path,{...options,signal}));pending.current.push(task);try{return await task.promise;}finally{pending.current=pending.current.filter(p=>p!==task);}}
  async function refresh(){const ticket=++generation.current;const [rows,people]=await Promise.all([
    call<Team[]>('/v1/teams'),admin?call<Account[]>('/v1/members'):Promise.resolve([])]);
    if(!mounted.current||ticket!==generation.current)return;
    setTeams(rows);setAccounts(people);setLoaded(true);setSelected(previous=>rows.some(t=>t.id===previous)?previous:rows[0]?.id||'');
  }
  useEffect(()=>{mounted.current=true;void refresh().catch(e=>{if(mounted.current)setError(String(e));});return()=>{mounted.current=false;generation.current++;pending.current.forEach(p=>p.cancel());};},[]);
  async function save(path:string,body:unknown,method='PUT'){
    if(writing.current)return;writing.current=true;setBusy(true);setError('');
    try{const result=await call<{id?:string}>(path,{method,body:JSON.stringify(body)});if(!mounted.current)return;
      if(method==='POST'&&result.id)setSelected(result.id);await refresh();setCreating(false);setName('');setUser('');setDraft({});
    }catch(e){if(mounted.current){setError(String(e));setDraft({});setUser('');await refresh().catch(()=>{});}}
    finally{writing.current=false;if(mounted.current)setBusy(false);}
  }
  const current=teams.find(t=>t.id===selected),available=accounts.filter(a=>!current?.members.some(m=>m.user_id===a.id));
  return <section className="panel team-workspace" aria-labelledby="teams-title">
    <div className="panel-heading"><h2 id="teams-title">{admin?'Teams':role==='manager'?'Teams you manage':'Your teams'}</h2>
      {admin&&<button className="secondary" onClick={()=>setCreating(!creating)} aria-expanded={creating}><Plus size={15}/>New team</button>}</div>
    {creating&&<form className="team-create" onSubmit={e=>{e.preventDefault();void save('/v1/teams',{name},'POST');}}>
      <label>Team name<input required minLength={2} maxLength={80} value={name} onChange={e=>setName(e.target.value)} placeholder="For example, Payments"/></label>
      <button className="primary" disabled={busy||name.trim().length<2}>Create team</button><button type="button" className="icon-button" aria-label="Cancel new team" onClick={()=>setCreating(false)}><X size={16}/></button></form>}
    {error&&<p role="alert" className="alert error">{error}</p>}
    {!loaded&&!error&&<p role="status" className="tiny">Loading your teams…</p>}
    {loaded&&!teams.length&&<div className="empty-state"><Users size={30}/><h3>No teams assigned</h3><p>Ask an administrator to assign your team access.</p></div>}
    <div className="team-grid">{teams.map((team,index)=>{const Icon=teamIcon(team.name);return <button className={'team-tile tone-'+index%5} key={team.id} aria-pressed={team.id===selected} onClick={()=>{setSelected(team.id);setUser('');setDraft({});}}>
      <Icon size={27}/><strong>{team.name}</strong><small>{team.members.filter(m=>m.enabled&&m.account_enabled).length} teammates</small></button>;})}</div>
    {current&&<div className="team-detail"><header><h3>{current.name}</h3><span className="pill neutral">{current.can_read_reviews?'Review access':'Structure only'}</span></header>
      {!current.can_read_reviews&&admin&&<p className="tiny">Managing a team does not automatically grant access to its reviews.</p>}
      {current.members.map(member=><details className="team-member" key={member.user_id}><summary><span className="team-avatar">{member.name.slice(0,1).toUpperCase()}</span><span><strong>{member.name}</strong><small>{member.account_role.replaceAll('_',' ')} · {member.enabled?(member.account_enabled?'Assigned':'Account disabled'):'Removed'}</small></span></summary>
        {admin?<div className="team-member-actions"><label>Review access<select aria-label={`Review access for ${member.user_id}`} disabled={busy} value={draft[member.user_id]||member.role} onChange={e=>setDraft({...draft,[member.user_id]:e.target.value})}><option value="member">Team member</option><option value="manager">Team manager</option></select></label>
          <button className="secondary" disabled={busy||!draft[member.user_id]||draft[member.user_id]===member.role} onClick={()=>void save(`/v1/teams/${current.id}/members/${encodeURIComponent(member.user_id)}`,{role:draft[member.user_id],enabled:member.enabled,expected_revision:member.revision})}>Save access</button>
          <button className="text-button" disabled={busy} onClick={()=>void save(`/v1/teams/${current.id}/members/${encodeURIComponent(member.user_id)}`,{role:member.role,enabled:!member.enabled,expected_revision:member.revision})}>{member.enabled?'Remove from team':'Restore membership'}</button></div>:<p className="tiny">{member.role==='manager'?'Manages this team':'Team member'} · @{member.user_id}</p>}
      </details>)}
      {!current.members.length&&<p className="tiny">No teammates yet.</p>}
      {admin&&<details className="technical-disclosure"><summary>Add a teammate</summary><form className="team-add" onSubmit={e=>{e.preventDefault();void save(`/v1/teams/${current.id}/members/${encodeURIComponent(user)}`,{role:kind,enabled:true,expected_revision:0});}}>
        <label>Account<select required value={user} onChange={e=>{setUser(e.target.value);setKind(accounts.find(a=>a.id===e.target.value)?.role==='manager'?'manager':'member');}}><option value="">Choose an account</option>{available.map(a=><option key={a.id} value={a.id}>{a.id}{a.enabled?'':' (disabled)'}</option>)}</select></label>
        <label>Review access<select value={kind} onChange={e=>setKind(e.target.value as typeof kind)}><option value="member">Team member</option><option value="manager">Team manager</option></select></label>
        <p className="tiny">Team membership controls visibility. Account roles control actions.</p><button className="primary" disabled={busy||!user}>Add teammate</button></form></details>}
    </div>}
  </section>;
}
