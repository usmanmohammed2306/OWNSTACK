import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { ArrowLeft, ArrowUpRight, ChevronLeft, ChevronRight, Code2, KeyRound, Layers3, Network, Pause, Play, Workflow, SlidersHorizontal, Plus, Minus, X, RefreshCw, Search } from 'lucide-react';
import { SceneWorkshop } from './SceneWorkshop';
import { defaultLayout, layoutKey, moveStation, parseLayout, type WorkspaceLayout } from './workspaceLayout';
import { AgentCommand } from './AgentCommand';
import type { PlannerTransport } from './plannerState';
import { layoutForPlan, parseCommandPlan, type CommandPlan } from './commandPlan';
import { allowedStations, homeStations, stationLabel, scopedDestination, worldStations, type SpatialDestination } from './spatialWorkspaceModel';
import type { SpatialWorld, WorldView, WorldHover } from './SpatialWorldRenderer';
import { clampZoom, collectionRecords, collectionPage, searchRecords, safeRecord, stationDescriptions, stationRecords, type SpatialRecord } from './spatialRecords';
import {semanticZoom,type ZoomContext} from './semanticZoom';
import {placeLabels,tooltipPosition,type Rect} from './spatialLayout';

const icons = { demo: Layers3, journey: Workflow, access: KeyRound, engineering: Code2, convergence: Network };

