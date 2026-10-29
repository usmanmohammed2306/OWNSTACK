import { Clock3, FileText, LockKeyhole, UserRound } from 'lucide-react';
import { personName, projectName } from './changePresentation';

/** Exact saved scope, not a permission token or an observed access result. */
export function ChangeScope({ project, viewer, expiry }: { project: string | null; viewer: string | null; expiry: string | null }) {
  return <div className="scope-card" aria-label="Requested access scope">
    <div className="scope-path">
      <div className="scope-person"><span className="scope-symbol"><UserRound size={23}/></span><span><small>Person</small><strong>{personName(viewer)}</strong></span></div>
      <div className="scope-connection" aria-hidden="true"><span/><LockKeyhole size={15}/><span/></div>
      <div className="scope-project"><span className="scope-symbol"><FileText size={23}/></span><span><small>Project</small><strong>{projectName(project)}</strong></span></div>
    </div>
    <div className="scope-terms"><span><LockKeyhole size={14}/>Read only</span><span><Clock3 size={14}/>{expiry ? `Ends ${new Date(expiry).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}` : 'End time required'}</span></div>
  </div>;
}
