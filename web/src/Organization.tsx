import {useEffect,useRef,useState} from 'react';
import {ArrowLeft,ArrowRight,ChevronLeft,ChevronRight,Users,Network,Building2,KeyRound,Search,Settings2} from 'lucide-react';
import {Teams} from './Teams';
import {People} from './People';
import {RevokeReview} from './RevokeReview';
import {accessRefreshDelay} from './accessRefresh';
import {boundedResponse} from './responseDeadline';
import {CustomerWorkspace} from './CustomerWorkspace';
type Transport=<T>(path:string,options?:RequestInit)=>Promise<T>;
type Person={id:string;name:string;title:string;manager_id:string|null;manager_outside_scope:boolean;revision:number;enabled:boolean;reports:number;teams:{id:string;name:string;role:string}[]};
type Directory={people:Person[];count:number;total:number;page:number;page_size:number;teams:{id:string;name:string}[];can_edit:boolean};
type Access={user_id:string;preview_only:boolean;as_of:string;rules:{project_id:string;project:string;allowed:boolean;basis:string;variation_id:string|null;expires_at:string|null;can_request:boolean;can_manage:boolean;grants:{id:string;expires_at:string}[]}[]};

/** Reporting structure and policy snapshots share one organization entry point.
 * A title is never used as an authorization role. */
