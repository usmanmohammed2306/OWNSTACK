import * as THREE from 'three/webgpu';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { worldStations, type SpatialDestination } from './spatialWorkspaceModel';
import { defaultLayout, moveStation, type WorkspaceLayout } from './workspaceLayout';
import { clampZoom, type SpatialRecord } from './spatialRecords';
import { springStep } from './spatialMotion';
import { createStudioLighting } from './StudioLighting';
import { workspaceColors } from './workspaceColors';
import { buildPavilion } from './WorkspaceArchitecture';

export type WorldView = { focus: string; allowed: SpatialDestination[]; motion: boolean; visible: boolean; illustration: boolean; editing?: boolean; layout?:WorkspaceLayout;zoom?:number;exploring?:SpatialDestination|null;items?:SpatialRecord[];connections?:SpatialRecord[];highlight?:string;agentState?:'idle'|'working'|'review'|'error' };
export type WorldHover={station:SpatialDestination;id?:string;x:number;y:number};
export type SpatialWorld = { update: (view: WorldView) => void; rotate: (direction: number) => void; dispose: () => void };

/** Navigable product shell. Scene geometry cannot call the API or change permissions. */
export async function createSpatialWorld(host: HTMLElement, initial: WorldView,
  pick: (id: SpatialDestination) => void, anchors: (value: Record<string, [number, number]>, obstacles:{x:number;y:number;width:number;height:number}[]) => void,
  onFailure: () => void, drop?: (id: SpatialDestination, x: number, z: number) => void,
  interactions?:{inspect:(station:SpatialDestination,id:string)=>void;hover:(value:WorldHover|null)=>void;zoom:(amount:number,station?:SpatialDestination)=>void}): Promise<SpatialWorld> {
  const renderer = new THREE.WebGPURenderer({ antialias: true, alpha: true });
  const scene = new THREE.Scene(), assembly = new THREE.Group();
  const camera = new THREE.PerspectiveCamera(37, 1, .1, 80);
  const geometries = new Set<THREE.BufferGeometry>(), materials = new Set<THREE.Material>();
  const targets: THREE.Mesh[] = [], groups = new Map<string, THREE.Group>(), routes = new Map<string, THREE.Mesh>();
  const itemGroups=new Map<string,THREE.Group>(),itemTargets:THREE.Mesh[]=[],itemResources:{geometry:THREE.BufferGeometry;material:THREE.Material;texture?:THREE.Texture}[]=[];
  let renderedItems:SpatialRecord[]|undefined;
  let itemFingerprint='',reveal=1,revealVelocity=0;
  let renderedConnections:SpatialRecord[]|undefined;
  const links:{line:THREE.Line;from:SpatialRecord;to:SpatialRecord}[]=[];
  const linkMaterial=new THREE.LineBasicNodeMaterial({color:0x6b9eb9,transparent:true,opacity:.2}),highlightLinkMaterial=new THREE.LineBasicNodeMaterial({color:0x2f8fb8,transparent:true,opacity:.65});materials.add(linkMaterial);materials.add(highlightLinkMaterial);
  const fromPoint=new THREE.Vector3(),toPoint=new THREE.Vector3();
  const cameraTarget=new THREE.Vector3(),cameraGoal=new THREE.Vector3(),worldQuaternion=new THREE.Quaternion();
  const cameraVelocity=new THREE.Vector3();let scaleVelocity=0,shiftVelocity=0,orbitVelocity=0;
  const raycaster = new THREE.Raycaster(), pointer = new THREE.Vector2(), point = new THREE.Vector3();
  const canvas = renderer.domElement;
  const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0), dragPoint = new THREE.Vector3(), offset = new THREE.Vector3();
  let held: SpatialDestination | undefined, dragLayout: WorkspaceLayout | undefined;
  let disposed = false, frame = 0, previous = 0, elapsed = 0, view = initial;
  let hover: string | null = null, dragging = false, moved = false, startX = 0, startY = 0, travel = 0, orbit = 0, targetOrbit = 0;
  let observer: ResizeObserver | undefined;
  let environment: THREE.RenderTarget | undefined;
  let studio:ReturnType<typeof createStudioLighting>|undefined;
  let cameraShift = initial.focus === 'demo' ? -.155 : .25, cameraScale = initial.focus === 'demo' ? 1.22 : 1.5;
  const key = new THREE.DirectionalLight(0xffffff, 2.1);
  const glass = new THREE.MeshPhysicalNodeMaterial({ color: 0xd6e2ff, transparent: true, opacity: .5,
    metalness: .02, roughness: .16, clearcoat: 1, clearcoatRoughness: .16, ior:1.46, side: THREE.DoubleSide });
  const metal = new THREE.MeshStandardNodeMaterial({ color: 0x26344d, metalness: .3, roughness: .33 });
  const dark = new THREE.MeshStandardNodeMaterial({ color: 0x17233b, metalness: .15, roughness: .4 });
  const silver = new THREE.MeshStandardNodeMaterial({ color: 0xc4ccd8, metalness: .72, roughness: .24 });
  const copper = new THREE.MeshStandardNodeMaterial({ color: 0xf4f7fa, metalness: .08, roughness: .4 });
  const cyan = new THREE.MeshPhysicalNodeMaterial({ color: 0x3159e8, metalness: .22, roughness: .26, clearcoat: .75 });
  const amber = new THREE.MeshStandardNodeMaterial({ color: 0xe8aa32, metalness: .12, roughness: .35 });
  const solids = Object.fromEntries(Object.entries(workspaceColors).map(([id,{solid}])=>{
    const material=new THREE.MeshPhysicalNodeMaterial({color:solid,metalness:.18,roughness:.27,clearcoat:.7,clearcoatRoughness:.22});
    materials.add(material);return [id,material];
  })) as Record<SpatialDestination,THREE.MeshPhysicalNodeMaterial>;
  [glass,metal,dark,silver,copper,cyan,amber].forEach(m => materials.add(m));
  function mesh(g: THREE.BufferGeometry, m: THREE.Material, parent: THREE.Object3D, x=0,y=0,z=0) {
    geometries.add(g); const item = new THREE.Mesh(g,m); item.position.set(x,y,z); item.castShadow=true; item.receiveShadow=true; parent.add(item); return item;
  }
  function box(w: number,h: number,d: number,m: THREE.Material,parent: THREE.Object3D,x=0,y=0,z=0,r=.045) {
    return mesh(new RoundedBoxGeometry(w,h,d,3,r),m,parent,x,y,z);
  }
  function ring(radius: number,tube: number,m: THREE.Material,parent: THREE.Object3D,y: number) {
    const item=mesh(new THREE.TorusGeometry(radius,tube,10,80),m,parent,0,y,0); item.rotation.x=Math.PI/2; return item;
  }
  function route(to: [number,number,number],m: THREE.Material) {
    const curve=new THREE.CatmullRomCurve3([new THREE.Vector3(0,-.18,0),new THREE.Vector3(to[0]*.5,-.12,to[2]*.5),new THREE.Vector3(to[0],-.12,to[2])]);
    return mesh(new THREE.TubeGeometry(curve,36,.012,6,false),m,assembly);
  }
  scene.add(assembly); scene.fog=new THREE.FogExp2(0xe6edf1,.010);
  scene.add(new THREE.HemisphereLight(0xffffff,0x8992a5,.72)); key.position.set(-4,8,5); key.castShadow=true;
  key.shadow.mapSize.set(2048,2048); key.shadow.camera.left=-7; key.shadow.camera.right=7; key.shadow.camera.top=7; key.shadow.camera.bottom=-7; key.shadow.normalBias=.025; scene.add(key);
  const rim=new THREE.DirectionalLight(0xd5deff,1.2); rim.position.set(4,4,-5); scene.add(rim);
  const warm=new THREE.DirectionalLight(0xffffff,.65); warm.position.set(-5,2,-3); scene.add(warm);
  const floor=mesh(new THREE.PlaneGeometry(200,200),new THREE.MeshStandardNodeMaterial({color:0xe6edf1,metalness:.04,roughness:.68}),scene,0,-.76,0);
  materials.add(floor.material); floor.rotation.x=-Math.PI/2;
  const grid=new THREE.GridHelper(64,64,0xc9dce7,0xdbe7ef); grid.position.y=-.75; scene.add(grid); geometries.add(grid.geometry);
  (Array.isArray(grid.material)?grid.material:[grid.material]).forEach(m=>materials.add(m));
  const campus=new THREE.Group();assembly.add(campus);
  box(8.35,.14,6.55,copper,campus,0,-.56,-.35,.22);
  box(8.16,.025,6.36,silver,campus,0,-.47,-.35,.15);
  box(8.02,.035,6.22,copper,campus,0,-.44,-.35,.12);
  // Engraved lanes make the five rooms read as one connected product.
  for(const x of [-3.55,3.55])for(let i=0;i<8;i++)box(.015,.004,.12,silver,campus,x,-.415,-2.65+i*.65,.003);
  const core=new THREE.Group(); groups.set('demo',core); assembly.add(core);
  buildPavilion('demo',core,{box,mesh,white:copper,silver,dark,glass,accent:cyan,amber});
  const heart=mesh(new THREE.SphereGeometry(.12,20,12),cyan,core,.28,1.7,.17);
  const intelligence=new THREE.Group();core.add(intelligence);
  const signalMaterial=new THREE.MeshStandardNodeMaterial({color:0x16bace,emissive:0x16bace,emissiveIntensity:.7,metalness:.3,roughness:.22});materials.add(signalMaterial);
  const signals:THREE.Mesh[]=[];
  for(let i=0;i<8;i++){const dot=mesh(new THREE.SphereGeometry(.018,8,6),signalMaterial,intelligence);signals.push(dot);}
  const orbitRing=ring(.34,.008,silver,core,1.7);orbitRing.position.x=.28;orbitRing.position.z=.17;orbitRing.rotation.x=.6;
  const coreTarget=box(1.9,1.95,1.8,new THREE.MeshBasicNodeMaterial({transparent:true,opacity:0,depthWrite:false,colorWrite:false}),core,0,.65,0); coreTarget.castShadow=false; materials.add(coreTarget.material); coreTarget.userData.destination='demo'; targets.push(coreTarget);
  core.children.forEach((child,index)=>{child.userData.structure=true;child.userData.plinth=index<2;});
  for(const station of worldStations.filter(s=>s.id!=='demo')){
    const g=new THREE.Group(); g.position.set(station.position[0],-.14,station.position[2]); assembly.add(g); groups.set(station.id,g);
    const solid=solids[station.id];
    buildPavilion(station.id,g,{box,mesh,white:copper,silver,dark,glass,accent:solid,amber});
    const target=box(1.9,1.4,1.8,new THREE.MeshBasicNodeMaterial({transparent:true,opacity:0,depthWrite:false,colorWrite:false}),g,0,.4,0); target.castShadow=false; materials.add(target.material);target.userData.destination=station.id;targets.push(target);
    g.children.forEach((child,index)=>{child.userData.structure=true;child.userData.plinth=index<2;});
    routes.set(station.id,route(station.position,solid));
  }
  const reticle=new THREE.Group();assembly.add(reticle);
  const reticleMaterial=new THREE.MeshBasicNodeMaterial({color:0x58b8df,transparent:true,opacity:.7});materials.add(reticleMaterial);
  for(let i=0;i<4;i++){const arc=mesh(new THREE.TorusGeometry(1.11,.012,8,40,Math.PI*.32),reticleMaterial,reticle);arc.rotation.x=Math.PI/2;arc.rotation.z=i*Math.PI/2+.1;}
  reticle.visible=false;
  camera.position.set(4,7,10.8); camera.lookAt(0,.1,0);
  function hitObject(event:PointerEvent){
    const r=canvas.getBoundingClientRect(); pointer.set((event.clientX-r.left)/r.width*2-1,-(event.clientY-r.top)/r.height*2+1);
    raycaster.setFromCamera(pointer,camera);
    const detail=raycaster.intersectObjects(itemTargets.filter(t=>view.allowed.includes(t.userData.destination)&&!!view.exploring&&t.parent?.visible),false)[0]?.object;
    return detail||raycaster.intersectObjects(targets.filter(t=>t.visible&&t.parent?.visible&&view.allowed.includes(t.userData.destination)),false)[0]?.object;
  }
  function hit(event:PointerEvent){return hitObject(event)?.userData.destination as SpatialDestination|undefined;}
  function groundPoint(event:PointerEvent){hit(event);if(!raycaster.ray.intersectPlane(plane,dragPoint))return null;return assembly.worldToLocal(dragPoint);}
  function down(event:PointerEvent){ if(event.button!==0)return;dragging=true;moved=false;travel=0;startX=event.clientX;startY=event.clientY;held=view.editing?hit(event):undefined;dragLayout=undefined;if(held){const p=groundPoint(event);if(p)offset.copy(p).sub(groups.get(held)!.position);}canvas.setPointerCapture(event.pointerId); }
  function move(event:PointerEvent){
    if(dragging){const delta=event.clientX-startX;travel+=Math.abs(delta)+Math.abs(event.clientY-startY);if(travel>4)moved=true;if(held&&moved){const p=groundPoint(event);if(p)dragLayout=moveStation(view.layout||defaultLayout(),held,p.x-offset.x,p.z-offset.z);}else if(event.pointerType==='mouse')targetOrbit=THREE.MathUtils.clamp(targetOrbit+delta*.003,-Math.PI,Math.PI);startX=event.clientX;startY=event.clientY;}
    const object=hitObject(event),next=object?.userData.destination||null; if(next!==hover){hover=next;canvas.style.cursor=next?(view.editing?'grab':'pointer'):'grab';}
    interactions?.hover(!dragging&&object?{station:object.userData.destination,id:object.userData.record,x:event.clientX,y:event.clientY}:null);requestFrame();
  }
  function up(event:PointerEvent){if(event.type==='pointerup'&&dragging){if(held&&moved&&view.editing){const p=(dragLayout||view.layout||defaultLayout()).positions[held];drop?.(held,p[0],p[1]);}else if(!moved&&!view.editing){const object=hitObject(event);if(object?.userData.record)interactions?.inspect(object.userData.destination,object.userData.record);else if(object)pick(object.userData.destination);}}dragLayout=undefined;held=undefined;dragging=false;if(canvas.hasPointerCapture(event.pointerId))canvas.releasePointerCapture(event.pointerId);requestFrame();}
  let wheelFrame=0,wheelDelta=0,wheelStation:SpatialDestination|undefined;
  function wheel(event:WheelEvent){
    event.preventDefault();if(!Number.isFinite(event.deltaY)||event.deltaY===0)return;
    const rect=canvas.getBoundingClientRect();pointer.set((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1);raycaster.setFromCamera(pointer,camera);
    const object=raycaster.intersectObjects(targets.filter(t=>t.visible&&t.parent?.visible&&view.allowed.includes(t.userData.destination)),false)[0]?.object;
    wheelStation=object?.userData.destination;
    // A trackpad can deliver many events per frame. Bound a frame's navigation
    // step so it cannot skip every semantic level in one burst.
    const pixels=event.deltaY*(event.deltaMode===1?16:event.deltaMode===2?host.clientHeight:1);
    wheelDelta=THREE.MathUtils.clamp(wheelDelta-pixels*.002,-.2,.2);
    if(!wheelFrame)wheelFrame=requestAnimationFrame(()=>{wheelFrame=0;if(!disposed)interactions?.zoom(wheelDelta,wheelStation);wheelDelta=0;});
  }
  function leave(){if(!dragging){hover=null;interactions?.hover(null);requestFrame();}}
  function clearItems(){for(const group of itemGroups.values())group.removeFromParent();itemGroups.clear();itemTargets.length=0;for(const r of itemResources){r.geometry.dispose();r.material.dispose();r.texture?.dispose();}itemResources.length=0;}
  function syncItems(){
    if(renderedItems===view.items)return;renderedItems=view.items;
    const fingerprint=JSON.stringify((view.items||[]).map(i=>[i.id,i.title,i.description,i.status,i.by,i.code]));
    if(fingerprint===itemFingerprint)return;itemFingerprint=fingerprint;clearItems();reveal=view.motion?0:1;revealVelocity=0;
    for(const [i,item] of (view.items||[]).slice(0,6).entries()){
      if(!view.allowed.includes(item.station))continue;
      const parent=groups.get(item.station);if(!parent)continue;
      const group=new THREE.Group();parent.add(group);itemGroups.set(item.id,group);
      const columns=host.clientWidth<700?2:3,rowCount=Math.min(columns,Math.min(view.items?.length||0,6)-Math.floor(i/columns)*columns);group.position.set((i%columns-(rowCount-1)/2)*1.22,2.05-Math.floor(i/columns)*1.03,.55);group.userData.index=i;
      const drawing=document.createElement('canvas');drawing.width=512;drawing.height=352;const ctx=drawing.getContext('2d');if(!ctx)continue;
      const category=workspaceColors[item.station],hex='#'+category.solid.toString(16).padStart(6,'0');
      ctx.fillStyle='#fffdf9';ctx.fillRect(0,0,512,352);ctx.fillStyle=hex;ctx.fillRect(0,0,512,8);
      ctx.fillStyle='#202b42';ctx.font='600 30px sans-serif';ctx.fillText(item.title.slice(0,26),24,47);
      ctx.font='18px sans-serif';ctx.fillStyle='#596174';ctx.fillText((item.by||item.description).slice(0,47),24,78);
      if(item.code){ctx.fillStyle='#1e263a';ctx.fillRect(16,94,480,200);ctx.font='19px monospace';ctx.fillStyle='#d6ccff';item.code.split('\n').slice(0,7).forEach((line,j)=>ctx.fillText(line.slice(0,39),28,120+j*24));}
      else if(item.kind==='person'){
        ctx.fillStyle=category.pale;ctx.beginPath();ctx.arc(256,165,47,0,Math.PI*2);ctx.fill();ctx.fillStyle=hex;ctx.beginPath();ctx.ellipse(256,252,76,42,0,Math.PI,Math.PI*2);ctx.fill();
        ctx.fillStyle=category.ink;ctx.font='600 38px sans-serif';ctx.textAlign='center';ctx.fillText(item.title[0].toUpperCase(),256,179);ctx.textAlign='left';
      }else {
        // A category glyph gives collections a silhouette; full prose stays in inspection.
        ctx.fillStyle=category.pale;ctx.fillRect(24,101,464,182);ctx.strokeStyle=hex;ctx.lineWidth=12;ctx.lineJoin='round';ctx.lineCap='round';
        if(item.kind==='role'||item.kind==='team'){ctx.strokeRect(218,120,76,45);ctx.beginPath();ctx.moveTo(256,165);ctx.lineTo(256,195);ctx.moveTo(159,220);ctx.lineTo(159,195);ctx.lineTo(353,195);ctx.lineTo(353,220);ctx.stroke();[159,256,353].forEach(x=>ctx.strokeRect(x-22,222,44,35));}
        else if(item.station==='access'){ctx.beginPath();ctx.arc(256,158,31,Math.PI,0);ctx.lineTo(287,184);ctx.moveTo(225,158);ctx.lineTo(225,184);ctx.stroke();ctx.fillStyle=hex;ctx.fillRect(208,181,96,73);ctx.fillStyle=category.pale;ctx.fillRect(251,207,10,24);}
        else if(item.station==='engineering'){ctx.beginPath();ctx.moveTo(221,151);ctx.lineTo(181,190);ctx.lineTo(221,229);ctx.moveTo(291,151);ctx.lineTo(331,190);ctx.lineTo(291,229);ctx.moveTo(272,138);ctx.lineTo(240,242);ctx.stroke();}
        else if(item.station==='convergence'){ctx.beginPath();ctx.moveTo(191,222);ctx.lineTo(256,149);ctx.lineTo(321,222);ctx.closePath();ctx.stroke();[ [191,222],[256,149],[321,222] ].forEach(([x,y])=>{ctx.beginPath();ctx.arc(x,y,16,0,Math.PI*2);ctx.fillStyle=hex;ctx.fill();});}
        else {ctx.strokeRect(205,125,102,124);ctx.beginPath();ctx.moveTo(230,159);ctx.lineTo(282,159);ctx.moveTo(230,188);ctx.lineTo(282,188);ctx.moveTo(230,217);ctx.lineTo(263,217);ctx.stroke();}
      }
      ctx.fillStyle=category.pale;ctx.fillRect(0,306,512,46);ctx.font='600 18px sans-serif';ctx.fillStyle=category.ink;ctx.fillText(item.status.replaceAll('_',' ').slice(0,48),24,336);
      const texture=new THREE.CanvasTexture(drawing);texture.colorSpace=THREE.SRGBColorSpace;texture.anisotropy=4;
      const material=new THREE.MeshBasicNodeMaterial({map:texture,side:THREE.DoubleSide,toneMapped:false,fog:false}),geometry=new THREE.PlaneGeometry(1.12,.77);
      const card=new THREE.Mesh(geometry,material);card.userData.destination=item.station;card.userData.record=item.id;group.add(card);itemTargets.push(card);itemResources.push({geometry,material,texture});
      const backGeometry=new RoundedBoxGeometry(1.16,.81,.09,3,.04),backMaterial=new THREE.MeshStandardNodeMaterial({color:category.solid,metalness:.1,roughness:.3});
      // Keep the rounded solid behind the text plane, including its front face.
      const back=new THREE.Mesh(backGeometry,backMaterial);back.position.z=-.06;group.add(back);itemResources.push({geometry:backGeometry,material:backMaterial});
    }
  }
  function syncConnections(){
    if(renderedConnections===view.connections)return;renderedConnections=view.connections;
    for(const link of links){link.line.removeFromParent();link.line.geometry.dispose();}links.length=0;
    const all=new Map((view.connections||[]).map(r=>[r.id,r]));
    for(const item of all.values())for(const id of [...item.related||[],...item.parent?[item.parent]:[]]){
      const parent=all.get(id);if(!parent||links.length>=120)continue;
      const geometry=new THREE.BufferGeometry().setAttribute('position',new THREE.BufferAttribute(new Float32Array(25*3),3));
      const line=new THREE.Line(geometry,linkMaterial);assembly.add(line);links.push({line,from:item,to:parent});
    }
  }
  function lost(event:Event){event.preventDefault();fail();}
  function requestFrame(){if(!disposed&&!frame)frame=requestAnimationFrame(draw);}
  function draw(now:number){
    frame=0;if(disposed||!view.visible)return;
    syncItems();syncConnections();
    const frameInterval=dragging||hover||reveal<.999?15:32;
    if(view.motion&&view.visible&&previous&&now-previous<frameInterval){requestFrame();return;}
    const dt=previous?Math.min((now-previous)/1000,.05):1/30;previous=now;
    const moving=view.motion&&view.visible;const mix=moving?1-Math.exp(-dt*7):1; if(moving)elapsed+=dt;
    campus.visible=!view.exploring&&!view.editing;
    const turn=view.motion?springStep(orbit,orbitVelocity,targetOrbit,dt):{position:targetOrbit,velocity:0,settled:true};orbit=turn.position;orbitVelocity=turn.velocity;assembly.rotation.y=orbit;
    const opening=view.motion?springStep(reveal,revealVelocity,1,dt):{position:1,velocity:0,settled:true};reveal=opening.position;revealVelocity=opening.velocity;
    const layout=dragLayout||view.layout||defaultLayout(),color=layout.palette==='violet'?0x8154d6:layout.palette==='mint'?0x109b83:workspaceColors.demo.solid;
    cyan.color.setHex(color);glass.color.setHex(layout.palette==='violet'?0xded6f7:layout.palette==='mint'?0xc9eee3:0xd6e2ff);renderer.toneMappingExposure=layout.light*.9;grid.visible=!!view.editing;
    let settling=!turn.settled||!opening.settled;
    for(const [id,g] of groups){
      g.visible=(view.allowed.includes(id as SpatialDestination)||view.illustration)&&(!view.exploring||id===view.exploring||!!view.editing);
      // The selected physical object remains as context while its records open.
      // Other stations are hidden, so there are no cropped neighbor silhouettes.
      for(const child of g.children)if(child.userData.structure)child.visible=true;
      const connector=routes.get(id);if(connector){connector.visible=g.visible&&!view.exploring;const start=(layout.positions.demo),end=layout.positions[id as SpatialDestination];connector.position.set(start[0],0,start[1]);const dx=end[0]-start[0],dz=end[1]-start[1],original=worldStations.find(s=>s.id===id)!.position;const angle=Math.atan2(dz,dx)-Math.atan2(original[2],original[0]);connector.rotation.y=-angle;connector.scale.setScalar(Math.hypot(dx,dz)/Math.hypot(original[0],original[2]));}
      const pos=layout.positions[id as SpatialDestination];g.position.x=pos[0];g.position.z=pos[1];const scaleGoal=layout.scale*(hover===id&&!view.editing?1.035:1);g.scale.setScalar(THREE.MathUtils.lerp(g.scale.x,scaleGoal,mix));
      const base=id==='demo'?0:-.14;const y=base+(id===view.focus||id===hover? .16:0);
      g.position.y=THREE.MathUtils.lerp(g.position.y,y,mix);settling=settling||Math.abs(g.position.y-y)>.0005;
    }
    const selectedStation=held||hover||worldStations.find(s=>s.id===view.highlight)?.id||view.exploring;
    reticle.visible=!!selectedStation;
    if(selectedStation){const g=groups.get(selectedStation)!;reticle.position.set(g.position.x,-.32,g.position.z);reticle.scale.setScalar(layout.scale);reticle.rotation.y=view.motion?elapsed*.12:0;reticleMaterial.color.setHex(color);}
    if(moving){heart.rotation.y=elapsed*.18;orbitRing.rotation.z=.45+Math.sin(elapsed*.25)*.08;}
    const working=view.agentState==='working';signalMaterial.emissiveIntensity=working?1.7:.35;
    signalMaterial.color.setHex(view.agentState==='error'?0xbf6c53:view.agentState==='review'?0x62a77b:0x16bace);
    signals.forEach((dot,i)=>{const angle=i/signals.length*Math.PI*2+elapsed*(working?1.5:.12);dot.position.set(.28+Math.cos(angle)*.35,1.7+Math.sin(angle*2)*.06,.17+Math.sin(angle)*.35);dot.scale.setScalar(working?1.5:1);});
    const mobile=host.clientWidth<600;
    // CSS reserves the actual stage. Frame within it, not behind a reading panel.
    const shift=0;
    const scale=Math.max(.84,host.clientHeight/Math.max(host.clientWidth,1)*1.18)/clampZoom(view.zoom||1);
    const lens=view.motion?springStep(cameraScale,scaleVelocity,scale,dt):{position:scale,velocity:0,settled:true};cameraScale=lens.position;scaleVelocity=lens.velocity;
    const offsetStep=view.motion?springStep(cameraShift,shiftVelocity,shift,dt):{position:shift,velocity:0,settled:true};cameraShift=offsetStep.position;shiftVelocity=offsetStep.velocity;settling ||= !lens.settled||!offsetStep.settled;
    cameraGoal.set(0,-.05,0);if(view.exploring){groups.get(view.exploring)!.getWorldPosition(cameraGoal);cameraGoal.y+=1.1;}
    for(const axis of ['x','y','z'] as const){const step=view.motion?springStep(cameraTarget[axis],cameraVelocity[axis],cameraGoal[axis],dt):{position:cameraGoal[axis],velocity:0,settled:true};cameraTarget[axis]=step.position;cameraVelocity[axis]=step.velocity;settling ||=!step.settled;}
    camera.position.set(4,7,10.8).multiplyScalar(cameraScale).add(cameraTarget);camera.lookAt(cameraTarget);
    camera.setViewOffset(host.clientWidth,host.clientHeight,host.clientWidth*cameraShift,0,host.clientWidth,host.clientHeight);
    camera.updateProjectionMatrix();
    camera.updateMatrixWorld();
    const projected:Record<string,[number,number]>={};
    assembly.updateMatrixWorld(true);
    for(const [id,g] of itemGroups){g.visible=!!view.exploring;const columns=mobile?2:3,i=g.userData.index,rowCount=Math.min(columns,itemGroups.size-Math.floor(i/columns)*columns),progress=THREE.MathUtils.clamp((reveal-i*.035)/(1-i*.035),0,1);g.position.set((i%columns-(rowCount-1)/2)*1.22,2.05-Math.floor(i/columns)*1.03-(1-progress)*.55,.55);g.scale.setScalar((.7+.3*progress)*(view.highlight===id?1.035:1));assembly.getWorldQuaternion(worldQuaternion);g.quaternion.copy(worldQuaternion.invert()).multiply(camera.quaternion);g.getWorldPosition(point);point.y-=.53;point.project(camera);projected['record:'+id]=[(point.x*.5+.5)*host.clientWidth,(-point.y*.5+.5)*host.clientHeight];}
    const drawnConnections=new Set<string>();
    for(const link of links){
      const pair=(view.exploring?[link.from.id,link.to.id]:[link.from.station,link.to.station]).sort().join(':');
      // Overview aggregates repeated relationships; a collection reveals only
      // edges touching its visible records. This avoids stacked, flickering
      // lines through every card while retaining the real saved relationships.
      link.line.visible=view.allowed.includes(link.from.station)&&view.allowed.includes(link.to.station)
        &&!drawnConnections.has(pair)&&(!view.exploring||(itemGroups.has(link.from.id)&&itemGroups.has(link.to.id)))
        &&(!!view.exploring||link.from.station!==link.to.station);
      if(!link.line.visible)continue;
      drawnConnections.add(pair);
      link.line.material=[link.from.id,link.to.id,link.from.station,link.to.station].includes(view.highlight||'')?highlightLinkMaterial:linkMaterial;
      const a=itemGroups.get(link.from.id)||groups.get(link.from.station)!,b=itemGroups.get(link.to.id)||groups.get(link.to.station)!;
      a.getWorldPosition(fromPoint);b.getWorldPosition(toPoint);
      if(itemGroups.has(link.from.id))fromPoint.y-=.46;
      if(itemGroups.has(link.to.id))toPoint.y-=.46;
      assembly.worldToLocal(fromPoint);assembly.worldToLocal(toPoint);
      const attribute=link.line.geometry.getAttribute('position');for(let i=0;i<=24;i++){const t=i/24;attribute.setXYZ(i,THREE.MathUtils.lerp(fromPoint.x,toPoint.x,t),THREE.MathUtils.lerp(fromPoint.y,toPoint.y,t)+Math.sin(t*Math.PI)*.5,THREE.MathUtils.lerp(fromPoint.z,toPoint.z,t));}attribute.needsUpdate=true;link.line.geometry.computeBoundingSphere();
    }
    for(const station of worldStations){
      const g=groups.get(station.id)!;g.getWorldPosition(point);point.y+=station.id==='demo'?.8:.4;point.project(camera);
      projected[station.id]=[(point.x*.5+.5)*host.clientWidth,(-point.y*.5+.5)*host.clientHeight];
    }
    // Labels are callouts, not stickers over the 3D controls. Project the actual
    // hit volumes and reserve those areas when arranging the native buttons.
    const obstacles:{x:number;y:number;width:number;height:number}[]=[];
    if(!view.exploring&&!view.editing)for(const target of targets){
      if(!target.parent?.visible)continue;
      if(!target.geometry.boundingBox)target.geometry.computeBoundingBox();
      const bounds=target.geometry.boundingBox!;let left=Infinity,top=Infinity,right=-Infinity,bottom=-Infinity;
      for(const x of [bounds.min.x,bounds.max.x])for(const y of [bounds.min.y,bounds.max.y])for(const z of [bounds.min.z,bounds.max.z]){
        point.set(x,y,z).applyMatrix4(target.matrixWorld).project(camera);
        const px=(point.x*.5+.5)*host.clientWidth,py=(-point.y*.5+.5)*host.clientHeight;
        left=Math.min(left,px);right=Math.max(right,px);top=Math.min(top,py);bottom=Math.max(bottom,py);
      }
      obstacles.push({x:left,y:top,width:right-left,height:bottom-top});
    }
    anchors(projected,obstacles);
    try{if(studio)studio.render();else renderer.render(scene,camera);}catch{if(studio){studio.dispose();studio=undefined;canvas.dataset.quality='direct';try{renderer.render(scene,camera);}catch{fail();return;}}else{fail();return;}}
    if(view.visible&&(moving||settling))requestFrame();
  }
  function resize(){
    if(disposed)return;const w=Math.max(host.clientWidth,1),h=Math.max(host.clientHeight,1);
    camera.aspect=w/h;
    cameraShift=0;
    cameraScale=Math.max(.84,h/w*1.18)/clampZoom(view.zoom||1);
    renderer.setPixelRatio(Math.min(devicePixelRatio||1,1.5));renderer.setSize(w,h,false);requestFrame();
  }
  function dispose(){
    if(disposed)return;disposed=true;cancelAnimationFrame(frame);cancelAnimationFrame(wheelFrame);observer?.disconnect();
    canvas.removeEventListener('pointerdown',down);canvas.removeEventListener('pointermove',move);canvas.removeEventListener('pointerup',up);canvas.removeEventListener('pointercancel',up);canvas.removeEventListener('pointerleave',leave);canvas.removeEventListener('webglcontextlost',lost);canvas.removeEventListener('wheel',wheel);clearItems();
    studio?.dispose();links.forEach(l=>l.line.geometry.dispose());geometries.forEach(g=>g.dispose());materials.forEach(m=>m.dispose());environment?.dispose();key.shadow.dispose();scene.clear();canvas.remove();void renderer.dispose().catch(()=>{});
  }
  function fail(){if(disposed)return;dispose();onFailure();}
  try{
    await renderer.init();renderer.setClearColor(0xf5f2ec,0);renderer.toneMapping=THREE.NeutralToneMapping;renderer.toneMappingExposure=1;
    // Local studio lighting gives the physical surfaces real reflections, without a downloaded image.
    const room=new RoomEnvironment(), pmrem=new THREE.PMREMGenerator(renderer);
    try{environment=pmrem.fromScene(room,.04);scene.environment=environment.texture;scene.environmentIntensity=.45;}
    finally{room.dispose();pmrem.dispose();}
    renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFShadowMap;renderer.onDeviceLost=fail;
    if('isWebGPUBackend' in renderer.backend){try{studio=createStudioLighting(renderer,scene,camera);canvas.dataset.quality='studio-ao';}catch{canvas.dataset.quality='direct';}}
    canvas.dataset.renderer='isWebGPUBackend' in renderer.backend?'webgpu':'webgl2';canvas.setAttribute('aria-hidden','true');
    canvas.style.cssText='display:block;width:100%;height:100%;touch-action:pan-y pinch-zoom;cursor:grab';host.appendChild(canvas);
    canvas.addEventListener('pointerdown',down);canvas.addEventListener('pointermove',move);canvas.addEventListener('pointerup',up);canvas.addEventListener('pointercancel',up);canvas.addEventListener('pointerleave',leave);canvas.addEventListener('webglcontextlost',lost);canvas.addEventListener('wheel',wheel,{passive:false});
    observer=new ResizeObserver(resize);observer.observe(host);resize();
    return {update(next){view=next;canvas.style.touchAction=next.editing?'none':'pan-y pinch-zoom';previous=0;requestFrame();},rotate(direction){targetOrbit=THREE.MathUtils.clamp(targetOrbit+direction*.15,-Math.PI,Math.PI);requestFrame();},dispose};
  }catch(error){dispose();throw error;}
}
