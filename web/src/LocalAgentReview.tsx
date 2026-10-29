import {useEffect,useRef,useState} from 'react';
import {ArrowRight,BrainCircuit,Check,LoaderCircle,ScanLine,ShieldCheck} from 'lucide-react';
type State={stage:string;proposal_id?:string;generation?:number|null};
type Transport=<T>(path:string,options?:RequestInit)=>Promise<T>;
/** Real local inference prepares a bounded proposal. No animation authorizes it. */
export function LocalAgentReview({id,revision,request,prepared,onState}:{id:string;revision:number;request:Transport;prepared:()=>Promise<void>;onState?:(state:'idle'|'working'|'review'|'error')=>void}){
  const [state,setState]=useState<State>({stage:'ready'}),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const alive=useRef(true),ticket=useRef(0),controller=useRef<AbortController|null>(null),writing=useRef(false);
  const latest=useRef({request,prepared});latest.current={request,prepared};
  useEffect(()=>{onState?.(busy?'working':error?'error':state.stage==='proposal_saved'?'review':'idle');},[busy,error,state.stage,onState]);
  useEffect(()=>()=>onState?.('idle'),[onState]);
  useEffect(()=>{alive.current=true;const abort=new AbortController();controller.current=abort;
    void request<State>(`/v1/local-agent/requests/${id}`,{signal:abort.signal}).then(s=>{if(alive.current)setState(s);}).catch(()=>{});
    return()=>{alive.current=false;ticket.current++;controller.current?.abort();};},[id,revision]);
  useEffect(()=>{if(!['running','interpreting'].includes(state.stage))return;let current=true;const abort=new AbortController();
    const timer=setTimeout(()=>{void latest.current.request<State>(`/v1/local-agent/requests/${id}`,{signal:abort.signal}).then(async s=>{if(current&&alive.current){setState(s);if(s.proposal_id)await latest.current.prepared();}}).catch(()=>{if(current&&alive.current)setError('Could not refresh saved progress. Retry checking when ready.');});},1000);
    return()=>{current=false;abort.abort();clearTimeout(timer);};},[state,id]);
  async function prepare(){
    if(writing.current)return;writing.current=true;setBusy(true);setError('');const mine=++ticket.current;
    const abort=new AbortController();controller.current=abort;const timer=setTimeout(()=>abort.abort(),65000);
    try{
      const retry=['failed','timed_out','cancelled'].includes(state.stage)&&state.generation;
      const value=await latest.current.request<State>(`/v1/local-agent/requests/${id}/prepare`,{method:'POST',
        body:JSON.stringify({revision,...(retry?{retry_generation:state.generation}:{})}),signal:abort.signal});
      if(alive.current&&mine===ticket.current){setState(value);if(value.proposal_id)await latest.current.prepared();}
    }catch(e){if(alive.current&&mine===ticket.current){setError(abort.signal.aborted?'Stopped waiting. Check saved progress before retrying.':e instanceof Error?e.message:'The agent could not finish.');
      try{const saved=await latest.current.request<State>(`/v1/local-agent/requests/${id}`);if(alive.current&&mine===ticket.current)setState(saved);}catch{/* Error remains visible; never simulate a proposal. */}}}
    finally{clearTimeout(timer);writing.current=false;if(alive.current&&mine===ticket.current)setBusy(false);}
  }
  const saved=state.stage==='proposal_saved';
  return <section className="local-agent-review" aria-label="Request agent"><div className="local-agent-heading"><span className={busy?'agent-sigil is-working':'agent-sigil'}><BrainCircuit size={24}/></span><div><strong>{busy?'Understanding your request':saved?'Your proposal is saved':'From request to proposal'}</strong><p>{busy?'Checking the change against this app’s boundaries.':saved?'Review the exact effect before anything changes.':'Let the agent prepare a change you can review.'}</p></div></div>
    <div className="agent-route" aria-label="Request stages"><span><BrainCircuit size={16}/>Understand</span><i/><span><ScanLine size={16}/>Check scope</span><i/><span><ShieldCheck size={16}/>Your review</span></div>
    {!saved&&<button className="primary" disabled={busy} onClick={()=>void prepare()}>{busy?<LoaderCircle size={16}/>:<ArrowRight size={16}/>}{busy?'Preparing…':['failed','timed_out','cancelled'].includes(state.stage)?'Retry saved interpretation':'Prepare proposal'}</button>}
    {saved&&<span className="tiny"><Check size={13}/> Ready for exact review</span>}
    {error&&<p className="alert error" role="alert">{error}</p>}
    <details className="technical-disclosure"><summary>How this works</summary><p className="tiny">A local trained model proposes a route. The host checks scope and saves the proposal. It cannot approve access, run model-written commands or release code. No provider credits are used.</p></details>
  </section>;
}
