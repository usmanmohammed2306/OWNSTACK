import { useEffect, useState } from 'react';
import { ArrowRight, Code2, RotateCcw, ShieldCheck } from 'lucide-react';

type Demo = {
  historical: boolean; notice: string; observed_at: string;
  access: { model_id: string; latency_ms: number; state: string; outcome: string; nova: string; preview_checks: number; preview_unexpected: number; saved_status: string };
  patch: { model_id: string; patch_hash: string; passed: boolean; stderr: string; release_state: string };
  recovery: { author: string; patch_hash: string; passed: boolean; stderr: string; ai_call: boolean; not_live_model_success: boolean };
  comparison: { models: { model_id: string; correct: number; total: number; mean_latency_ms: number; estimated_usd: number }[]; baseline: { name: string; correct: number; total: number }; limitation: string };
  artifacts: { path: string; sha256: string }[];
};

export function DemoEvidence({ mode, role, navigate }: { mode: string; role: string; navigate: (tab: 'journey' | 'engineering' | 'convergence') => void }) {
  const [data, setData] = useState<Demo | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    fetch('/v1/demo-evidence', { credentials: 'same-origin', signal: controller.signal })
      .then(async response => { if (!response.ok) throw new Error(`Evidence unavailable (${response.status}). Inspect docs/evidence in the source build.`); return response.json() as Promise<Demo>; })
      .then(saved => { if (!controller.signal.aborted) setData(saved); })
      .catch(err => { if (!controller.signal.aborted) setError(String(err)); });
    return () => controller.abort();
  }, []);
  if (error) return <p className="alert error" role="alert">{error}</p>;
  if (!data) return <p role="status">Loading saved evidence. No inference is started.</p>;
  const recordedDate = new Date(data.observed_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' });
  const runtime = mode === 'off' ? 'AI paused' : mode === 'nebius' ? 'Nebius enabled' : 'Synthetic model';
  return <div className="content-grid recorded-proof">
    <section className="panel span-three recorded-proof-heading">
      <div className="panel-heading"><div><p className="eyebrow">RECORDED DEMO</p><h2>A real run. Every result kept.</h2></div>
        <div className="button-row"><span className="pill neutral"><time dateTime={data.observed_at}>{recordedDate}</time></span><span className="pill neutral">Now: {runtime}</span></div>
      </div>
      <p className="muted">Saved Nemotron runs on synthetic Atlas and Nova data. Opening this panel uses no inference credits.</p>
    </section>
    <section className="panel recorded-proof-card">
      <div className="panel-heading"><ShieldCheck size={21} aria-hidden="true"/><span className="pill good">Access observed</span></div>
      <h3>Atlas only. Until revoked.</h3>
      <p>Real Nebius inference, exact admin approval, then an allowed Atlas read. Nova was denied. Revocation denied the next read.</p>
      <p className="recorded-proof-metric">{data.access.latency_ms.toLocaleString()} ms <span className="muted">for one accepted interpretation</span></p>
      <details><summary>Inspect access evidence</summary>
        <p className="tiny">Model: {data.access.model_id}. Saved final request state: {data.access.saved_status}.</p>
        <p className="tiny">The preview made {data.access.preview_checks} finite policy comparisons with {data.access.preview_unexpected} unexpected effects. Preview predicts an effect; actual host reads provide the observations above.</p>
        <p className="tiny">A separate eight-second manual grant demonstrated expiry. These are synthetic fixtures, not customer outcomes.</p>
      </details>
    </section>
    <section className="panel recorded-proof-card">
      <div className="panel-heading"><Code2 size={21} aria-hidden="true"/><span className={'pill ' + (data.patch.passed ? 'good' : 'bad')}>Model checks {data.patch.passed ? 'passed' : 'failed'}</span></div>
      <h3>The invalid patch stopped here.</h3>
      <p>Nemotron Super proposed a PDF export patch. Independent checks rejected its syntax. No code was released.</p>
      <details><summary>Inspect the original model failure</summary>
        <p className="tiny">Model: {data.patch.model_id}. Release state: {data.patch.release_state}.</p>
        <div className="hash-line"><span>ORIGINAL MODEL PATCH</span><code>{data.patch.patch_hash}</code></div>
        <pre className="demo-log">{data.patch.stderr}</pre>
      </details>
    </section>
    <section className="panel recorded-proof-card">
      <div className="panel-heading"><RotateCcw size={21} aria-hidden="true"/><span className={'pill ' + (data.recovery.passed ? 'good' : 'bad')}>Manual checks {data.recovery.passed ? 'passed' : 'failed'}</span></div>
      <h3>A separate correction. Same history.</h3>
      <p>A coding-assistant-authored correction passed four fixture checks through the manual path. The failed model patch remains saved.</p>
      <details><summary>Inspect the manual recovery</summary>
        <p className="tiny">Recorded author: {data.recovery.author}. Correction used an inference call: {data.recovery.ai_call ? 'yes' : 'no'}. This is agent-assisted manual recovery, not a successful model-only patch or independent user-authored work.</p>
        <div className="hash-line"><span>MANUAL CORRECTION / DISTINCT PATCH</span><code>{data.recovery.patch_hash}</code></div>
        <pre className="demo-log">{data.recovery.stderr}</pre>
        <p className="tiny">Checks cover this fixture. Human acceptance is not deployment; the experimental verifier is not a certified sandbox.</p>
      </details>
    </section>
    <section className="panel span-three recorded-proof-details">
      <details><summary>Model comparison: two cases each</summary>
        <div className="recorded-models">{data.comparison.models.map(model => <div className="model-measurement" key={model.model_id}>
          <div><h3>{model.model_id.toLowerCase().includes('nano') ? 'Nemotron Nano' : 'Nemotron Super'}</h3><span className="pill neutral">{model.correct}/{model.total} correct routes</span></div>
          <p>{model.mean_latency_ms.toLocaleString()} ms mean · ${model.estimated_usd.toFixed(8)} estimated returned-usage cost</p>
          <p className="tiny">{model.model_id}</p>
        </div>)}</div>
        <p className="muted">Kind-only baseline: {data.comparison.baseline.correct}/{data.comparison.baseline.total}. {data.comparison.limitation}</p>
        <p className="tiny">Three failed Nano drafts and one failed Super patch are retained separately. Returned token estimates do not reconcile provider billing.</p>
      </details>
      <details><summary>Sources, exact hashes and limits</summary>
        <p className="muted">{data.notice}</p>
        {data.artifacts.map(artifact => <div className="hash-line" key={artifact.path}><span>{artifact.path}</span><code>{artifact.sha256}</code></div>)}
        <p className="tiny">Local synthetic results, not a production deployment or customer study. Production identity, stronger isolation and independent validation remain open.</p>
      </details>
      <div className="button-row"><button className="secondary" onClick={() => navigate(role === 'product_owner' ? 'convergence' : 'journey')}>{role === 'contractor' ? 'Check your current access' : role === 'product_owner' ? 'Open product decisions' : 'Open current requests'} <ArrowRight size={15} aria-hidden="true"/></button></div>
    </section>
  </div>;
}
