import {useEffect,useRef,useState} from 'react';
import {Check,GitBranch,X,Upload} from 'lucide-react';
type Transport=<T>(path:string,options?:RequestInit)=>Promise<T>;
type Pattern={id:string;hash:string;title:string;kind:string;count:number;evidence:string;locations:{path?:string;line?:number;name?:string;text?:string}[]};
type State={request_id:string;revision:number;customer_text:string;patterns:Pattern[];choices:Record<string,{decision:string;note:string;pattern_hash:string}>;can_edit:boolean;code_files:number};

export function RequestPatterns({id,revision,role,request,changed}: {id:string;revision:number;role:string;request:Transport;changed:()=>Promise<void>}){
  const [data,setData]=useState<State|null>(null),[chosen,setChosen]=useState<{pattern:Pattern;decision:'use'|'drop'}|null>(null),[note,setNote]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const writing=useRef(false),pending=useRef<string|null>(null),upload=useRef<HTMLInputElement>(null);
  useEffect(()=>{const c=new AbortController();setData(null);setChosen(null);setError('');
    request<State>(`/v1/requests/${id}/patterns`,{signal:c.signal}).then(s=>{if(!c.signal.aborted&&s.request_id===id&&s.revision===revision)setData(s);}).catch(e=>{if(!c.signal.aborted)setError(String(e));});return()=>c.abort();
  },[id,revision]);
  async function save(){if(!chosen||!data||writing.current)return;writing.current=true;setBusy(true);setError('');pending.current||=crypto.randomUUID();
    try{await request(`/v1/requests/${id}/patterns/decision`,{method:'POST',headers:{'Idempotency-Key':pending.current},body:JSON.stringify({expected_revision:data.revision,pattern_id:chosen.pattern.id,pattern_hash:chosen.pattern.hash,decision:chosen.decision,note})});setChosen(null);pending.current=null;await changed();}
    catch(e){setError(String(e));}finally{writing.current=false;setBusy(false);}}
  async function connect(files:FileList|null){if(!files?.length||!data||writing.current)return;writing.current=true;setBusy(true);setError('');
    try{if(files.length>20)throw new Error('Select up to 20 Python files.');let size=0;const source:Record<string,string>={};for(const f of Array.from(files)){size+=f.size;if(f.size>64000||size>256000)throw new Error('Source snapshot is too large.');if(source[f.name]!==undefined)throw new Error('Files need distinct names.');source[f.name]=await f.text();}
      await request(`/v1/requests/${id}/code-context`,{method:'POST',body:JSON.stringify({expected_revision:data.revision,files:source})});await changed();
    }catch(e){setError(String(e));}finally{writing.current=false;setBusy(false);if(upload.current)upload.current.value='';}}
  return <section className="request-patterns" aria-label="Reusable patterns">
    <header><span><GitBranch size={16}/>Reuse</span>{role==='engineer'&&data?.can_edit&&<><input type="file" ref={upload} hidden multiple accept=".py" onChange={e=>void connect(e.target.files)}/><button className="text-button" disabled={busy} onClick={()=>upload.current?.click()} title="Index up to 20 selected Python source files. Files remain private; no code is executed."><Upload size={13}/>{data.code_files?'Update code':'Connect code'}</button></>}</header>
    {error&&<p className="alert error" role="alert">{error}</p>}
    {!data&&!error&&<span role="status">Finding saved patterns…</span>}
    {data?.patterns.map(p=><div className="reuse-candidate" key={p.id}><div><strong title={p.evidence}>{p.title}</strong><small>{p.count} occurrences{data.choices[p.id]?' · '+data.choices[p.id].decision:''}</small></div><div><button aria-label={`Use ${p.title}`} title={data.can_edit?'Add context for reuse':'This request is already in review'} disabled={!data.can_edit||busy} onClick={()=>{pending.current=null;setChosen({pattern:p,decision:'use'});setNote(data.choices[p.id]?.note||'');}}><Check size={15}/>Use</button><button aria-label={`Drop ${p.title}`} title={data.can_edit?'Explain why to avoid this pattern':'This request is already in review'} disabled={!data.can_edit||busy} onClick={()=>{pending.current=null;setChosen({pattern:p,decision:'drop'});setNote(data.choices[p.id]?.note||'');}}><X size={15}/>Drop</button></div></div>)}
    {data&&!data.patterns.length&&<p className="tiny" title="Matches come from scoped saved requests and the connected Python source snapshot. No AI similarity result is claimed.">No supported reuse found yet.</p>}
    {chosen&&<form className="reuse-context" onSubmit={e=>{e.preventDefault();void save();}}><label>{chosen.decision==='use'?'How should this pattern be used?':'What should be done instead?'}<textarea aria-label="Additional engineering context" required minLength={5} maxLength={800} value={note} onChange={e=>{setNote(e.target.value);pending.current=null;}} rows={3} autoFocus/></label><div><button type="submit" className="primary" disabled={busy||note.trim().length<5}>{busy?'Saving…':'Save context'}</button><button type="button" className="text-button" disabled={busy} onClick={()=>setChosen(null)}>Cancel</button></div></form>}
  </section>;
}
