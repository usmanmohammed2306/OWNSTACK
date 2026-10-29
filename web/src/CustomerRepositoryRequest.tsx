import {useEffect,useRef,useState} from 'react';
import {ChangeAgent} from './ChangeAgent';
import {boundedResponse} from './responseDeadline';
type Transport=<T>(path:string,options?:RequestInit)=>Promise<T>;
type Options={customer_id:string|null;engineering_id:string|null;repositories:{id:string;label:string;kind:'pinned'|'python';source:{sha256?:string}}[]};
export function CustomerRepositoryRequest({requestId,projectId,role,aiMode,request,openReview,onConnected}:{requestId:string;projectId:string;role:string;aiMode:string;request:Transport;openReview:(id:string)=>void;onConnected?:(connected:boolean)=>void}){
 const [options,setOptions]=useState<Options|null>(null),[selected,setSelected]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const alive=useRef(true),pending=useRef(false),transport=useRef(request);transport.current=request;
 useEffect(()=>{alive.current=true;const c=new AbortController();transport.current<Options>(`/v1/repositories/request-options/${requestId}`,{signal:c.signal})
  .then(o=>{if(!c.signal.aborted){setOptions(o);setSelected(o.repositories[0]?.id||'');}}).catch(e=>{if(!c.signal.aborted)setError(String(e));});return()=>{alive.current=false;c.abort();};},[requestId]);
 const chosen=options?.repositories.find(r=>r.id===selected);
 useEffect(()=>{onConnected?.(!!options?.customer_id&&chosen?.kind==='pinned');return()=>onConnected?.(false);},[requestId,options?.customer_id,chosen?.kind]);
 if(error)return <p role="alert" className="alert error">{error}</p>;
 if(!options)return <p role="status">Loading repository connections…</p>;
 if(!options.customer_id||!options.repositories.length)return <ChangeAgent requestId={requestId} projectId={projectId} role={role} aiMode={aiMode} request={request}/>;
 return <section aria-label="Customer repository" className="customer-repository"><label>Repository<select value={selected} disabled={busy} onChange={e=>setSelected(e.target.value)}>{options.repositories.map(r=><option key={r.id} value={r.id}>{r.label}</option>)}</select></label>
  {chosen?.kind==='python'?<ChangeAgent key={chosen.id} repositoryId={chosen.id} sourcePin={chosen.source.sha256} requestId={requestId} projectId={projectId} role={role} aiMode={aiMode} request={request}/>:<><p>Review the patch against upstream tests and approved customer behavior.</p><button disabled={busy||role!=='engineer'} onClick={async()=>{if(pending.current||!chosen)return;pending.current=true;setBusy(true);setError('');try{const r=await boundedResponse(signal=>transport.current<{engineering_id:string}>('/v1/repositories/handoff',{signal,method:'POST',body:JSON.stringify({request_id:requestId,repository_id:chosen.id})})).promise;if(alive.current)openReview(r.engineering_id);}catch(e){if(alive.current)setError(String(e));}finally{pending.current=false;if(alive.current)setBusy(false);}}}>{busy?'Opening…':'Open code review'}</button></>}
 </section>;
}