export function Organization({role,request,initial='people',requestAccess,target,projects=[],openRequest=()=>{}}: {
  role:string;request:Transport;initial?:'people'|'access';requestAccess:(user:string,project:string)=>void;target:(user:string)=>void;
  projects?:{id:string;name:string}[];openRequest?:(id:string)=>void;
}){
  const [view,setView]=useState<'people'|'hierarchy'|'teams'|'access'|'customers'>(initial),[query,setQuery]=useState(''),[page,setPage]=useState(0);
  const [team,setTeam]=useState<string|null>(null),[path,setPath]=useState<{id:string;name:string}[]>([]);
  const [directory,setDirectory]=useState<Directory|null>(null),[person,setPerson]=useState<Person|null>(null),[access,setAccess]=useState<Access|null>(null);
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[refresh,setRefresh]=useState(0),[tools,setTools]=useState(false);
  const [title,setTitle]=useState(''),[manager,setManager]=useState(''),[saving,setSaving]=useState(false),[rule,setRule]=useState<string|null>(null);
  const [accessVersion,setAccessVersion]=useState(0),[profileOpen,setProfileOpen]=useState(false),[managerQuery,setManagerQuery]=useState(''),[managers,setManagers]=useState<Person[]>([]);
  const [allRules,setAllRules]=useState(false);
  const selected=useRef(person?.id);selected.current=person?.id;
  useEffect(()=>{const controller=new AbortController();setBusy(true);setError('');setDirectory(null);
    const params=new URLSearchParams({q:query,page:String(page)});
    if(team)params.set('team_id',team);
    if(view==='hierarchy'){if(path.length)params.set('reports_to',path[path.length-1].id);else params.set('roots','true');}
    request<Directory>('/v1/organization?'+params,{signal:controller.signal}).then(data=>{if(!controller.signal.aborted)setDirectory(data);})
      .catch(e=>{if(!controller.signal.aborted)setError(String(e));}).finally(()=>{if(!controller.signal.aborted)setBusy(false);});
    return()=>controller.abort();
  },[view,query,page,team,path,refresh]);
  useEffect(()=>{setAccess(null);setRule(null);setProfileOpen(false);setManagerQuery('');setAllRules(false);},[person?.id]);
  useEffect(()=>{
    if(person){target(person.id);setTitle(person.title);setManager(person.manager_id||'');}
  },[person?.id,person?.revision]);
  useEffect(()=>{if(!person)return;let disposed=false,running=false;let timer:ReturnType<typeof setTimeout>;let pending:ReturnType<typeof boundedResponse<Access>>|null=null;
    async function load(){if(disposed||running)return;running=true;clearTimeout(timer);
      pending=boundedResponse(signal=>request<Access>(`/v1/organization/people/${encodeURIComponent(person!.id)}/access`,{signal}));
      let delay=15000;
      try{const data=await pending.promise;if(!disposed&&data.user_id===person!.id&&selected.current===data.user_id){setAccess(data);setError('');delay=accessRefreshDelay(data);}}
      catch(e){if(!disposed){setAccess(null);setError('Access could not be refreshed. '+String(e));}}
      finally{running=false;if(!disposed)timer=setTimeout(()=>{if(document.visibilityState==='visible')void load();else timer=setTimeout(()=>void load(),15000);},delay);}}
    const resume=()=>{if(document.visibilityState==='visible')void load();};void load();document.addEventListener('visibilitychange',resume);
    return()=>{disposed=true;clearTimeout(timer);pending?.cancel();document.removeEventListener('visibilitychange',resume);};
  },[person?.id,person?.revision,accessVersion]);
  useEffect(()=>{if(!profileOpen)return;const controller=new AbortController();setManagers([]);
    request<Directory>('/v1/organization?'+new URLSearchParams({q:managerQuery}),{signal:controller.signal}).then(d=>{if(!controller.signal.aborted)setManagers(d.people);}).catch(e=>{if(!controller.signal.aborted)setError(String(e));});
    return()=>controller.abort();
  },[profileOpen,managerQuery]);
  function change(next:typeof view){setView(next);setTeam(null);setPath([]);setPage(0);setQuery('');setPerson(null);setTools(false);}
  async function saveProfile(){if(!person||saving)return;setSaving(true);setError('');try{
    const result=await request<{revision:number}>(`/v1/organization/people/${encodeURIComponent(person.id)}`,{method:'PUT',body:JSON.stringify({title,manager_id:manager.trim()||null,expected_revision:person.revision})});
    if(selected.current===person.id)setPerson({...person,title,manager_id:manager.trim()||null,revision:result.revision});setRefresh(n=>n+1);
  }catch(e){setError(String(e));}finally{setSaving(false);}}
  const tabs=[['people','People',Users],['hierarchy','Hierarchy',Network],['teams','Teams',Building2],['access','Access',KeyRound],['customers','Customers',Building2]] as const;
  const visibleRules=access?.rules.filter(r=>allRules||r.allowed||r.can_request)||[];
  return <section className="organization-workspace" aria-label="Organization">
    <div className="section-tabs">{tabs.map(([id,name,Icon])=><button key={id} aria-pressed={view===id} onClick={()=>change(id)}><Icon size={16}/>{name}</button>)}</div>
    {error&&<p className="alert error" role="alert">{error}</p>}
    {view==='customers'?<CustomerWorkspace role={role} request={request} projects={projects} openRequest={openRequest}/>:person?<>
      <button className="text-button" onClick={()=>setPerson(null)}><ArrowLeft size={15}/>Back to {view}</button>
      <header className="person-heading"><span className="employee-avatar">{person.name.split(' ').slice(0,2).map(n=>n[0]).join('')}</span><div><h2>{person.name}</h2><p>{person.title}</p></div></header>
      <div className="organization-chips">{person.teams.map(t=><span key={t.id}>{t.name}</span>)}</div>
      <div className="access-rule-grid" aria-label="Project access rules">{access?visibleRules.map(r=><button key={r.project_id} className={r.allowed?'rule-allowed':'rule-denied'} aria-pressed={rule===r.project_id} onClick={()=>setRule(rule===r.project_id?null:r.project_id)} title={`${r.basis.replaceAll('_',' ')}${r.expires_at?' · until '+new Date(r.expires_at).toLocaleString():''}`}><KeyRound size={16}/><span>{r.project}<small>{r.allowed?'Can read':'No access'}{r.expires_at?' · temporary':''}</small></span></button>):<p role="status">{error?'Current access is unavailable. Retrying…':'Checking current access…'}</p>}</div>
      {access&&access.rules.length>visibleRules.length&&<button className="text-button" onClick={()=>setAllRules(true)}>Show all {access.rules.length} projects</button>}{allRules&&<button className="text-button" onClick={()=>{setAllRules(false);setRule(null);}}>Show current access</button>}
      {rule&&access&&<div className="selected-access-rule"><strong>{access.rules.find(r=>r.project_id===rule)?.basis.replaceAll('_',' ')}</strong><p className="tiny">Current policy preview. The host checks every read.</p>{access.rules.find(r=>r.project_id===rule)?.can_request&&<button className="secondary" onClick={()=>requestAccess(person.id,rule)}>Request a change<ArrowRight size={15}/></button>}{access.rules.find(r=>r.project_id===rule)?.grants.map(g=><div className="organization-grant" key={g.id}><span>Temporary access · {new Date(g.expires_at).toLocaleString()}</span>{access.rules.find(r=>r.project_id===rule)?.can_manage&&<RevokeReview variation={{id:g.id,project_id:rule,viewer_id:person.id}} disabled={saving} request={request} onChanged={async()=>{if(selected.current===person.id)setAccessVersion(n=>n+1);}}/>}</div>)}</div>}
      {role==='admin'&&<details className="profile-edit" open={profileOpen} onToggle={e=>setProfileOpen(e.currentTarget.open)}><summary><Settings2 size={15}/>Reporting line</summary><form onSubmit={e=>{e.preventDefault();void saveProfile();}}><label>Position<input value={title} onChange={e=>setTitle(e.target.value)} maxLength={80} minLength={2} required list="position-titles"/></label><datalist id="position-titles">{['CEO','CTO','CFO','COO','CPO','CISO','Director of Engineering','Engineering Manager','Staff Engineer','Software Engineer','Architect','Product Manager','Designer','Finance Analyst','Customer Success Manager'].map(t=><option key={t} value={t}/>)}</datalist><label>Find a manager<input value={managerQuery} onChange={e=>setManagerQuery(e.target.value)} placeholder="Search by name or position"/></label><label>Reports to<select value={manager} onChange={e=>setManager(e.target.value)}><option value="">No manager</option>{manager&&!managers.some(p=>p.id===manager)&&<option value={manager}>Current manager · {manager}</option>}{managers.filter(p=>p.id!==person.id&&p.enabled).map(p=><option value={p.id} key={p.id}>{p.name} · {p.title}</option>)}</select></label><button className="primary" disabled={saving}>{saving?'Saving…':'Save reporting line'}</button></form></details>}
    </>:<>
      {view==='teams'&&tools?<><button className="text-button" onClick={()=>setTools(false)}><ArrowLeft size={15}/>Team directory</button><Teams role={role} request={request}/></>:tools?<><button className="text-button" onClick={()=>setTools(false)}><ArrowLeft size={15}/>People directory</button><People request={request}/></>:<>
      <div className="directory-tools"><label><Search size={16}/><input aria-label="Search organization" placeholder="Find a person, position or team" value={query} onChange={e=>{setQuery(e.target.value);setPage(0);}}/></label><span className="directory-total">{directory?.total??'…'} people</span>{role==='admin'&&view!=='hierarchy'&&view!=='access'&&<button className="icon-button" aria-label={view==='teams'?'Manage teams':'Manage employee accounts'} onClick={()=>setTools(true)}><Settings2 size={17}/></button>}</div>
      {view==='hierarchy'&&<nav className="hierarchy-path" aria-label="Reporting path"><button onClick={()=>{setPath([]);setPage(0);}}>Organization</button>{path.map((p,i)=><button key={p.id} onClick={()=>{setPath(path.slice(0,i+1));setPage(0);}}><ArrowRight size={12}/>{p.name}</button>)}</nav>}
      {team&&<button className="text-button" onClick={()=>{setTeam(null);setPage(0);}}><ArrowLeft size={15}/>All teams</button>}
      {busy?<p className="empty" role="status">Loading your organization…</p>:view==='teams'&&!team?<div className="organization-grid">{directory?.teams.filter(t=>!query||t.name.toLowerCase().includes(query.toLowerCase())).map((t,i)=><button className={`organization-team tone-${i%5}`} key={t.id} onClick={()=>{setTeam(t.id);setPage(0);setQuery('');}}><Building2 size={26}/><strong>{t.name}</strong><ArrowRight size={16}/></button>)}</div>:<div className={'employee-grid'+(view==='hierarchy'?' hierarchy-grid':'')}>{directory?.people.map((p,i)=><article className="employee-card" key={p.id}>
        <button className="employee-open" onClick={()=>setPerson(p)} title={`${p.title} · ${p.teams.map(t=>t.name).join(', ')}`}><span className={`employee-avatar tone-${i%5}`}>{p.name.split(' ').slice(0,2).map(n=>n[0]).join('')}</span><strong>{p.name}</strong><span>{p.title}</span><small>{p.teams.map(t=>t.name).join(' · ')}</small>{view==='access'&&<KeyRound size={16}/>}</button>
        {view==='hierarchy'&&p.reports>0&&<button className="report-branch" onClick={()=>{setPath([...path,{id:p.id,name:p.name}]);setPage(0);setQuery('');}}>{p.reports} direct reports<ArrowRight size={14}/></button>}
      </article>)}</div>}
      {!busy&&directory&&!directory.people.length&&<p className="empty">No people in this view.</p>}
      {directory&&(view!=='teams'||team)&&directory.count>directory.page_size&&<div className="directory-pagination"><button aria-label="Previous people page" disabled={!page} onClick={()=>setPage(page-1)}><ChevronLeft size={17}/></button><span>{page+1} / {Math.ceil(directory.count/directory.page_size)}</span><button aria-label="Next people page" disabled={(page+1)*directory.page_size>=directory.count} onClick={()=>setPage(page+1)}><ChevronRight size={17}/></button></div>}
      </>}
    </>}
  </section>;
}
