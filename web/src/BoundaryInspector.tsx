import { ArrowUpRight, Check, Circle, LockKeyhole, ShieldCheck } from 'lucide-react';
import { attributedReads } from './review';

type Props = {
  request: { id: string; project_id: string | null; viewer_id: string | null; status: string; kind: string };
  proposal: { route: string; contract_version: number | null; proposal_hash: string; status: string } | null;
  preview: { matches_saved_proposal: boolean; counterfactual: { checks: number; unexpected_delta_count: number } } | null;
  events: { request_id: string; type: string; payload: Record<string, unknown> }[];
  observations: { variation_id: string | null; allowed: boolean; project_id: string; actor_id: string }[];
  openLedger: () => void;
};

export function BoundaryInspector({ request, proposal, preview, events, observations, openLedger }: Props) {
  const reads = attributedReads(request, events, observations);
  const approved = events.some(e => e.request_id === request.id && e.type === 'variation.activated');
  const steps = [
    { title: 'Saved intent', detail: 'Durable request record', done: true },
    { title: 'Bounded proposal', detail: proposal ? `${proposal.route} · ${proposal.contract_version ? `contract v${proposal.contract_version}` : 'outside access contract'}` : 'No accepted proposal', done: !!proposal },
    { title: 'Host preview', detail: preview ? `${preview.counterfactual.checks} comparisons · ${preview.counterfactual.unexpected_delta_count} unexpected` : 'Not run in this view', done: !!preview?.matches_saved_proposal },
    { title: 'Admin approval', detail: approved ? 'Saved activation event' : request.kind === 'feature' ? 'Engineering route instead' : 'No activation event', done: approved },
    { title: 'Host observation', detail: `${reads} attributed granted read${reads === 1 ? '' : 's'} in loaded history`, done: reads > 0 },
  ];
  return <section className="boundary-inspector" aria-label="Selected request boundary inspector">
    <div className="inspector-heading"><span><ShieldCheck size={16}/> BOUNDARY INSPECTOR</span><button className="text-button" onClick={openLedger}>Inspect ledger <ArrowUpRight size={14}/></button></div>
    <ol className="boundary-steps">{steps.map((step, i) => <li key={step.title} className={step.done ? 'evidenced' : ''}>
      <span className="boundary-node" aria-hidden="true">{step.done ? <Check size={13}/> : <Circle size={11}/>}</span>
      <div><small>0{i + 1}</small><strong>{step.title}</strong><p>{step.detail}</p></div>
    </li>)}</ol>
    <p className="tiny"><LockKeyhole size={12}/> Evidence presence, not permission. Preview is session-local; observation history is limited to the latest 500 tenant checks. Only the host decides each read.</p>
  </section>;
}
