import {useEffect,useRef,useState} from 'react';
import {ArrowRight,Building2,LogOut,RefreshCw} from 'lucide-react';
import {boundedResponse} from './responseDeadline';
type Account={id:string;name:string};
type Session={token:string;name:string;customer:Account};
type Me={name:string;customer:Account;projects:{id:string;name:string}[]};
type Submission={id:string;project_id:string;text:string;status:string;review_update:string|null;released:false};

/** Separate customer surface. Tokens remain in memory and are never staff cookies. */
export function CustomerPortal(){
  const [session,setSession]=useState<Session|null>(null),[me,setMe]=useState<Me|null>(null),[items,setItems]=useState<Submission[]>([]);
  const [register,setRegister]=useState(false),[username,setUsername]=useState(''),[password,setPassword]=useState(''),[name,setName]=useState(''),[invitation,setInvitation]=useState('');
  const [text,setText]=useState(''),[project,setProject]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const mounted=useRef(true),writing=useRef(false),pendingKey=useRef<{intent:string;key:string}|null>(null);
  const token=useRef<string|null>(null);token.current=session?.token||null;
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;token.current=null;};},[]);
  async function call<T>(path:string,options:RequestInit={},credential=token.current):Promise<T>{
    const pending=boundedResponse(async signal=>{const r=await fetch('/v1/customer-portal'+path,{...options,signal,credentials:'omit',headers:{'Content-Type':'application/json',...(credential?{Authorization:'Bearer '+credential}:{}),...options.headers}});const b=await r.json();if(!r.ok){if(r.status===401&&credential&&credential===token.current&&mounted.current){token.current=null;setSession(null);setMe(null);setItems([]);setText('');pendingKey.current=null;}throw new Error(typeof b.detail==='string'?b.detail:'Check your entries and try again.');}return b as T;});return pending.promise;
  }
  async function refresh(credential=token.current){const [m,i]=await Promise.all([call<Me>('/me',{},credential),call<Submission[]>('/requests',{},credential)]);if(mounted.current&&credential===token.current){setMe(m);setItems(i);setProject(old=>m.projects.some(p=>p.id===old)?old:m.projects[0]?.id||'');}}
  async function work(action:()=>Promise<void>){if(writing.current)return;writing.current=true;setBusy(true);setError('');try{await action();}catch(e){if(mounted.current)setError(String(e));}finally{writing.current=false;if(mounted.current)setBusy(false);}}
  return <main className="customer-portal"><header><a href="/">OwnStack</a>{session&&<button disabled={busy} onClick={()=>void work(async()=>{await call('/logout',{method:'POST'});token.current=null;setSession(null);setMe(null);setItems([]);setText('');pendingKey.current=null;})}><LogOut size={16}/>Sign out</button>}</header>
    {error&&<p className="alert error" role="alert">{error}</p>}
    {!session?<section aria-label="Customer sign-in"><Building2 size={34}/><h1>{register?'Join your customer account':'Customer sign-in'}</h1><p>Requests and updates for your company.</p><form onSubmit={e=>{e.preventDefault();void work(async()=>{const result=await call<Session>(register?'/register':'/session',{method:'POST',body:JSON.stringify({username,password,...(register?{name,invitation}: {})})},null);if(!mounted.current)return;token.current=result.token;setSession(result);setPassword('');setInvitation('');await refresh(result.token);});}}>
      {register&&<><label>Invitation<input required value={invitation} onChange={e=>setInvitation(e.target.value)} autoComplete="off"/></label><label>Your name<input required value={name} onChange={e=>setName(e.target.value)} autoComplete="name"/></label></>}
      <label>Username<input required value={username} onChange={e=>setUsername(e.target.value)} autoComplete="username"/></label><label>Passphrase<input required type="password" minLength={register?12:1} maxLength={128} value={password} onChange={e=>setPassword(e.target.value)} autoComplete={register?'new-password':'current-password'}/></label><button disabled={busy}>{busy?'Please wait…':register?'Create customer account':'Sign in'}<ArrowRight size={16}/></button>
    </form><button disabled={busy} className="text-button" onClick={()=>{setRegister(!register);setError('');setPassword('');}}>{register?'Already registered? Sign in':'Have an invitation? Join'}</button></section>:<section aria-label="Customer requests"><div className="list-heading"><div><small>{session.customer.name}</small><h1>Your requests</h1></div><button aria-label="Refresh customer requests" disabled={busy} onClick={()=>void work(()=>refresh())}><RefreshCw size={16}/></button></div>
      {!me?<p role="status">Loading your connected products…</p>:!me.projects.length?<p>No products are connected. Ask your vendor to connect one.</p>:<form onSubmit={e=>{e.preventDefault();void work(async()=>{const intent=JSON.stringify({project_id:project,text});if(pendingKey.current?.intent!==intent)pendingKey.current={intent,key:crypto.randomUUID()};await call('/requests',{method:'POST',body:JSON.stringify({project_id:project,text,idempotency_key:pendingKey.current.key})});setText('');pendingKey.current=null;await refresh();});}}><label>Product<select value={project} onChange={e=>setProject(e.target.value)}>{me.projects.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label><label>What would you like to change?<textarea required minLength={10} maxLength={3000} value={text} onChange={e=>setText(e.target.value)} placeholder="Describe what your team needs and why it matters."/></label><button disabled={busy||text.trim().length<10}>Send request<ArrowRight size={16}/></button></form>}
      <div className="customer-request-list">{items.map(i=><article key={i.id}><small>{i.status==='received'?'Received':'With engineering'}</small><p>{i.text}</p>{i.review_update&&<p className="customer-review-update">{i.review_update}</p>}</article>)}</div>
    </section>}
  </main>;
}
