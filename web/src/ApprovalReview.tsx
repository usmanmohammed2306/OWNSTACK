import { useId, useRef, useState } from 'react';
import { ArrowRight, LockKeyhole, X } from 'lucide-react';

type Props = {
  enabled: boolean;
  busy: boolean;
  admin: string;
  project: string | null;
  viewer: string | null;
  proposalHash: string;
  contract: string | null;
  version: number | null;
  preview: { snapshot_hash: string; expires_at: string; visible_documents: { title: string }[]; counterfactual: { checks: number; unexpected_delta_count: number } } | null;
  approve: () => Promise<void>;
};

export function ApprovalReview(props: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [reviewed, setReviewed] = useState(false);
  const titleId = useId();
  const checkboxId = useId();
  return <><button className="primary" disabled={!props.enabled || props.busy} onClick={() => dialog.current?.showModal()}>Review &amp; approve <ArrowRight size={14}/></button>
    <dialog className="approval-dialog" ref={dialog} aria-labelledby={titleId} onClose={() => setReviewed(false)}>
      <div className="command-heading"><div><p className="eyebrow">HUMAN APPROVAL GATE</p><h2 id={titleId}>One exact, temporary effect.</h2></div><button className="icon-button" aria-label="Close approval review" onClick={() => dialog.current?.close()}><X size={18}/></button></div>
      <p className="muted">You are approving this proposal, not giving the model permission to make future changes.</p>
      <dl className="approval-scope"><div><dt>PROJECT</dt><dd>{props.project}</dd></div><div><dt>CONTRACTOR</dt><dd>{props.viewer}</dd></div><div><dt>PERMISSION</dt><dd>Read-only</dd></div><div><dt>EXPIRES</dt><dd>{props.preview ? new Date(props.preview.expires_at).toLocaleString() : 'Preview required'}</dd></div></dl>
      <p className="approval-documents"><LockKeyhole size={15}/><span>Would reveal: {props.preview?.visible_documents.map(doc => doc.title).join(', ') || 'No previewed documents'}.</span></p>
      <div className="hash-line"><span>PROPOSAL / EXACT APPROVAL SUBJECT</span><code>{props.proposalHash}</code></div>
      <details><summary>Inspect contract and preview identity</summary><p className="tiny">{props.contract} v{props.version} · {props.preview?.counterfactual.checks} finite comparisons · {props.preview?.counterfactual.unexpected_delta_count} unexpected effects.</p><div className="hash-line"><span>PREVIEW SNAPSHOT</span><code>{props.preview?.snapshot_hash}</code></div></details>
      <p className="tiny">Approver: {props.admin}. The server rechecks role, scope, contract version and snapshot before activation. Another tenant remains outside this contract. Preview is a prediction, not an observed read.</p>
      <label className="approval-ack" htmlFor={checkboxId}><input id={checkboxId} type="checkbox" checked={reviewed} onChange={e => setReviewed(e.target.checked)}/><span>I reviewed this exact project, contractor, read-only permission and expiry.</span></label>
      <div className="button-row"><button className="secondary" onClick={() => dialog.current?.close()}>Keep in review</button><button className="primary" disabled={!reviewed || !props.enabled || props.busy} onClick={() => { dialog.current?.close(); void props.approve(); }}>Approve exact proposal <ArrowRight size={14}/></button></div>
    </dialog></>;
}
