import {useEffect,useRef,useState} from 'react';
import {Building2,ArrowLeft,ArrowRight,Plus,RefreshCw} from 'lucide-react';
import {RepositoryConnections} from './RepositoryConnections';
type Transport=<T>(path:string,options?:RequestInit)=>Promise<T>;
type Customer={id:string;name:string;key:string;enabled:boolean;revision:number};
type Inbox={id:string;customer_id:string;project_id:string;text:string;request_id:string|null;status:string};
type Project={id:string;name:string;enabled?:boolean;revision?:number};
type Person={id:string;name:string;enabled:boolean;revision:number};

/** Customer accounts are external organizations; staff teams stay in Organization. */
export function CustomerWorkspace({request,role,projects,openRequest}:{request:Transport;role:string;projects:Project[];openRequest:(id:string)=>void}){
  const [customers,setCustomers]=useState<Customer[]>([]),[inbox,setInbox]=useState<Inbox[]>([]),[selected,setSelected]=useState<Customer|null>(null);
  const [links,setLinks]=useState<Project[]>([]),[people,setPeople]=useState<Person[]>([]),[invitation,setInvitation]=useState('');
  const [error,setError]=useState(''),[busy,setBusy]=useState(false),[name,setName]=useState(''),[key,setKey]=useState(''),[project,setProject]=useState('');
  const active=useRef(true),writing=useRef(false);const admin=role==='admin';
  async function refresh(signal?:AbortSignal){const [c,i]=await Promise.all([request<Customer[]>('/v1/customers',{signal}),request<Inbox[]>('/v1/customers/inbox/requests',{signal})]);if(!signal?.aborted&&active.current){setCustomers(c);setInbox(i);}}
  useEffect(()=>{active.current=true;const c=new AbortController();refresh(c.signal).catch(e=>{if(!c.signal.aborted)setError(String(e));});return()=>{active.current=false;c.abort();};},[]);
  useEffect(()=>{setInvitation('');setLinks([]);setPeople([]);setProject('');if(!selected)return;const c=new AbortController();
    Promise.all([request<Project[]>(`/v1/customers/${selected.id}/projects`,{signal:c.signal}),admin?request<Person[]>(`/v1/customers/${selected.id}/people`,{signal:c.signal}):Promise.resolve([])]).then(([p,people])=>{if(!c.signal.aborted){setLinks(p);setPeople(people);}}).catch(e=>{if(!c.signal.aborted)setError(String(e));});return()=>c.abort();
  },[selected?.id,selected?.revision]);
  async function work(action:()=>Promise<void>){if(writing.current)return;writing.current=true;setBusy(true);setError('');try{await action();}catch(e){if(active.current)setError(String(e));}finally{writing.current=false;if(active.current)setBusy(false);}}
  return <section aria-label="Vendor customers" className="customer-workspace">
    {error&&<p role="alert" className="alert error">{error}</p>}
    {selected?<><button className="text-button" onClick={()=>setSelected(null)}><ArrowLeft size={15}/>Customers</button>
      <header className="person-heading"><Building2 size={32}/><div><h2>{selected.name}</h2><span>{selected.enabled?'Active customer':'Customer paused'}</span></div></header>
      <h3>Products</h3><div className="organization-chips">{links.map(p=><span key={p.id}>{p.name}{!p.enabled?' · disconnected':''}{admin&&<button disabled={busy} onClick={()=>void work(async()=>{const r=await request<Project>(`/v1/customers/${selected.id}/projects`,{method:'POST',body:JSON.stringify({project_id:p.id,expected_revision:p.revision,enabled:!p.enabled})});setLinks(v=>v.map(old=>old.id===p.id?{...old,...r}:old));})}>{p.enabled?'Disconnect':'Reconnect'}</button>}</span>)}</div>
      {admin&&selected.enabled&&<form onSubmit={e=>{e.preventDefault();void work(async()=>{await request(`/v1/customers/${selected.id}/projects`,{method:'POST',body:JSON.stringify({project_id:project,expected_revision:1,enabled:true})});setLinks(await request<Project[]>(`/v1/customers/${selected.id}/projects`));setProject('');});}}><label>Connect a product<select value={project} onChange={e=>setProject(e.target.value)}><option value="">Select product</option>{projects.filter(p=>!links.some(l=>l.id===p.id)).map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label><button disabled={!project||busy}>Connect</button></form>}
      <RepositoryConnections customerId={selected.id} projects={links} role={role} request={request}/>
      {admin&&<details><summary>Customer sign-in</summary><p>Invited people can send requests and see their own updates. They cannot access staff code or approvals.</p>
        <button disabled={busy||!selected.enabled} onClick={()=>void work(async()=>{const r=await request<{invitation:string}>(`/v1/customers/${selected.id}/invitations`,{method:'POST'});setInvitation(r.invitation);})}>Create invitation</button>
        {invitation&&<div><label>One-time invitation<input readOnly value={invitation}/></label><button onClick={()=>setInvitation('')}>Hide invitation</button></div>}
        <a href="/customer" target="_blank" rel="noreferrer">Open customer portal<ArrowRight size={15}/></a>
        {people.map(p=><p key={p.id}>{p.name} <button disabled={busy} onClick={()=>void work(async()=>{const r=await request<Person>(`/v1/customers/${selected.id}/people/${p.id}/status`,{method:'POST',body:JSON.stringify({expected_revision:p.revision,enabled:!p.enabled})});setPeople(v=>v.map(x=>x.id===p.id?{...x,...r}:x));})}>{p.enabled?'Disable sign-in':'Enable sign-in'}</button></p>)}
      </details>}
      {admin&&<details><summary>Account controls</summary><p>Pausing or reconnecting invalidates earlier customer-bound review evidence. Re-enabling requires fresh review.</p><button disabled={busy} onClick={()=>void work(async()=>{const r=await request<Customer>(`/v1/customers/${selected.id}/status`,{method:'POST',body:JSON.stringify({expected_revision:selected.revision,enabled:!selected.enabled})});setSelected(r);await refresh();})}>{selected.enabled?'Pause customer':'Resume customer'}</button></details>}
    </>:<><div className="list-heading"><h2>Customers</h2><button aria-label="Refresh customers" disabled={busy} onClick={()=>void work(()=>refresh())}><RefreshCw size={16}/></button></div>
      <div className="organization-grid">{customers.map(c=><button key={c.id} className="organization-team" onClick={()=>setSelected(c)}><Building2 size={26}/><strong>{c.name}</strong><span>{c.enabled?'Active':'Paused'}</span><ArrowRight size={16}/></button>)}</div>
      {!customers.length&&<p className="empty">Add a customer to connect their requests to your product.</p>}
      {admin&&<details><summary><Plus size={14}/> Add customer</summary><form onSubmit={e=>{e.preventDefault();void work(async()=>{await request('/v1/customers',{method:'POST',body:JSON.stringify({name,key})});setName('');setKey('');await refresh();});}}><label>Company name<input required minLength={2} maxLength={100} value={name} onChange={e=>setName(e.target.value)}/></label><label>Account key<input required pattern="[a-z0-9][a-z0-9-]+" value={key} onChange={e=>setKey(e.target.value)}/></label><button disabled={busy||!name||!key}>Add customer</button></form></details>}
    </>}
    <h3>Customer inbox</h3><div className="request-gallery">{inbox.filter(i=>!selected||i.customer_id===selected.id).map(i=><article key={i.id} className="customer-inbox-item"><small>{customers.find(c=>c.id===i.customer_id)?.name||'Customer'}</small><p>{i.text}</p>{i.request_id?<button onClick={()=>openRequest(i.request_id!)}>Open engineering request<ArrowRight size={15}/></button>:['admin','engineer'].includes(role)?<button disabled={busy} onClick={()=>void work(async()=>{const r=await request<{request_id:string}>(`/v1/customers/inbox/${i.id}/adopt`,{method:'POST'});await refresh();openRequest(r.request_id);})}>Start engineering review<ArrowRight size={15}/></button>:<span>Awaiting engineering triage</span>}</article>)}</div>
  </section>;
}