/** The world is navigation. Only the host API can approve or apply a change. */
export function SpatialShell({ role, tenant, user = 'guest', workspaceName, focus, counts, navigate, children, planCommand, draftRequest, items=[], inspectItem, mapAsOf, mapTruncated,refreshMap,openTeams,requestAgentState='idle',homeReset=0 }: {
  role: string; tenant: string; user?: string; workspaceName?: string; focus: string;
  counts: Partial<Record<SpatialDestination, number | null>>;
  navigate: (id: SpatialDestination|'people') => void; children: ReactNode;
  planCommand?: PlannerTransport;
  draftRequest?: (kind:'access'|'feature',text:string)=>void;
  items?:SpatialRecord[];inspectItem?:(item:SpatialRecord)=>void;mapAsOf?:string;mapTruncated?:boolean;
  refreshMap?:()=>Promise<void>;
  openTeams?:()=>void;
  requestAgentState?:'idle'|'working'|'review'|'error';
  homeReset?:number;
}) {
  const host = useRef<HTMLDivElement>(null), world = useRef<SpatialWorld | null>(null);
  const contextPanel=useRef<HTMLElement|null>(null);
  const customizeButton=useRef<HTMLButtonElement|null>(null);
  const labels = useRef<Record<string, HTMLButtonElement | null>>({});
  const leaders=useRef<Record<string,SVGLineElement|null>>({});
  const labelSizes=useRef<Record<string,{width:number;height:number}>>({});
  const labelObserver=useRef<ResizeObserver|null>(null);
  const [stageBounds,setStageBounds]=useState<Rect>({x:0,y:0,width:window.innerWidth,height:window.innerHeight});
  function registerLabel(id:string,element:HTMLButtonElement|null){
    const previous=labels.current[id];if(previous)labelObserver.current?.unobserve(previous);
    labels.current[id]=element;
    if(element){element.dataset.anchor=id;labelObserver.current?.observe(element);}
  }
  useEffect(()=>{
    const observer=new ResizeObserver(entries=>{for(const entry of entries){const element=entry.target as HTMLButtonElement;
      const size=element.getBoundingClientRect();labelSizes.current[element.dataset.anchor!]={width:size.width,height:size.height};}});
    labelObserver.current=observer;Object.values(labels.current).forEach(element=>{if(element)observer.observe(element);});
    const stage=new ResizeObserver(()=>{const r=host.current?.getBoundingClientRect();if(r)setStageBounds({x:r.left,y:r.top,width:r.width,height:r.height});});
    if(host.current)stage.observe(host.current);
    return()=>{observer.disconnect();stage.disconnect();labelObserver.current=null;};
  },[]);
  const [status, setStatus] = useState<'loading' | 'ready' | 'unavailable'>('loading');
  const [paused, setPaused] = useState(false), [reduced, setReduced] = useState(false);
  const [agentState,setAgentState]=useState<'idle'|'working'|'review'|'error'>('idle');
  const [editing, setEditing] = useState(false), [message, setMessage] = useState('');
  function closeWorkshop(){setEditing(false);requestAnimationFrame(()=>customizeButton.current?.focus());}
  const storageKey = layoutKey(tenant, user);
  const [layout, setLayout] = useState<WorkspaceLayout>(() => { try { return parseLayout(JSON.parse(localStorage.getItem(storageKey) || 'null')) || defaultLayout(); } catch { return defaultLayout(); } });
  const [ghost, setGhost] = useState<WorkspaceLayout|null>(null), previewRevision = useRef<number|null>(null);
  const layoutRef = useRef(layout); layoutRef.current = layout;
  const save = (next: WorkspaceLayout) => {
    const value = parseLayout({...next, revision:layoutRef.current.revision+1}); if (!value) return false;
    try {
      const stored=parseLayout(JSON.parse(localStorage.getItem(storageKey)||'null'));
      if(stored&&stored.revision!==layoutRef.current.revision){layoutRef.current=stored;setLayout(stored);setMessage('Changed in another tab. Try your edit again.');return false;}
      localStorage.setItem(storageKey, JSON.stringify(value));layoutRef.current=value;setLayout(value);setMessage('Saved');
    } catch { layoutRef.current=value;setLayout(value);setMessage('Storage unavailable. Changes last for this session.'); }
    return true;
  };
  const saveRef = useRef(save); saveRef.current = save;
  useEffect(() => { const sync = (e: StorageEvent) => { if(e.key!==storageKey)return;try{const next=parseLayout(JSON.parse(e.newValue||'null'));if(next){layoutRef.current=next;setLayout(next);setMessage('Layout updated in another tab.');}}catch{/* Invalid external state is ignored. */} };window.addEventListener('storage',sync);return()=>window.removeEventListener('storage',sync); },[storageKey]);
  const [visible, setVisible] = useState(!document.hidden);
  const [exploring,setExploring]=useState<SpatialDestination|null>(null),[zoom,setZoom]=useState(1),[page,setPage]=useState(0),[parent,setParent]=useState<string|null>(null);
  const [query,setQuery]=useState('');
  const [hovered,setHovered]=useState<WorldHover|null>(null),[inspected,setInspected]=useState<SpatialRecord|null>(null);
  const zoomContext=useRef<ZoomContext>({zoom:1,station:null,parent:null});zoomContext.current={zoom,station:exploring,parent};
  const lastStation=useRef<SpatialDestination>('demo');
  const lastRecord=useRef<string|null>(null);
  const personHeading=useRef<HTMLHeadingElement>(null),[refreshing,setRefreshing]=useState(false);
  useEffect(()=>{if(inspected)personHeading.current?.focus();},[inspected?.id]);
  useEffect(()=>{
    const panel=contextPanel.current;if(!panel)return;
    const observer=new ResizeObserver(()=>panel.parentElement?.style.setProperty('--collection-top',`${panel.getBoundingClientRect().bottom+24}px`));
    observer.observe(panel);return()=>observer.disconnect();
  },[exploring,parent,focus,editing,inspected?.id]);
  const collection=useMemo(()=>collectionRecords(items,exploring,parent),[items,exploring,parent]);
  const matches=useMemo(()=>searchRecords(collection,query),[collection,query]);
  const currentPage=collectionPage(page,matches.length);
  const visibleItems=useMemo(()=>exploring?stationRecords(matches,exploring,currentPage):[],[matches,exploring,currentPage]);
  useEffect(()=>{setQuery('');setPage(0);},[exploring,parent]);
  useEffect(()=>{if(page!==currentPage)setPage(currentPage);},[page,currentPage]);
  const current = useRef({ role, navigate,items,inspectItem }); current.current = { role, navigate,items,inspectItem };
  useEffect(()=>{setExploring(null);setParent(null);setPage(0);setZoom(1);setInspected(null);setHovered(null);zoomContext.current={station:null,parent:null,zoom:1};},[homeReset]);
  function explore(id:SpatialDestination){if(role==='guest'||!scopedDestination(id,role))return;
    const visual=id==='access'?'demo':id==='convergence'&&role!=='product_owner'?'journey':id;
    lastStation.current=visual;lastRecord.current=null;zoomContext.current={station:visual,parent:null,zoom:1.9};setExploring(visual);setParent(null);setPage(0);setZoom(1.9);setInspected(null);setHovered(null);navigate(id==='demo'?'people':id);}
  function inspect(station:SpatialDestination,id:string){const item=safeRecord(current.current.items,station,id);if(!item||!scopedDestination(station,current.current.role))return;
    setHovered(null);if(['role','team'].includes(item.kind||'')){setParent(item.id);setPage(0);setZoom(2.15);}else if(item.kind==='person'){setInspected(item);}else current.current.inspectItem?.(item);
  }
  function changeZoom(amount:number,station?:SpatialDestination){
    if(focus!=='demo'){setZoom(value=>clampZoom(value+amount));setHovered(null);return;}
    // Signed-out visitors can zoom the illustration, never enter saved records.
    if(role==='guest'){setZoom(value=>clampZoom(value+amount));return;}
    const target=scopedDestination(station||hovered?.station||lastStation.current,role)||'demo';
    // Moving focus to a zoom button must not lose the object just inspected.
    // Only a still-visible record can remain an anchor across that focus move.
    const child=hovered?.id?safeRecord(items,hovered.station,hovered.id):visibleItems.find(i=>i.id===lastRecord.current)||null;
    const next=semanticZoom(zoomContext.current,amount,target,child&&['role','team'].includes(child.kind||'')?child.id:null);
    const changed=next.station!==zoomContext.current.station||next.parent!==zoomContext.current.parent;
    zoomContext.current=next;setZoom(next.zoom);
    if(changed){lastRecord.current=null;setExploring(next.station);setParent(next.parent);setPage(0);setInspected(null);setHovered(null);navigate('demo');}
    if(amount<0&&(focus!=='demo'||inspected)){setInspected(null);navigate('demo');}
    if(amount>0&&next.zoom>=2.4&&child&&!['role','team'].includes(child.kind||'')&&focus==='demo'){inspect(child.station,child.id);}
  }
  const actions=useRef({explore,inspect,changeZoom});actions.current={explore,inspect,changeZoom};
  const view = useRef<WorldView>({ focus, allowed: homeStations(role), motion: !paused && !reduced, visible, illustration: role === 'guest', editing, layout });
  view.current = { focus, allowed: homeStations(role), motion: !paused && !reduced, visible, illustration: role === 'guest', editing, layout:ghost||layout,zoom,exploring:editing?null:exploring,items:editing||focus!=='demo'?[]:visibleItems,connections:items,highlight:hovered?.id||hovered?.station,agentState:requestAgentState==='idle'?agentState:requestAgentState };

  useEffect(() => {
    const preference = matchMedia('(prefers-reduced-motion: reduce)');
    const motion = () => setReduced(preference.matches), visibility = () => setVisible(!document.hidden);
    motion(); preference.addEventListener('change', motion); document.addEventListener('visibilitychange', visibility);
    return () => { preference.removeEventListener('change', motion); document.removeEventListener('visibilitychange', visibility); };
  }, []);
  useEffect(() => {
    let canceled = false;
    const failure = () => { if (!canceled) { setStatus('unavailable'); world.current?.dispose(); world.current = null; } };
    const deadline = window.setTimeout(() => { failure(); canceled = true; }, 15000);
    import('./SpatialWorldRenderer').then(async ({ createSpatialWorld }) => {
      if (canceled || !host.current) return;
      const instance = await createSpatialWorld(host.current, view.current, id => {
        const target = scopedDestination(id, current.current.role);
        if (target) actions.current.explore(target);
      }, (positions,obstacles) => {
        const stage=host.current;if(!stage)return;
        const active=Object.entries(positions).filter(([id])=>view.current.exploring&&!view.current.editing?id.startsWith('record:'):!id.startsWith('record:'));
        const placements=placeLabels(active.filter(([id])=>labels.current[id]).map(([id,[x,y]])=>{
          const cached=labelSizes.current[id];const label=labels.current[id]!;
          const size=cached&&cached.width?cached:{width:label.offsetWidth,height:label.offsetHeight};
          return {id,x,y,...size};
        }),stage.clientWidth,stage.clientHeight,10,obstacles);
        for (const [id] of active) {
          const label = labels.current[id];
          if(label){const next=placements[id];label.style.visibility=next?'visible':'hidden';
            if(next){const transform=`translate(${next.x}px, ${next.y}px)`;if(label.style.transform!==transform)label.style.transform=transform;}}
          const leader=leaders.current[id];if(leader){const next=placements[id];leader.style.display=next?'':'none';
            if(next){const [x,y]=positions[id];leader.setAttribute('x1',String(x));leader.setAttribute('y1',String(y));
              leader.setAttribute('x2',String(next.x+next.width/2));leader.setAttribute('y2',String(next.y+next.height/2));}}
        }
      }, failure, (id,x,z) => { if(scopedDestination(id,current.current.role))saveRef.current(moveStation(layoutRef.current,id,x,z)); },
      {inspect:(station,id)=>actions.current.inspect(station,id),hover:setHovered,zoom:(amount,station)=>actions.current.changeZoom(amount,station)});
      if (canceled) { instance.dispose(); return; }
      window.clearTimeout(deadline); world.current = instance; instance.update(view.current); setStatus('ready');
    }).catch(() => { window.clearTimeout(deadline); failure(); });
    return () => { canceled = true; window.clearTimeout(deadline); world.current?.dispose(); world.current = null; };
  }, []);
  useEffect(() => { world.current?.update(view.current); }, [focus, role, paused, reduced, visible, editing, layout, ghost,zoom,exploring,visibleItems,items,hovered,agentState]);
  useEffect(()=>{if(exploring&&!scopedDestination(exploring,role)){setExploring(null);setInspected(null);setHovered(null);}},[role,exploring]);
  function previewCommand(plan:CommandPlan|null){previewRevision.current=plan?layoutRef.current.revision:null;setGhost(plan?layoutForPlan(layoutRef.current,plan):null);}
  function applyCommand(plan:CommandPlan,text:string){
    const valid=parseCommandPlan(plan,role);if(!valid||previewRevision.current!==layoutRef.current.revision)return false;
    if(valid.actions.some(a=>['move','theme','reset'].includes(a.action))&&!save(layoutForPlan(layoutRef.current,valid)))return false;
    for(const action of valid.actions){if(action.action==='navigate'){const id=scopedDestination(action.target,role);if(id)explore(id);}if(action.action==='draft')draftRequest?.(action.target,text);}
    return true;
  }

  const hoveredItem=hovered?.id?safeRecord(items,hovered.station,hovered.id):null;
  const selectedPerson=inspected?safeRecord(items,'demo',inspected.id):null;
  const title=hoveredItem?.title||(hovered?stationLabel(hovered.station):undefined);
  const collectionCount=parent?collection.length:collection.filter(i=>exploring==='demo'?['role','team'].includes(i.kind||''):i.kind!=='action').length;
  const collectionLabel=parent?(collectionCount===1?'person':'people'):exploring==='demo'?(collection.some(i=>i.kind==='team')?(collectionCount===1?'team':'teams'):(collectionCount===1?'role':'roles')):(collectionCount===1?'saved item':'saved items');
  const peek=hovered?tooltipPosition(hovered.x,hovered.y,stageBounds):null;
  return <div className={`spatial-shell arctic-shell studio-shell world-${status}`} data-role={role} data-inspecting={focus!=='demo'||!!inspected} data-focus={focus} data-level={parent?'people':exploring?'collection':'workspace'} data-exploring={exploring||''} data-zoom={zoom.toFixed(2)} data-editing={editing} data-palette={(ghost||layout).palette} data-layout-revision={layout.revision}>
    <div className="world-canvas" ref={host}/><div className="world-atmosphere" aria-hidden="true"/>
    {role !== 'guest' && <nav className="world-hotspots" aria-label="Spatial workspace navigation">
      <svg className="station-leaders" aria-hidden="true">{worldStations.filter(s=>homeStations(role).includes(s.id)).map(s=><line key={s.id} ref={element=>{leaders.current[s.id]=element;}}/>)}</svg>
      {worldStations.filter(station => homeStations(role).includes(station.id)).map(station => {
        const Icon = icons[station.id], count = counts[station.id];
        const name=stationLabel(station.id);
        return <button key={station.id} ref={element => registerLabel(station.id,element)}
          className={`world-hotspot station-${station.id}`} data-x={(ghost||layout).positions[station.id][0]} data-z={(ghost||layout).positions[station.id][1]} aria-current={focus === station.id ? 'page' : undefined}
          aria-disabled={editing} onPointerDown={event=>{if(!editing)event.currentTarget.setPointerCapture(event.pointerId);}}
          onClick={() => {if(!editing)explore(station.id);}} title={editing?`Arrange ${name} in the scene`:`Explore ${name}`}
          onMouseEnter={e=>{const r=e.currentTarget.getBoundingClientRect();setHovered({station:station.id,x:r.left+r.width/2,y:r.bottom});}} onMouseLeave={()=>setHovered(null)}
          onFocus={e=>{const r=e.currentTarget.getBoundingClientRect();setHovered({station:station.id,x:r.left+r.width/2,y:r.bottom});}} onBlur={()=>setHovered(null)}><span className="station-number" aria-hidden="true">{String(homeStations(role).indexOf(station.id)+1).padStart(2,'0')}</span><Icon size={14}/><span>{name}</span>
          {count != null && <small aria-label={`${count} ${station.id === 'access' ? 'active grants' : station.id === 'convergence' ? 'observed need categories' : station.id === 'engineering' ? 'work items' : 'requests'}`}>{count}</small>}</button>;
      })}
      {!editing&&focus==='demo'&&visibleItems.map(item=><button key={item.id} className="world-record-hit" ref={element=>registerLabel('record:'+item.id,element)}
        aria-label={`Inspect ${item.title}${item.by?', '+item.by:''}`} onPointerDown={event=>event.currentTarget.setPointerCapture(event.pointerId)} onClick={()=>inspect(item.station,item.id)}
        onMouseEnter={e=>{lastRecord.current=item.id;const r=e.currentTarget.getBoundingClientRect();setHovered({station:item.station,id:item.id,x:r.left+r.width/2,y:r.bottom});}} onMouseLeave={()=>setHovered(null)}
        onFocus={e=>{lastRecord.current=item.id;const r=e.currentTarget.getBoundingClientRect();setHovered({station:item.station,id:item.id,x:r.left+r.width/2,y:r.bottom});}} onBlur={()=>setHovered(null)}><ArrowUpRight size={13}/><span className="sr-only">{item.title}</span></button>)}
    </nav>}
    {status !== 'ready' && <div className="world-fallback" role="status"><Layers3 size={44}/>
      <p>{status === 'loading' ? 'Opening your workspace' : '3D is unavailable on this device'}</p>
      {status === 'unavailable' && <small>Your saved work is still accessible below.</small>}</div>}
    {role!=='guest'&&<div className="world-view-controls" aria-label="3D view controls">
      <span className="zoom-level-label" aria-live="polite">{parent?'People':exploring?exploring==='demo'?'Organization':worldStations.find(s=>s.id===exploring)?.label:'Workspace'}</span>
      {exploring&&focus==='demo'&&<button aria-label={parent?'Back to organization teams':'Back to workspace map'} onClick={()=>{if(parent){setParent(null);setPage(0);setInspected(null);setZoom(1.9);}else{setExploring(null);setZoom(1);setInspected(null);navigate('demo');}setHovered(null);}}><ArrowLeft size={16}/></button>}
      <button aria-label="Zoom out" title="Zoom out" disabled={zoom<=.65} onClick={()=>changeZoom(-.25)}><Minus size={16}/></button>
      <small aria-label={`Zoom ${Math.round(zoom*100)} percent`}>{Math.round(zoom*100)}%</small>
      <button aria-label="Zoom in" title="Zoom in" disabled={zoom>=3.2} onClick={()=>changeZoom(.25)}><Plus size={16}/></button>
      <button ref={customizeButton} aria-label="Customize workspace" aria-pressed={editing} title="Customize workspace" onClick={()=>{setEditing(!editing);setMessage('');if(!editing){setZoom(1);setExploring(null);setParent(null);setInspected(null);navigate('demo');}}}><SlidersHorizontal size={16}/></button>
      <button aria-label={paused ? 'Resume ambient motion' : 'Pause ambient motion'} aria-pressed={paused}
        disabled={status !== 'ready' || reduced} onClick={() => setPaused(value => !value)}>{paused || reduced ? <Play size={14}/> : <Pause size={14}/>}</button>
    </div>}
    {exploring&&!editing&&focus==='demo'&&!inspected&&<section ref={contextPanel} className="map-context" aria-label="Current collection"><strong>{parent?items.find(i=>i.id===parent)?.title:exploring==='demo'?workspaceName||'Organization':worldStations.find(s=>s.id===exploring)?.label}</strong><span role="status">{query.trim()?`${matches.length} ${matches.length===1?'match':'matches'}`:`${collectionCount} ${collectionLabel}`}</span>
      {exploring==='journey'&&focus==='demo'&&draftRequest&&['admin','engineer','member'].includes(role)&&<button aria-label="New request" onClick={()=>draftRequest('feature','')}><Plus size={14}/>New request</button>}
      {exploring==='demo'&&focus==='demo'&&openTeams&&<button onClick={openTeams}>{role==='admin'?'Manage teams':'Team directory'}</button>}
      {refreshMap&&<button aria-label="Refresh saved workspace" disabled={refreshing} onClick={async()=>{setRefreshing(true);try{await refreshMap();}finally{setRefreshing(false);}}}><RefreshCw size={13}/></button>}
      {matches.length>6&&<><button aria-label="Previous collection page" disabled={!currentPage} onClick={()=>setPage(currentPage-1)}><ChevronLeft size={15}/></button><small>{currentPage+1}/{Math.ceil(matches.length/6)}</small><button aria-label="Next collection page" disabled={(currentPage+1)*6>=matches.length} onClick={()=>setPage(currentPage+1)}><ChevronRight size={15}/></button></>}
      {!!collection.length&&<div className="collection-search" role="search" aria-label="Search current collection"><Search size={15}/><input aria-label="Find in this collection" placeholder="Find in this collection" maxLength={160} value={query} onChange={e=>{setQuery(e.target.value);setPage(0);setHovered(null);}} onKeyDown={e=>{if(e.key==='Escape')setQuery('');}}/>{query&&<button aria-label="Clear collection search" onClick={()=>setQuery('')}><X size={14}/></button>}</div>}
      {!matches.length&&<small role="status">{query.trim()?'No matching items.':exploring==='demo'?'No team details available for this role.':'No saved items here yet.'}</small>}
      {exploring==='demo'&&mapTruncated&&<small>Showing the first 50 people and 10 projects.</small>}
    </section>}
    {hovered&&!editing&&peek&&<div className="map-peek" role="tooltip" style={{left:peek.x,top:peek.y,width:peek.width,maxHeight:peek.height}}><strong>{title}</strong><span>{(hoveredItem?.description||stationDescriptions[hovered.station]).slice(0,100)}</span>{hoveredItem&&<small>{hoveredItem.status.replaceAll('_',' ')}{hoveredItem.by?` · ${hoveredItem.by}`:''}</small>}</div>}
    {selectedPerson&&<section className="map-person-detail" aria-label="Person access details" onKeyDown={e=>{if(e.key==='Escape'){setInspected(null);labels.current['record:'+selectedPerson.id]?.focus();}}}><header><h2 tabIndex={-1} ref={personHeading}>{selectedPerson.title}</h2><button aria-label="Close person details" onClick={()=>{setInspected(null);labels.current['record:'+selectedPerson.id]?.focus();}}><X size={18}/></button></header><p>{selectedPerson.description} · {selectedPerson.status}</p><h3>Project access</h3>{selectedPerson.details?.length?selectedPerson.details.map(d=><div key={d.project}><strong>{d.project}</strong><span className={d.allowed?'permitted':'denied'}>{d.allowed?'Can read':'No access'}</span></div>):<p>Access details are not loaded for this profile.</p>}<small>Policy preview · {mapAsOf?new Date(mapAsOf).toLocaleTimeString():'snapshot'}<br/>The host checks every actual read.</small></section>}
    {editing && <SceneWorkshop layout={layout} change={save} allowed={allowedStations(role)} close={closeWorkshop} reset={()=>save(defaultLayout())} notice={setMessage}/>}
    <span className="scene-save-status" role="status">{message}</span>
    {children}
    {role!=='guest'&&planCommand&&<AgentCommand role={role} identityKey={`${tenant}:${user}`} transport={planCommand} preview={previewCommand} apply={applyCommand} onState={setAgentState}/>}
  </div>;
}
