import { useEffect, useRef, useState } from 'react';
import { Box, ChevronLeft, ChevronRight, Pause, Play, X } from 'lucide-react';
import { WorkspaceVisual } from './WorkspaceVisual';
import { scenarioContent, type Scenario } from './variationModel';
import type { WorkspaceRenderer, SpatialView } from './WorkspaceRenderer';

/** Optional product example. Opening or interacting never calls the application API. */
export function SpatialOverview() {
  const dialog = useRef<HTMLDialogElement>(null), surface = useRef<HTMLDivElement>(null);
  const renderer = useRef<WorkspaceRenderer | null>(null);
  const [open, setOpen] = useState(false), [scenario, setScenario] = useState<Scenario>('access');
  const [stage, setStage] = useState(0), [paused, setPaused] = useState(false), [simple, setSimple] = useState(false);
  const [status, setStatus] = useState<'loading' | 'ready' | 'unavailable'>('loading');
  const [reduced, setReduced] = useState(() => matchMedia('(prefers-reduced-motion: reduce)').matches);
  const [visible, setVisible] = useState(!document.hidden);
  const latest = useRef<SpatialView>({ scenario, stage, motion: !paused && !reduced, visible });
  latest.current = { scenario, stage, motion: !paused && !reduced, visible };
  useEffect(() => {
    const preference = matchMedia('(prefers-reduced-motion: reduce)');
    const changed = () => setReduced(preference.matches), visibility = () => setVisible(!document.hidden);
    preference.addEventListener('change', changed); document.addEventListener('visibilitychange', visibility);
    return () => { preference.removeEventListener('change', changed); document.removeEventListener('visibilitychange', visibility); };
  }, []);
  useEffect(() => {
    if (!open || simple) return;
    let cancelled = false;
    let instance: WorkspaceRenderer | undefined;
    setStatus('loading');
    const deadline = setTimeout(() => { if (!cancelled && !instance) { cancelled = true; setStatus('unavailable'); } }, 12_000);
    void import('./WorkspaceRenderer').then(async ({ createWorkspaceRenderer }) => {
      if (cancelled || !surface.current) return;
      instance = await createWorkspaceRenderer(surface.current, latest.current, () => { if (!cancelled) setStatus('unavailable'); });
      if (cancelled) { instance.dispose(); return; }
      renderer.current = instance; instance.update(latest.current); setStatus('ready'); clearTimeout(deadline);
    }).catch(() => { if (!cancelled) setStatus('unavailable'); });
    return () => { cancelled = true; clearTimeout(deadline); instance?.dispose(); if (renderer.current === instance) renderer.current = null; };
  }, [open, simple]);
  useEffect(() => { renderer.current?.update(latest.current); }, [scenario, stage, paused, reduced, visible]);
  const content = scenarioContent[scenario], chapter = content.stages[stage];
  return <><button className="explore-spatial" onClick={() => { setOpen(true); dialog.current?.showModal(); }}><Box size={13}/>Explore in 3D</button>
    <dialog className="spatial-dialog" ref={dialog} aria-labelledby="spatial-title" onClose={() => setOpen(false)}>
      <div className="dialog-heading"><div><h2 id="spatial-title">One app. Room to adapt.</h2><p className="tiny">Interactive example. Does not change your workspace.</p></div><button className="icon-button" aria-label="Close 3D example" onClick={() => dialog.current?.close()}><X size={20}/></button></div>
      <div className="spatial-scenarios" role="group" aria-label="Explore an example"><button aria-pressed={scenario === 'access'} onClick={() => { setScenario('access'); setStage(0); }}>Temporary access</button><button aria-pressed={scenario === 'pdf'} onClick={() => { setScenario('pdf'); setStage(0); }}>PDF export</button></div>
      <div className="spatial-surface" data-state={simple ? 'simple' : status}><div ref={surface} aria-hidden="true"/>{(simple || status !== 'ready') && <div className="spatial-fallback"><WorkspaceVisual/><span>{status === 'loading' && !simple ? 'Loading interactive view…' : 'Diagram view'}</span></div>}</div>
      <div className="spatial-controls"><span>Illustration only</span><div><button disabled={simple || status !== 'ready'} aria-label="Rotate model left" onClick={() => renderer.current?.rotate(-1)}><ChevronLeft size={16}/></button><button disabled={simple || status !== 'ready'} aria-label="Rotate model right" onClick={() => renderer.current?.rotate(1)}><ChevronRight size={16}/></button><button aria-label={paused || reduced ? 'Resume model motion' : 'Pause model motion'} aria-pressed={paused || reduced} disabled={reduced || simple} onClick={() => setPaused(value => !value)}>{paused || reduced ? <Play size={14}/> : <Pause size={14}/>}</button><button onClick={() => setSimple(value => !value)}>{simple ? '3D view' : 'Diagram'}</button></div></div>
      <div className="spatial-steps" role="group" aria-label="Example stages">{content.stages.map((entry,index)=><button key={entry.name} aria-pressed={stage === index} onClick={() => setStage(index)}>{entry.name}</button>)}</div>
      <div className="spatial-explanation" aria-live="polite"><h3>{chapter.title}</h3><p>{chapter.description}</p><div><span>Atlas: {chapter.atlasLabel}</span><span>Nova: {chapter.novaLabel}</span></div></div>
    </dialog>
  </>;
}
