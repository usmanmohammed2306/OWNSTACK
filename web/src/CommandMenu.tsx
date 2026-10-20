import { useEffect, useRef, useState } from 'react';
import { ArrowUpRight, Search, X } from 'lucide-react';

type Item = { id: string; label: string; description: string; run: () => void };
export function CommandMenu({ items }: { items: Item[] }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState('');
  const open = () => { dialog.current?.showModal(); input.current?.focus(); };
  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        if (dialog.current?.open) dialog.current.close(); else open();
      }
    };
    window.addEventListener('keydown', keydown);
    return () => window.removeEventListener('keydown', keydown);
  }, []);
  const matches = items.filter(item => `${item.label} ${item.description}`.toLowerCase().includes(query.toLowerCase())).slice(0, 10);
  return <><button className="command-trigger" aria-label="Quick navigation" onClick={open}><Search size={15} aria-hidden="true"/><span>Jump to…</span><kbd>⌘ / Ctrl K</kbd></button>
    <dialog className="command-dialog" ref={dialog} aria-labelledby="command-title" onClose={() => setQuery('')}>
      <div className="command-heading"><h2 id="command-title">Jump to a view or request</h2><button className="icon-button" aria-label="Close quick navigation" onClick={() => dialog.current?.close()}><X size={18}/></button></div>
      <label className="command-search">Search this workspace<input ref={input} value={query} onChange={e => setQuery(e.target.value)} placeholder="Try requests, code review or an ID"/></label>
      <div className="command-results">{matches.map(item => <button key={item.id} onClick={() => { dialog.current?.close(); item.run(); }}><span><strong>{item.label}</strong><small>{item.description}</small></span><ArrowUpRight size={16}/></button>)}{!matches.length && <p className="empty">Nothing matches. Try a view name or another request.</p>}</div>
      <p className="tiny">Tab to a result, Enter to open, Esc to close. No inference or mutations.</p>
    </dialog></>;
}
