import {useEffect,useRef,useState} from 'react';
import {GitBranch,Plus,RefreshCw} from 'lucide-react';
type Transport=<T>(path:string,options?:RequestInit)=>Promise<T>;
type Repository={id:string;project_id:string;key:string;label:string;revision:number;enabled:boolean;kind:'python'|'pinned';source:{repo?:string;base_commit?:string;sha256?:string};customers:Record<string,{enabled:boolean}>};
type Source={project_id:string;label:string;sha256:string};
export function RepositoryConnections({customerId,projects,role,request}:{customerId:string;projects:{id:string;name:string;enabled?:boolean}[];role:string;request:Transport}){
 const [project,setProject]=useState(''),[rows,setRows]=useState<Repository[]>([]),[sources,setSources]=useState<Source[]>([]);
 const [label,setLabel]=useState(''),[kind,setKind]=useState<'python'|'pinned'>('pinned'),[source,setSource]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const alive=useRef(true),writing=useRef(false),key=useRef(crypto.randomUUID());const canWrite=['admin','engineer'].includes(role);
 useEffect(()=>{if(!projects.some(p=>p.id===project&&p.enabled!==false))setProject(projects.find(p=>p.enabled!==false)?.id||'');},[projects,project]);
 useEffect(()=>{alive.current=true;const c=new AbortController();setRows([]);setSources([]);setError('');if(project)Promise.all([
   request<Repository[]>('/v1/repositories?'+new URLSearchParams({project_id:project}),{signal:c.signal}),request<Source[]>('/v1/release/sources',{signal:c.signal})])
   .then(([r,s])=>{if(!c.signal.aborted){setRows(r);const filtered=s.filter(v=>v.project_id===project);setSources(filtered);setSource(filtered[0]?.sha256||'');}}).catch(e=>{if(!c.signal.aborted)setError(String(e));});return()=>{alive.current=false;c.abort();};
 },[project,customerId]);
 async function refresh(){const data=await request<Repository[]>('/v1/repositories?'+new URLSearchParams({project_id:project}));if(alive.current)setRows(data);}
 async function work(fn:()=>Promise<void>){if(writing.current)return;writing.current=true;setBusy(true);setError('');try{await fn();}catch(e){if(alive.current)setError(String(e));}finally{writing.current=false;if(alive.current)setBusy(false);}}
 async function connect(r:Repository,enabled:boolean){await request(`/v1/repositories/${r.id}/customers`,{method:'POST',body:JSON.stringify({expected_revision:r.revision,customer_id:customerId,enabled})});await refresh();}
 return <details className="repository-connections"><summary><GitBranch size={16}/>Repositories</summary>{error&&<p role="alert" className="alert error">{error}</p>}
  {!project?<p>Connect a product before onboarding its repository.</p>:<><label>Product<select value={project} onChange={e=>setProject(e.target.value)}>{projects.filter(p=>p.enabled!==false).map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
  <div className="list-heading"><small>Staff-only source connections</small><button aria-label="Refresh repositories" disabled={busy} onClick={()=>void work(refresh)}><RefreshCw size={16}/></button></div>
  <div className="customer-repository-list">{rows.map(r=><article key={r.id}><GitBranch size={18}/><div><strong>{r.label}</strong><small>{r.source.repo||'Reviewed Python app'} · {(r.source.base_commit||r.source.sha256||'').slice(0,12)}{!r.enabled?' · paused':''}</small></div>{canWrite&&<button disabled={busy||!r.enabled} onClick={()=>void work(()=>connect(r,!r.customers[customerId]?.enabled))}>{r.customers[customerId]?.enabled?'Disconnect':'Connect customer'}</button>}</article>)}</div>
  {canWrite&&<details><summary><Plus size={14}/>Onboard repository</summary><form onSubmit={e=>{e.preventDefault();void work(async()=>{const r=await request<Repository>('/v1/repositories',{method:'POST',body:JSON.stringify({project_id:project,key:key.current,label,kind,...(kind==='pinned'?{case_id:'pallets__flask-4160'}:{source_sha256:source})})});await connect(r,true);key.current=crypto.randomUUID();setLabel('');});}}>
   <label>Name<input required minLength={2} maxLength={80} value={label} onChange={e=>{setLabel(e.target.value);key.current=crypto.randomUUID();}}/></label>
   <label>Source<select value={kind} onChange={e=>{setKind(e.target.value as typeof kind);key.current=crypto.randomUUID();}}><option value="pinned">Pinned Flask repository</option><option value="python">Onboarded Python app</option></select></label>
   {kind==='python'?<label>Reviewed source<select required value={source} onChange={e=>{setSource(e.target.value);key.current=crypto.randomUUID();}}><option value="">Choose source</option>{sources.map(s=><option key={s.sha256} value={s.sha256}>{s.label}</option>)}</select></label>:<p className="tiny">Uses the reviewed Flask Decimal execution profile. Other repositories need an explicitly supported adapter.</p>}
   <button disabled={busy||!label||(kind==='python'&&!source)}>Onboard and connect</button>
  </form></details>}</>}
 </details>;
}
