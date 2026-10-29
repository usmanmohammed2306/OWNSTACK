import {useEffect,useRef,useState} from 'react';
import {boundedResponse} from './responseDeadline';
type Transport=<T>(path:string,options?:RequestInit)=>Promise<T>;
type Review={check_id:string;revision:number;evidence_hash:string;state:string;decision:string|null;source_diff:string;candidate_sha256:string;customer_submission_id?:string|null;customer_review_shared?:boolean;comments:{actor:string;comment:string}[]};
export function AgentPatchReview({sessionId,checkId,role,request,stale=false}:{sessionId:string;checkId:string;role:string;request:Transport;stale?:boolean}){
 const [review,setReview]=useState<Review|null>(null),[comment,setComment]=useState(''),[decision,setDecision]=useState('comment'),[ack,setAck]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const alive=useRef(true),pending=useRef(false),key=useRef(crypto.randomUUID());
 const shared=review?.customer_review_shared===true;
 const path=`/v1/change-agents/${sessionId}/checks/${checkId}/review`;
 useEffect(()=>{alive.current=true;const c=new AbortController();request<Review>(path,{signal:c.signal}).then(r=>{if(!c.signal.aborted)setReview(r);}).catch(e=>{if(!c.signal.aborted)setError(String(e));});return()=>{alive.current=false;c.abort();};},[path]);
 async function submit(){if(!review||pending.current)return;pending.current=true;setBusy(true);setError('');
  try{await boundedResponse(signal=>request(path,{signal,method:'POST',body:JSON.stringify({expected_revision:review.revision,evidence_hash:review.evidence_hash,comment,decision,idempotency_key:key.current})})).promise;
   const next=await request<Review>(path);if(alive.current){setReview(next);setComment('');setDecision('comment');setAck(false);key.current=crypto.randomUUID();}
  }catch(e){if(alive.current)setError(String(e)+' Refresh saved review before retrying.');}finally{pending.current=false;if(alive.current)setBusy(false);}}
 return <section aria-label="Counterexample patch review" className="minimal-code-review">{error&&<p role="alert" className="alert error">{error}</p>}{review&&<>
  <header><span role="status" className="review-check">{stale?'Historical evidence':review.decision==='accept_for_manual_release'?'Accepted · not released':review.state==='passed'?'Independent checks passed':review.state}</span></header>
  <pre className="review-source" tabIndex={0} aria-label="Repair diff against failed candidate">{review.source_diff}</pre>
  <div className="review-comments">{review.comments.map((c,i)=><article key={i}><strong>{c.actor}</strong><p>{c.comment}</p></article>)}</div>
  {review.customer_submission_id&&review.decision==='accept_for_manual_release'&&!stale&&['admin','engineer'].includes(role)&&<div><button disabled={busy||shared} onClick={async()=>{if(pending.current)return;pending.current=true;setBusy(true);setError('');try{await boundedResponse(signal=>request(`/v1/customers/inbox/${review.customer_submission_id}/share-review`,{signal,method:'POST',body:JSON.stringify({discovery_id:sessionId,check_id:checkId,evidence_hash:review.evidence_hash})})).promise;if(alive.current)setReview({...review,customer_review_shared:true});}catch(e){if(alive.current)setError(String(e));}finally{pending.current=false;if(alive.current)setBusy(false);}}}>{shared?'Customer update shared':'Share reviewed status with customer'}</button><p className="tiny">Only the review status is shared. Code and internal comments stay private; release is not confirmed.</p></div>}
  <form onSubmit={e=>{e.preventDefault();void submit();}}><label>Your patch review<textarea aria-label="Counterexample review comment" required minLength={2} maxLength={2000} value={comment} disabled={busy} onChange={e=>{setComment(e.target.value);key.current=crypto.randomUUID();}}/></label>
   {['admin','engineer'].includes(role)&&!review.decision&&<label>Decision<select value={decision} disabled={busy} onChange={e=>{setDecision(e.target.value);setAck(false);key.current=crypto.randomUUID();}}><option value="comment">Comment only</option><option value="accept_for_manual_release" disabled={stale||review.state!=='passed'}>Accept for manual release review</option><option value="reject">Request changes</option></select></label>}
   {decision!=='comment'&&<label><input type="checkbox" checked={ack} onChange={e=>setAck(e.target.checked)}/>I reviewed this exact candidate and independent evidence. Nothing will deploy.</label>}
   <button className="primary" disabled={busy||comment.trim().length<2||(decision!=='comment'&&!ack)}>Submit review</button>
  </form>
 </>}</section>;
}
