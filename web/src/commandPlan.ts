import { allowedStations, type SpatialDestination } from './spatialWorkspaceModel.ts';
import { defaultLayout, moveStation, type WorkspaceLayout, type Palette } from './workspaceLayout.ts';
export type CommandAction = {action:'navigate';target:SpatialDestination}|{action:'move';target:SpatialDestination;x:number;z:number}|{action:'theme';target:Palette}|{action:'draft';target:'access'|'feature'}|{action:'reset'|'clarify'|'refuse'};
export type CommandPlan = {actions:CommandAction[]};
/** The browser rejects unexpected effects independently of the model/API renderer. */
export function parseCommandPlan(value: unknown, role: string): CommandPlan | null {
  if(!value||typeof value!=='object'||Array.isArray(value))return null;
  const p=value as Record<string,unknown>;
  if(Object.keys(p).join()!=='actions'||!Array.isArray(p.actions)||p.actions.length<1||p.actions.length>4)return null;
  for(const row of p.actions){
    if(!row||typeof row!=='object'||Array.isArray(row))return null;
    const a=row as Record<string,unknown>, keys=Object.keys(a).sort().join(',');
    if(a.action==='navigate'||a.action==='move'){
      if(!allowedStations(role).includes(a.target as SpatialDestination))return null;
      if(a.action==='navigate'&&keys!=='action,target')return null;
      if(a.action==='move'&&(keys!=='action,target,x,z'||![a.x,a.z].every(v=>typeof v==='number'&&Number.isFinite(v)&&v>=-4&&v<=4)))return null;
    }else if(a.action==='theme'){if(keys!=='action,target'||!['ice','violet','mint'].includes(String(a.target)))return null;}
    else if(a.action==='draft'){if(keys!=='action,target'||!['admin','engineer','member'].includes(role)||!['access','feature'].includes(String(a.target)))return null;}
    else if(!['reset','clarify','refuse'].includes(String(a.action))||keys!=='action')return null;
  }
  const actions=p.actions as CommandAction[];
  if(actions.some(a=>a.action==='clarify'||a.action==='refuse')&&actions.length!==1)return null;
  if(actions.filter(a=>a.action==='draft').length>1)return null;
  return {actions};
}
export function layoutForPlan(layout:WorkspaceLayout, plan:CommandPlan):WorkspaceLayout {
  return plan.actions.reduce((next,a)=>a.action==='theme'?{...next,palette:a.target}:a.action==='move'?moveStation(next,a.target,a.x,a.z):a.action==='reset'?{...defaultLayout(),revision:next.revision}:next,layout);
}
