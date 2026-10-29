import { useEffect, useRef } from 'react';
import { Download, RotateCcw, Upload, X, ArrowDown, ArrowLeft, ArrowRight, ArrowUp } from 'lucide-react';
import { worldStations, type SpatialDestination } from './spatialWorkspaceModel';
import { parseLayout, moveStation, type WorkspaceLayout, type Palette } from './workspaceLayout';

/** Every control edits presentation only. Keyboard controls mirror physical dragging. */
export function SceneWorkshop({ layout, change, reset, close, allowed, notice }: {
  layout: WorkspaceLayout; change: (value: WorkspaceLayout) => void; reset: () => void; close: () => void;
  allowed: SpatialDestination[]; notice: (text: string) => void;
}) {
  const file = useRef<HTMLInputElement>(null);
  const heading=useRef<HTMLHeadingElement>(null);
  useEffect(()=>{heading.current?.focus();},[]);
  return <section className="scene-workshop" aria-label="Customize workspace" onKeyDown={event=>{if(event.key==='Escape'){event.stopPropagation();close();}}}>
    <header><h2 ref={heading} tabIndex={-1}>Your space</h2><button aria-label="Close customization" onClick={close}><X size={18}/></button></header>
    <div className="scene-swatches" aria-label="Color palette">{(['ice','violet','mint'] as Palette[]).map(p => <button key={p} className={`swatch-${p}`} title={p} aria-label={`${p} palette`} aria-pressed={layout.palette===p} onClick={() => change({...layout,palette:p})}/>)}</div>
    <label>Object size<input type="range" min="0.7" max="1.4" step="0.05" value={layout.scale} onChange={e=>change({...layout,scale:Number(e.target.value)})}/></label>
    <label>Light<input type="range" min="0.6" max="1.5" step="0.05" value={layout.light} onChange={e=>change({...layout,light:Number(e.target.value)})}/></label>
    <label className="scene-check"><input type="checkbox" checked={layout.snap} onChange={e=>change({...layout,snap:e.target.checked})}/>Snap to grid</label>
    <details><summary>Position with keyboard</summary>{worldStations.filter(s=>allowed.includes(s.id)).map(s=><div className="scene-nudge" key={s.id}><span>{s.label}</span>{[
      [-.25,0,ArrowLeft,'left'],[.25,0,ArrowRight,'right'],[0,-.25,ArrowUp,'back'],[0,.25,ArrowDown,'front'],
    ].map(([x,z,Icon,label])=>{const Glyph=Icon as typeof ArrowLeft;return <button key={String(label)} aria-label={`Move ${s.label} ${label}`} onClick={()=>change(moveStation(layout,s.id,layout.positions[s.id][0]+Number(x),layout.positions[s.id][1]+Number(z)))}><Glyph size={13}/></button>;})}</div>)}</details>
    <footer><button aria-label="Reset scene" title="Reset" onClick={reset}><RotateCcw size={16}/></button>
      <button aria-label="Export layout" title="Export layout" onClick={()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(layout,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='ownstack-layout.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}}><Download size={16}/></button>
      <button aria-label="Import layout" title="Import layout" onClick={()=>file.current?.click()}><Upload size={16}/></button>
      <input ref={file} type="file" accept="application/json,.json" hidden onChange={async e=>{const f=e.target.files?.[0];e.target.value='';if(!f)return;if(f.size>4096){notice('Layout file is too large.');return;}try{const parsed=parseLayout(JSON.parse(await f.text()));if(!parsed)throw Error();change(parsed);}catch{notice('Use a valid OwnStack layout file.');}}}/>
    </footer><small>Drag objects to arrange. Saved on this device.</small>
  </section>;
}
