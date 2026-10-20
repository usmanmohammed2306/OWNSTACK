import { useMemo, useState } from 'react';
import { lineDiff } from './review';

export function PatchDiff({ path, before, after }: { path: string; before: string; after: string }) {
  const [view, setView] = useState<'diff' | 'source'>('diff');
  const lines = useMemo(() => lineDiff(before, after), [before, after]);
  const additions = lines.filter(line => line.kind === 'add').length;
  const removals = lines.filter(line => line.kind === 'remove').length;
  return <section className="diff" aria-label="Exact candidate source review">
    <div className="diff-head"><span>{path}</span><span className="diff-stats"><b>+{additions}</b><b>-{removals}</b></span></div>
    <div className="diff-toolbar"><span>Host-owned file · proposed, not released</span><div className="switch"><button aria-pressed={view === 'diff'} className={view === 'diff' ? 'chosen' : ''} onClick={() => setView('diff')}>Line diff</button><button aria-pressed={view === 'source'} className={view === 'source' ? 'chosen' : ''} onClick={() => setView('source')}>Complete source</button></div></div>
    {view === 'source' ? <pre tabIndex={0} aria-label="Complete candidate source">{after}</pre> : <div className="diff-lines" tabIndex={0} role="region" aria-label="Scrollable line-by-line diff">
      {lines.map((line, index) => <div className={`diff-line ${line.kind}`} key={index}><span className="line-number" aria-hidden="true">{line.oldLine}</span><span className="line-number" aria-hidden="true">{line.newLine}</span><span className="diff-sign">{line.kind === 'add' ? '+' : line.kind === 'remove' ? '-' : ' '}</span><code>{line.text || ' '}</code></div>)}
    </div>}
    <p className="tiny diff-note">Line counts describe this display only. Checks and human decisions bind to the exact server-side patch hash.</p>
  </section>;
}
