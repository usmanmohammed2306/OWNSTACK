import { useEffect, useRef } from 'react';
import { ArrowRight, Code2, KeyRound, X } from 'lucide-react';

export function RequestComposer({ open, close, kind, setKind, text, setText, project, viewer, setViewer, expiry, setExpiry, busy, error, save }: {
  open: boolean; close: () => void; kind: 'access' | 'feature'; setKind: (kind: 'access' | 'feature') => void;
  text: string; setText: (text: string) => void; project: string; viewer: string; setViewer: (value: string) => void;
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
      <div className="dialog-heading"><div><p className="eyebrow">START SMALL. KEEP IT SCOPED.</p><h2 id="request-composer-title">What should change?</h2></div><button type="button" className="icon-button" aria-label="Close new request" onClick={close}><X size={20}/></button></div>
      <p className="muted">Describe one customer's need. Saving creates a request, not an access grant or an AI call.</p>
      <div className="switch" role="group" aria-label="Request type"><button type="button" aria-pressed={kind === 'access'} className={kind === 'access' ? 'chosen' : ''} onClick={() => setKind('access')}><KeyRound size={16}/> Temporary access</button><button type="button" aria-pressed={kind === 'feature'} className={kind === 'feature' ? 'chosen' : ''} onClick={() => setKind('feature')}><Code2 size={16}/> New feature</button></div>
      <label>Desired outcome<textarea ref={outcome} required maxLength={4000} value={text} onChange={event => setText(event.target.value)} rows={4}/></label>
      <div className="form-row"><label>Project<input value={project} disabled/></label>{kind === 'access' && <><label>Viewer<input required value={viewer} onChange={event => setViewer(event.target.value)}/></label><label>Expires at<input required type="datetime-local" value={expiry} onChange={event => setExpiry(event.target.value)}/></label></>}</div>
      <p className="tiny">{kind === 'access' ? 'Read-only, project-scoped and time-limited. The server validates the scope.' : 'A feature request goes to engineering review. It cannot become a configuration shortcut.'}</p>
      {error && <p className="alert error" role="alert">{error}</p>}
      <div className="button-row"><button type="submit" className="primary" disabled={busy || !text.trim()}>{busy ? 'Saving…' : 'Save request'} <ArrowRight size={16}/></button><button type="button" className="secondary" onClick={close}>Back to workspace</button></div>
    </form>
  </dialog>;
}
