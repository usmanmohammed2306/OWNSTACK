import {useEffect,useRef,useState} from 'react';
import {boundedResponse} from './responseDeadline';
import {AgentPatchReview} from './AgentPatchReview';
import {forgetDiscoveryAfter} from './discoveryReadRecovery';
type Transport=<T>(path:string,options?:RequestInit)=>Promise<T>;
type Agent={id:string;revision:number;status:string;source_sha256:string;repository?:{repository_id:string}|null;needs_fresh_discovery?:boolean;local_wait_expired?:boolean;error?:string|null;answers:Record<string,unknown>;missing:string[];questions:Record<string,string>;policy_hash:string|null;
 last_decision:{action:string;field:string|null;reason:string;citations:string[];facts?:Record<string,unknown>;quotes?:{field:string;source:string;quote:string}[]}|null;last_usage?:{live:boolean;model?:string};operation:{deadline:string}|null;
 requirement_ids:string[];runs?:{check_id:string;state:string;attempts:number;trace:{tool:string;state?:string;count?:number}[]}[]};
type Source={project_id:string;label:string;sha256:string};

/** One persisted request -> explicit answers -> exact approval -> observed checks.
 * The UI never runs candidate code or treats an agent explanation as evidence. */
export function ChangeAgent({requestId,projectId,role,aiMode,request,repositoryId,sourcePin}:{requestId:string;projectId:string;role:string;aiMode:string;request:Transport;repositoryId?:string;sourcePin?:string}){
 const [savedAgent,setAgent]=useState<Agent|null>(null),[sources,setSources]=useState<Source[]>([]),[source,setSource]=useState('');
 const [readUnverified,setReadUnverified]=useState(false),[loadEpoch,setLoadEpoch]=useState(0);
 const knownId=useRef<string|null>(null),readScope=useRef('');
 const agent=savedAgent&&readUnverified?{...savedAgent,needs_fresh_discovery:true}:savedAgent;
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[roles,setRoles]=useState<string[]>(['manager']),[flag,setFlag]=useState(false),[fields,setFields]=useState('id,title'),[denial,setDenial]=useState('403'),[ack,setAck]=useState(false);
 const [reviewId,setReviewId]=useState<string|null>(null);
 const alive=useRef(true),writing=useRef(false),key=useRef(crypto.randomUUID()),generation=useRef(0),transport=useRef(request);transport.current=request;
 async function refresh(id?:string){const mine=++generation.current;
  try{const current=id||agent?.id;if(!current)return;knownId.current=current;
   const next=await boundedResponse(signal=>transport.current<Agent>(`/v1/change-agents/${current}`,{signal})).promise;
   if(alive.current&&mine===generation.current&&next.id===current){setAgent(repositoryId&&next.repository?.repository_id!==repositoryId?null:next);setReadUnverified(false);setError('');}
  }catch(e){if(alive.current&&mine===generation.current){if(forgetDiscoveryAfter(e)){setAgent(null);knownId.current=null;}setReadUnverified(true);setError(String(e));}}}
 useEffect(()=>{alive.current=true;const controller=new AbortController();
  const scope=JSON.stringify([requestId,projectId,repositoryId,sourcePin]);
  if(readScope.current!==scope){readScope.current=scope;knownId.current=null;setAgent(null);setReadUnverified(false);setError('');}
  Promise.all([transport.current<Source[]>('/v1/release/sources',{signal:controller.signal}),transport.current<{id:string}[]>('/v1/change-agents?'+new URLSearchParams({request_id:requestId}),{signal:controller.signal})])
   .then(([rows,sessions])=>{if(!controller.signal.aborted){setSources(rows.filter(r=>r.project_id===projectId&&(!sourcePin||r.sha256===sourcePin)));if(sourcePin)setSource(sourcePin);if(sessions[0])void refresh(sessions[0].id);else{setAgent(null);knownId.current=null;setReadUnverified(false);setError('');}}}).catch(e=>{if(!controller.signal.aborted){setReadUnverified(true);setError(String(e));}});
  return()=>{alive.current=false;generation.current++;controller.abort();};
 },[requestId,projectId,repositoryId,sourcePin,loadEpoch]);
 useEffect(()=>{if(!agent?.id)return;const timer=setInterval(()=>{if(!writing.current&&document.visibilityState==='visible')void refresh(agent.id);},10000);return()=>clearInterval(timer);},[agent?.id]);
 useEffect(()=>{setAck(false);setFlag(false);},[agent?.revision]);
 async function mutate(path:string,body:object){if(readUnverified){setError('Refresh saved progress before changing this discovery.');return;}if(writing.current)return;writing.current=true;setBusy(true);setError('');const mine=++generation.current;
  try{const next=await boundedResponse(signal=>transport.current<Agent>(path,{signal,method:'POST',body:JSON.stringify(body)})).promise;
   if(alive.current&&mine===generation.current){
    // Mutation receipts omit observed run history. Keep it for this same session
    // until the authoritative refresh; never carry another session's evidence.
    setAgent(current=>next.runs===undefined&&current?.id===next.id?{...next,runs:current.runs}:next);
    setAck(false);key.current=crypto.randomUUID();}
  }catch(e){if(alive.current&&mine===generation.current)setError(String(e)+' Refresh saved progress before retrying.');}
  finally{writing.current=false;if(alive.current&&mine===generation.current)setBusy(false);}}
 async function guardedReview<T>(path:string,options?:RequestInit):Promise<T>{if(readUnverified&&options?.method&&options.method!=='GET')throw new Error('Refresh saved progress before changing this review.');return request<T>(path,options);}
 const canWrite=!readUnverified&&(role==='engineer'||role==='admin');const field=agent?.last_decision?.action==='ask'&&agent.missing.includes(agent.last_decision.field||'')?agent.last_decision.field!:agent?.missing[0];
 function answer(){if(!agent||!field)return;const value=field==='roles'?roles:field==='visible_fields'?fields.split(',').map(x=>x.trim()).filter(Boolean):field==='denial_status'?Number(denial):flag;
  void mutate(`/v1/change-agents/${agent.id}/answers`,{expected_revision:agent.revision,answers:{[field]:value}});}
 return <section className="change-agent" aria-label="Change agent"><header><strong>Define & verify</strong>{agent&&<span role="status">{readUnverified?'Reconnect to verify':agent.needs_fresh_discovery?'Context changed':agent.local_wait_expired?'Wait expired':agent.operation?'Preparing proposal':agent.status.replaceAll('_',' ')}</span>}</header>
  {error&&<p role="alert" className="alert error">{error}</p>}
  {readUnverified&&<><p role="status">Saved evidence is unverified while disconnected. Reconnect before changing it; no new work has started.</p><button className="secondary" disabled={busy} onClick={()=>knownId.current?void refresh(knownId.current):setLoadEpoch(n=>n+1)}>Retry saved progress</button></>}
  {!agent?!readUnverified&&<><p>Connect the reviewed source, then define the behavior this change must preserve.</p><label>Reviewed source<select aria-label="Discovery source" value={source} onChange={e=>setSource(e.target.value)}><option value="">Choose a source</option>{sources.map(s=><option key={s.sha256} value={s.sha256}>{s.label}</option>)}</select></label><button className="primary" disabled={!canWrite||!source||busy} onClick={()=>void mutate('/v1/change-agents',{request_id:requestId,source_sha256:source,idempotency_key:key.current,...(repositoryId?{repository_id:repositoryId}:{})})}>Start discovery</button></>:<>
   {agent.last_decision&&<p className="agent-rationale">{agent.last_decision.reason}<small>{agent.last_usage?.live?'Model decision':'Controlled local decision'} · {agent.last_decision.citations.join(', ')}</small></p>}
   {!readUnverified&&agent.needs_fresh_discovery&&<p role="status">This discovery is no longer current. Start a revised discovery before accepting new work.</p>}
   {!agent.needs_fresh_discovery&&(agent.local_wait_expired||agent.error==='LOCAL_WAIT_EXPIRED')&&<p role="status">The local wait expired. Saved evidence is available. Remote inference cancellation is unverified.</p>}
   {!agent.needs_fresh_discovery&&agent.last_decision?.action==='suggest_answers'&&canWrite&&Object.keys(agent.last_decision.facts||{}).every(k=>agent.missing.includes(k))&&<form onSubmit={e=>{e.preventDefault();void mutate(`/v1/change-agents/${agent.id}/answers`,{expected_revision:agent.revision,answers:agent.last_decision!.facts});}}><strong>Suggested answers</strong><p>{Object.entries(agent.last_decision.facts||{}).map(([k,v])=>`${k.replaceAll('_',' ')}: ${Array.isArray(v)?v.join(', '):String(v)}`).join(' · ')}</p><details><summary>Quoted evidence</summary>{agent.last_decision.quotes?.map((q,i)=><blockquote key={i}><small>{q.source} · {q.field.replaceAll('_',' ')}</small><p>{q.quote}</p></blockquote>)}</details><label><input type="checkbox" checked={ack} onChange={e=>setAck(e.target.checked)}/>I confirm these values match our intended behavior.</label><button className="secondary" disabled={busy||!ack}>Confirm suggested answers</button></form>}
   {!agent.needs_fresh_discovery&&field&&canWrite&&agent.status!=='running'&&<form onSubmit={e=>{e.preventDefault();answer();}}><label>{agent.questions[field]}</label>
    {field==='roles'?<div className="organization-chips">{['contractor','member','engineer','manager','admin'].map(r=><label key={r}><input type="checkbox" checked={roles.includes(r)} onChange={e=>setRoles(e.target.checked?[...roles,r]:roles.filter(x=>x!==r))}/>{r}</label>)}</div>:field==='visible_fields'?<input aria-label="Allowed fields" value={fields} onChange={e=>setFields(e.target.value)} required/>:field==='denial_status'?<select aria-label="Denied response" value={denial} onChange={e=>setDenial(e.target.value)}><option value="403">403 · forbidden</option><option value="404">404 · not found</option></select>:<label><input type="checkbox" checked={flag} onChange={e=>setFlag(e.target.checked)}/>Yes</label>}
    <button className="secondary" disabled={busy||(field==='roles'&&!roles.length)}>Save answer</button></form>}
   {agent.needs_fresh_discovery?null:agent.operation?<><p>Model operation saved. Refreshing does not start another call.</p><button className="secondary" disabled={busy||!canWrite} onClick={()=>void mutate(`/v1/change-agents/${agent.id}/cancel`,{expected_revision:agent.revision})}>Stop local wait</button></>:canWrite&&['clarifying','ready','failed'].includes(agent.status)&&<button className="secondary" disabled={busy||aiMode==='off'} title={aiMode==='off'?'Remote inference stays paused for this local rehearsal. Explicit answers remain available.':'Ask the agent to choose the next consequential question'} onClick={()=>void mutate(`/v1/change-agents/${agent.id}/step`,{expected_revision:agent.revision,idempotency_key:key.current})}>Ask the agent</button>}
   {!agent.missing.length&&<><details open={agent.status==='ready'||agent.status==='published'}><summary>Expected behavior</summary><dl className="agent-policy">{Object.entries(agent.answers).map(([k,v])=><div key={k}><dt>{({roles:'Allowed roles',requires_assignment:'Assignment required',temporary_grants:'Temporary grants',visible_fields:'Visible fields',denial_status:'Denied response'} as Record<string,string>)[k]||k}</dt><dd>{Array.isArray(v)?v.join(', '):typeof v==='boolean'?v?'Yes':'No':String(v)}</dd></div>)}</dl></details>
    {!agent.needs_fresh_discovery&&['ready','failed'].includes(agent.status)&&canWrite&&<><label><input type="checkbox" checked={ack} onChange={e=>setAck(e.target.checked)}/>I reviewed this behavior and the 144-case visibility domain.</label><button className="primary" disabled={!ack||busy} onClick={()=>void mutate(`/v1/change-agents/${agent.id}/publish`,{expected_revision:agent.revision,policy_hash:agent.policy_hash})}>Prepare review</button></>}
    {!agent.needs_fresh_discovery&&agent.status==='published'&&role==='admin'&&<><label><input type="checkbox" checked={ack} onChange={e=>setAck(e.target.checked)}/>I approve these exact expected outcomes.</label><button className="primary" disabled={!ack||busy} onClick={()=>void mutate(`/v1/change-agents/${agent.id}/approve`,{expected_revision:agent.revision,policy_hash:agent.policy_hash})}>Approve behavior</button></>}
    {!agent.needs_fresh_discovery&&agent.status==='published'&&role!=='admin'&&<p>Waiting for a different administrator to approve the exact behavior.</p>}
    {!agent.needs_fresh_discovery&&agent.status==='approved'&&<p>Behavior approved. Repository checks run through the local operator; passing results still need human release review.</p>}
   </>}
   {agent.runs?.slice(0,1).map(run=><article key={run.check_id}><strong>{run.state==='ready_for_human_review'?'Latest checked candidate':run.state.replaceAll('_',' ')}</strong><p>{run.attempts} checked candidate versions · not released</p><details><summary>Agent evidence</summary><ol>{run.trace.map((t,i)=><li key={i}>{t.tool.replaceAll('_',' ')}{t.state?' · '+t.state:''}{t.count!==undefined?' · '+t.count+' failures':''}</li>)}</ol></details><button className="secondary" onClick={()=>setReviewId(reviewId===run.check_id?null:run.check_id)}>{reviewId===run.check_id?'Close review':'Review checked patch'}</button>{reviewId===run.check_id&&<AgentPatchReview key={run.check_id} sessionId={agent.id} stale={agent.needs_fresh_discovery} checkId={run.check_id} role={role} request={guardedReview}/>}</article>)}
   {(agent.runs?.length||0)>1&&<details><summary>Earlier execution history</summary><ul>{agent.runs?.slice(1).map(run=><li key={run.check_id}>{run.check_id.slice(0,8)} · {run.attempts} versions · historical, not released</li>)}</ul></details>}
   <button className="text-button" disabled={busy} onClick={()=>void refresh(agent.id)}>Refresh progress</button>
   {canWrite&&(agent.needs_fresh_discovery||!agent.operation)&&<button className="text-button" disabled={busy} onClick={()=>{setSource(agent.source_sha256);setAgent(null);setError('');key.current=crypto.randomUUID();}}>Revise behavior</button>}
  </>}
 </section>;
}
