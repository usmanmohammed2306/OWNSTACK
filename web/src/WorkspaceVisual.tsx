import { useId } from 'react';
import { Check, FileText, Layers3, LockKeyhole, ShieldCheck } from 'lucide-react';
import { requestSteps } from './workflowPresentation';

/** Product illustration only. Receives no runtime permission or approval data. */
export function WorkspaceVisual({ tenant = 'atlas' }: { tenant?: string }) {
  const id = useId().replaceAll(':', '');
  const current = tenant === 'nova' ? 'Nova' : 'Atlas';
  return <div className="stack-visual" aria-label="Illustration: one shared application, with separate customer workspaces">
    <svg viewBox="0 0 440 240" role="img" aria-labelledby={`${id}-title`}>
      <title id={`${id}-title`}>One shared app with separate Atlas and Nova workspaces. Illustration only, not current access.</title>
      <defs>
        <linearGradient id={`${id}-base`} x2="0.8" y2="1"><stop stopColor="#eee9e1"/><stop offset="1" stopColor="#d7d0c5"/></linearGradient>
        <linearGradient id={`${id}-card`} x2="0" y2="1"><stop stopColor="#fffdf9"/><stop offset="1" stopColor="#f0e9df"/></linearGradient>
        <linearGradient id={`${id}-accent`} x2="1" y2="1"><stop stopColor="#ea9e7a"/><stop offset="1" stopColor="#b95738"/></linearGradient>
        <filter id={`${id}-shadow`} x="-40%" y="-50%" width="180%" height="220%"><feDropShadow dx="0" dy="10" stdDeviation="9" floodColor="#4c3724" floodOpacity=".12"/></filter>
      </defs>
      <ellipse cx="220" cy="201" rx="150" ry="20" fill="#bcb09e" opacity=".12"/>
      <g filter={`url(#${id}-shadow)`}>
        <path d="M70 137 214 60 374 144 230 223Z" fill={`url(#${id}-base)`} stroke="#fcfaf7"/>
        <path d="m70 137 160 86v9L70 147Z" fill="#d7d0c5"/><path d="m230 223 144-79v10l-144 78Z" fill="#c6bbae"/>
        <path d="m103 126 111-59 125 66-111 62Z" fill="#f4f0e9" stroke="#fffdf9"/>
        <path d="m103 126 125 69v12l-125-69Z" fill="#e4ddd3"/><path d="m228 195 111-62v12l-111 62Z" fill="#d4c8ba"/>
      </g>
      <g className="visual-workspace" filter={`url(#${id}-shadow)`}>
        <rect x="102" y="30" width="107" height="100" rx="13" fill={`url(#${id}-card)`} stroke={current === 'Atlas' ? '#d5a487' : '#d8d0c5'}/>
        <rect x="244" y="53" width="107" height="100" rx="13" fill={`url(#${id}-card)`} stroke={current === 'Nova' ? '#d5a487' : '#d8d0c5'}/>
        <rect x="117" y="45" width="29" height="29" rx="9" fill={current === 'Atlas' ? `url(#${id}-accent)` : '#d8d2c7'}/>
        <rect x="259" y="68" width="29" height="29" rx="9" fill={current === 'Nova' ? `url(#${id}-accent)` : '#d8d2c7'}/>
        <path d="m125 65 7-13 7 13m-11-4h8" stroke="#fffdf9" strokeWidth="1.5" fill="none" strokeLinecap="round"/>
        <path d="M267 88V76l12 12V76" stroke="#fffdf9" strokeWidth="1.5" fill="none" strokeLinecap="round"/>
        <text x="117" y="96" fill="#4a433b" fontSize="12" fontFamily="system-ui" fontWeight="600">Atlas</text>
        <text x="259" y="119" fill="#4a433b" fontSize="12" fontFamily="system-ui" fontWeight="600">Nova</text>
        <path d="M117 111h59M259 134h59" stroke="#ded6cb" strokeWidth="3" strokeLinecap="round"/>
      </g>
      <path d="m155 145 72 39 71-39" fill="none" stroke="#be967c" strokeWidth="1.5" strokeDasharray="3 5"/>
      <circle cx="227" cy="184" r="7" fill="#b65b3d" stroke="#fffaf4" strokeWidth="3"/>
    </svg>
    <div className="visual-caption"><Layers3 size={14}/><span>One app. Separate customer spaces.</span></div>
  </div>;
}

export function RequestSteps({ status, hasProposal, previewMatches, feature }: {
  status: string; hasProposal: boolean; previewMatches: boolean; feature: boolean;
}) {
  const steps = feature ? [{ label: 'Saved', done: true }, { label: 'Routed to code review', done: status === 'engineering' }]
    : requestSteps(status, hasProposal, previewMatches);
  const icons = [FileText, Layers3, ShieldCheck, LockKeyhole];
  const next = steps.findIndex(step => !step.done);
  return <ol className="request-steps" aria-label="Request progress">{steps.map((step, i) => {
    const Icon = icons[i];
    return <li key={step.label} className={step.done ? 'step-done' : i === next ? 'step-next' : ''} aria-current={i === next ? 'step' : undefined}>
      <span className="step-icon">{step.done ? <Check size={15}/> : <Icon size={15}/>}</span><span>{step.label}</span>
      <span className="sr-only">{step.done ? ' complete' : i === next ? ' next' : ' pending'}</span>
    </li>;
  })}</ol>;
}
