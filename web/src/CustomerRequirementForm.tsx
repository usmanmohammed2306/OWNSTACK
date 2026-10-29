import {useState} from 'react';
import {customerRequirementDraft} from './customerRequirementDraft';

/** One guided entry route. Exact generated cases remain visible before saving. */
export function CustomerRequirementForm({tenant,owner,existing,busy,onSave}:{tenant:string;owner:string;existing:{spec:{key:string;version:number}}[];busy:boolean;onSave:(value:unknown)=>void}) {
  const [key,setKey]=useState('contractor-document-access'),[title,setTitle]=useState('Contractor document access');
  const [reference,setReference]=useState(''),[control,setControl]=useState(tenant==='nova'?'atlas':'nova');
  const [fields,setFields]=useState('id, title'),[at,setAt]=useState(()=>new Date().toISOString()),[error,setError]=useState('');
  const version=1+Math.max(0,...existing.filter(r=>r.spec.key===key).map(r=>r.spec.version));
  return <form aria-label="Draft customer requirement" onSubmit={event=>{
    event.preventDefault();setError('');
    try{onSave(customerRequirementDraft({key,title,reference,version,tenant,controlTenant:control,owner,fields,at}));}
    catch(e){setError(e instanceof Error?e.message:'Review the requirement fields.');}
  }}>
    <p>Protect a contractor read across releases. This saves a draft for separate approval.</p>
    <label>Requirement title<input value={title} disabled={busy} maxLength={240} onChange={e=>setTitle(e.target.value)}/></label>
    <label>Customer request or ticket<input value={reference} disabled={busy} maxLength={512} onChange={e=>setReference(e.target.value)}/></label>
    <label>Allowed response fields<input value={fields} disabled={busy} onChange={e=>setFields(e.target.value)}/></label>
    <p className="tiny">Three explicit checks: unassigned read denied, assigned read allowed, another customer hidden.</p>
    <details><summary>Test scope and version</summary>
      <label>Requirement key<input value={key} disabled={busy} maxLength={80} onChange={e=>setKey(e.target.value)}/></label>
      <label>Control customer key<input value={control} disabled={busy} onChange={e=>setControl(e.target.value)}/></label>
      <label>Read at, with timezone<input value={at} disabled={busy} onChange={e=>setAt(e.target.value)}/></label>
      <p className="tiny">Customer {tenant} · revision {version} · owner {owner}. These are test contexts, not permission grants.</p>
    </details>
    {error&&<p role="alert">{error}</p>}
    <button className="secondary" type="submit" disabled={busy||!reference.trim()}>Save requirement draft</button>
  </form>;
}
