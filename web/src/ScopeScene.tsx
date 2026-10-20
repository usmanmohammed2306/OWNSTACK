import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import { ArrowRight, Box, Braces, Eye, Focus, LockKeyhole, Pause, Play, RotateCcw, ShieldCheck } from 'lucide-react';
import type { createCapabilityRenderer } from './CapabilityRenderer';
import { scenarioContent, variationFrame, type Scenario } from './variationModel';
import './scope-scene.css';

type Renderer = ReturnType<typeof createCapabilityRenderer>;

/** An explanatory example only. No requests, permissions or telemetry enter this model. */
export function ScopeScene({ compact = false }: { compact?: boolean }) {
  const id = useId();
  const [scenario, setScenario] = useState<Scenario>('access');
  const [stage, setStage] = useState(0);
  const [paused, setPaused] = useState(false);
  const [simple, setSimple] = useState(false);
  const [status, setStatus] = useState<'loading' | 'ready' | 'unavailable'>('loading');
  const [reducedMotion, setReducedMotion] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const [visible, setVisible] = useState(true);
  const [documentVisible, setDocumentVisible] = useState(!document.hidden);
  const viewport = useRef<HTMLDivElement>(null);
  const renderer = useRef<Renderer | null>(null);
  const stageButtons = useRef<(HTMLButtonElement | null)[]>([]);
  const options = { stage, scenario, motion: !paused && !reducedMotion, reducedMotion, visible: visible && documentVisible };
  const latest = useRef(options);
  latest.current = options;
  const content = scenarioContent[scenario];
  const chapter = content.stages[stage];
  const frame = variationFrame(scenario, stage);

  useEffect(() => {
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => setReducedMotion(preference.matches);
    preference.addEventListener('change', update);
    const updateVisibility = () => setDocumentVisible(!document.hidden);
    document.addEventListener('visibilitychange', updateVisibility);
    const observer = typeof IntersectionObserver === 'undefined' ? null : new IntersectionObserver(
      ([entry]) => setVisible(entry.isIntersecting), { threshold: 0.05 },
    );
    if (viewport.current) observer?.observe(viewport.current);
    return () => {
      preference.removeEventListener('change', update);
      document.removeEventListener('visibilitychange', updateVisibility);
      observer?.disconnect();
    };
  }, []);

  useEffect(() => {
    if (simple) return;
    let canceled = false;
    let instance: Renderer | null = null;
    let failed = false;
    setStatus('loading');
    const failure = () => {
      failed = true;
      if (!canceled) setStatus('unavailable');
      instance?.dispose();
      if (renderer.current === instance) renderer.current = null;
    };
    void import('./CapabilityRenderer').then(({ createCapabilityRenderer }) => {
      if (canceled || !viewport.current) return;
      instance = createCapabilityRenderer(viewport.current, { ...latest.current, onFailure: failure });
      if (failed) { instance.dispose(); return; }
      renderer.current = instance;
      setStatus('ready');
    }).catch(failure);
    return () => {
      canceled = true;
      instance?.dispose();
      if (renderer.current === instance) renderer.current = null;
    };
  }, [simple]);

  useEffect(() => { renderer.current?.update(options); }, [stage, scenario, paused, reducedMotion, visible, documentVisible]);

  function selectWithKeyboard(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const target = event.key === 'ArrowRight' ? (index + 1) % 4
      : event.key === 'ArrowLeft' ? (index + 3) % 4
        : event.key === 'Home' ? 0 : event.key === 'End' ? 3 : null;
    if (target === null) return;
    event.preventDefault();
    setStage(target);
    stageButtons.current[target]?.focus();
  }

  function chooseScenario(value: Scenario) {
    setScenario(value);
    setStage(0);
    renderer.current?.reset();
  }

  return <section className={`capability-scene${compact ? ' capability-scene--compact' : ''}`} data-scenario={scenario} data-stage={stage} data-route={frame.route} data-renderer={simple ? 'simple' : status} data-motion={options.motion && options.visible && !simple && status === 'ready' ? 'running' : 'paused'} aria-label="Explore a customer-specific change">
    <header className="variation-header">
      <div><span className="variation-kicker"><span aria-hidden="true"/> THE VARIATION MAP</span><p>One shared app. Two separate customers.</p></div>
      <span className="illustration-badge">ILLUSTRATIVE EXAMPLE · NOT LIVE</span>
    </header>
    <div className="variation-toolbar">
      <div className="scenario-switch" role="group" aria-label="Example request">
        <button type="button" aria-pressed={scenario === 'access'} onClick={() => chooseScenario('access')}><LockKeyhole size={14}/>Temporary access</button>
        <button type="button" aria-pressed={scenario === 'pdf'} onClick={() => chooseScenario('pdf')}><Braces size={14}/>PDF export</button>
      </div>
      <div className="variation-view-controls">
        <button type="button" className="view-mode" onClick={() => setSimple(value => !value)}>{simple ? 'Show 3D' : 'Simple view'}</button>
        <button type="button" disabled={simple || status !== 'ready'} aria-label="Reset map view" title="Reset map view" onClick={() => renderer.current?.reset()}><Focus size={15}/></button>
        <button type="button" disabled={simple || reducedMotion || status !== 'ready'} aria-pressed={paused || reducedMotion} aria-label={reducedMotion ? 'Motion disabled by your system preference' : paused ? 'Resume map motion' : 'Pause map motion'} title={reducedMotion ? 'Reduced motion enabled' : paused ? 'Resume motion' : 'Pause motion'} onClick={() => setPaused(value => !value)}>{paused || reducedMotion ? <Play size={14}/> : <Pause size={14}/>}</button>
      </div>
    </div>
    <div className="variation-stage">
      <div className="map-request"><span>{content.kicker}</span><strong>{content.title}</strong></div>
      <div ref={viewport} className="chamber-canvas" aria-hidden="true"/>
      {(simple || status !== 'ready') && <div className="variation-fallback" aria-hidden="true">
        <div className="fallback-core"><Box size={29}/><span>ONE SHARED APPLICATION</span></div>
        <div className="fallback-gate"><ShieldCheck size={16}/>{chapter.gateLabel}</div>
        <div className="fallback-customers"><div className="fallback-atlas"><strong>ATLAS</strong><small>{chapter.atlasLabel}</small></div><div className="fallback-nova"><strong>NOVA</strong><small>Unchanged</small></div></div>
        {scenario === 'pdf' && <div className="fallback-engineering"><Braces size={18}/>Engineer review. No deployment.</div>}
      </div>}
      <div className="map-caption"><span>{simple ? 'Low-power diagram' : status === 'loading' ? 'Preparing 3D map…' : status === 'unavailable' ? '3D unavailable. Diagram shown.' : 'Explore the example with the steps below'}</span><span>01 SHARED APP <i/> NO PER-CUSTOMER FORK</span></div>
    </div>
    <div className="variation-console">
      <div className="variation-steps" role="group" aria-label="Example journey steps">{content.stages.map(({ name }, index) => <button key={name} type="button" ref={node => { stageButtons.current[index] = node; }} aria-pressed={stage === index} aria-controls={`${id}-explanation`} onClick={() => setStage(index)} onKeyDown={event => selectWithKeyboard(event, index)}><span>0{index + 1}</span>{name}</button>)}</div>
      <div className="variation-detail">
        <div id={`${id}-explanation`} className="variation-explanation" aria-live="polite" aria-atomic="true"><span>EXAMPLE STEP 0{stage + 1} / 04</span><h3>{chapter.title}</h3><p>{chapter.description}</p></div>
        <div className="example-boundaries" aria-label="Illustrated effect, not live state">
          <div className="atlas-boundary"><span><i/>Atlas</span><strong>{chapter.atlasLabel}</strong></div>
          <div className="nova-boundary"><span><i/>Nova</span><strong>{chapter.novaLabel}</strong></div>
          <div className="gate-boundary"><span><ShieldCheck size={12}/>Human gate</span><strong>{chapter.gateLabel}</strong></div>
        </div>
      </div>
      <div className="variation-footer"><p><Eye size={13}/>This example changes no permissions and deploys no code.</p><button type="button" onClick={() => setStage(value => (value + 1) % 4)}>{stage === 3 ? 'Restart example' : 'Next step'}{stage === 3 ? <RotateCcw size={14}/> : <ArrowRight size={14}/>}</button></div>
    </div>
  </section>;
}
