import { useState } from 'react';
import { ArrowRight, ArrowUpRight, Code2, Layers3, Plus, ShieldCheck } from 'lucide-react';
import { ScopeScene } from './ScopeScene';
import { DemoEvidence } from './DemoEvidence';

type Destination = 'demo' | 'journey' | 'engineering' | 'convergence' | 'ledger';
type SavedRequest = { id: string; text: string; status: string };

export function WorkspaceHome({ tenant, role, mode, requests, activeCount, engineeringCount, loaded, navigate, newRequest, selectRequest }: {
  tenant: string; role: string; mode: string; requests: SavedRequest[]; activeCount: number;
  engineeringCount: number; loaded: boolean; navigate: (tab: Destination) => void;
  newRequest: () => void; selectRequest: (id: string) => void;
}) {
  const [showProof, setShowProof] = useState(false);
  const canRequest = role === 'admin' || role === 'engineer';
  const pending = requests.filter(request => ['new', 'ready', 'awaiting_approval', 'failed', 'refused'].includes(request.status)).length;
  const next = role === 'contractor'
    ? { title: 'Open your project.', copy: 'Read the documents available to your identity. The host checks your access on every request.', action: 'Open project', tab: 'journey' as const }
    : role === 'product_owner'
      ? { title: 'Find the shared need.', copy: 'Review aggregate customer signals. Keep a variation separate, retire it or record a product decision.', action: 'Review product signals', tab: 'convergence' as const }
      : { title: mode === 'off' ? 'AI is paused. You can still build.' : 'Start with one customer need.', copy: mode === 'off' ? (role === 'engineer' ? 'Prepare a saved request manually. An admin reviews the exact host preview before approval.' : 'Save the request, then ask an engineer to prepare it. Return here to preview and approve the exact change.') : 'Describe the outcome. Review the bounded proposal and its host preview before making a decision.', action: 'Go to requests', tab: 'journey' as const };

  return <div className="workspace-home">
    <section className="workspace-hero" aria-label="Workspace overview">
      <div className="workspace-intro">
        <div className="intro-message"><p className="eyebrow"><span className="intro-line" /> CUSTOMER CHANGE CONTROL</p>
        <h2>One app.<em> Precisely adapted.</em></h2>
        <p className="intro-copy">Give one customer what they need. Keep the core yours.</p></div>
        <div className="intro-task">
        <div className="hero-actions">
          {canRequest ? <><button className="primary" onClick={newRequest}><Plus size={17}/> New request</button><button className="text-button" onClick={() => navigate('journey')}>Review requests <ArrowRight size={16}/></button></> : <button className="primary" onClick={() => navigate(next.tab)}>{next.action} <ArrowRight size={16}/></button>}
        </div>
        <div className="intro-note"><ShieldCheck size={15}/><span>{tenant === 'platform' ? 'Platform view' : `${tenant[0].toUpperCase()}${tenant.slice(1)} workspace`} <span aria-hidden="true">/</span> Synthetic reference app</span></div>
        </div>
      </div>
      <ScopeScene />
    </section>
    {canRequest && <div className="workspace-summary" aria-label="Loaded tenant state">
          <button onClick={() => navigate('journey')}><strong>{loaded ? pending : '…'}</strong><span>Need review <ArrowUpRight size={13}/></span></button>
          <button onClick={() => navigate('journey')}><strong>{loaded ? activeCount : '…'}</strong><span>Active grants <ArrowUpRight size={13}/></span></button>
          <button onClick={() => navigate('engineering')}><strong>{loaded ? engineeringCount : '…'}</strong><span>Code work items <ArrowUpRight size={13}/></span></button>
        </div>}
    <div className="home-lower">
      <section className="panel next-step"><div className="panel-heading"><p className="eyebrow">YOUR NEXT STEP</p><Code2 size={19}/></div><h3>{next.title}</h3><p className="muted">{next.copy}</p><button className="text-button" onClick={() => navigate(next.tab)}>{next.action} <ArrowRight size={16}/></button></section>
      <section className="panel recent-requests"><div className="panel-heading"><h3>{canRequest ? 'Recent requests' : 'A change with a boundary'}</h3><Layers3 size={18}/></div>
        {canRequest ? requests.length ? requests.slice(0, 3).map(request => <button className="recent-row" key={request.id} onClick={() => selectRequest(request.id)}><span><strong>{request.text}</strong><small>{request.status.replaceAll('_', ' ')}</small></span><ArrowUpRight size={17}/></button>) : <p className="muted">{loaded ? 'Your first request starts here. Try temporary project access or a PDF export feature.' : 'Loading saved requests…'}</p> : <p className="muted">A contract sets the scope. A person approves the exact proposal. The host enforces the decision. Explore the example above to see how they fit.</p>}
      </section>
    </div>
    <details className="proof-disclosure" onToggle={event => setShowProof(event.currentTarget.open)}><summary><span><ShieldCheck size={17}/> Explore recorded demo evidence</span><span className="tiny">Historical runs, checks and limitations</span></summary>{showProof && <DemoEvidence mode={mode} role={role} navigate={navigate}/>}</details>
  </div>;
}
