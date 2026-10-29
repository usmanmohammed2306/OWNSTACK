import { useEffect, useRef } from 'react';
import { ArrowRight, Code2, KeyRound, X } from 'lucide-react';

export function RequestComposer({ open, close, kind, setKind, text, setText, project, projectLabel,projects=[],setProject, viewer, setViewer, expiry, setExpiry, busy, error, save }: {
  open: boolean; close: () => void; kind: 'access' | 'feature'; setKind: (kind: 'access' | 'feature') => void;
  text: string; setText: (text: string) => void; project: string; projectLabel?: string | null; viewer: string; setViewer: (value: string) => void;
  projects?:{id:string;name:string}[];setProject?:(id:string)=>void;
  expiry: string; setExpiry: (value: string) => void; busy: boolean; error: string; save: () => Promise<void>;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const outcome = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (open && !dialog.current?.open) { dialog.current?.showModal(); outcome.current?.focus(); }
    if (!open && dialog.current?.open) dialog.current.close();
  }, [open]);
  return <dialog ref={dialog} className="request-dialog" aria-labelledby="request-composer-title" onClose={close}>
    <form onSubmit={event => { event.preventDefault(); if (!busy) void save(); }}>
      <div className="dialog-heading"><div><h2 id="request-composer-title">A few details first</h2></div><button type="button" className="icon-button" aria-label="Close new request" onClick={close}><X size={20}/></button></div>
      <p className="muted">Describe the change and confirm its scope.</p>
      <div className="switch" role="group" aria-label="Request type"><button type="button" aria-pressed={kind === 'access'} className={kind === 'access' ? 'chosen' : ''} onClick={() => setKind('access')}><KeyRound size={16}/> Temporary access</button><button type="button" aria-pressed={kind === 'feature'} className={kind === 'feature' ? 'chosen' : ''} onClick={() => setKind('feature')}><Code2 size={16}/> New feature</button></div>
      <label>What does your customer need?<textarea ref={outcome} required maxLength={3000} value={text} placeholder={kind === 'access' ? 'Let our contractor read this project until Friday.' : 'Let our team download a project as a PDF.'} onChange={event => setText(event.target.value)} rows={3}/></label>
      <div className="form-row"><label>Project{projects.length>1&&setProject?<select value={project} onChange={e=>setProject(e.target.value)}>{projects.map(p=><option value={p.id} key={p.id}>{p.name}</option>)}</select>:<input value={projectLabel || (project === 'atlas-project' ? 'Project Atlas' : project === 'nova-project' ? 'Project Nova' : project)} disabled/>}</label>{kind === 'access' && <><label>Person<input required value={viewer} placeholder="Teammate’s username" onChange={event => setViewer(event.target.value)}/></label><label>Access ends<input required type="datetime-local" value={expiry} onChange={event => setExpiry(event.target.value)}/></label></>}</div>
      {!project&&<p className="alert notice">Ask an administrator to assign a team before creating requests.</p>}
      <p className="tiny">{kind === 'access' ? 'Read-only access for one person, for up to seven days.' : 'An engineer reviews and checks new code before release.'}</p>
      {error && <p className="alert error" role="alert">{error}</p>}
      <div className="button-row"><button type="submit" className="primary" disabled={busy || !text.trim()||!project}>{busy ? 'Saving…' : 'Create request'} <ArrowRight size={16}/></button><button type="button" className="text-button" onClick={close}>Cancel</button></div>
    </form>
  </dialog>;
}
