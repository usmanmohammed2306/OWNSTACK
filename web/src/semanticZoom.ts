import type { SpatialDestination } from './spatialWorkspaceModel.ts';
import {clampZoom} from './spatialRecords.ts';

export type ZoomContext={zoom:number;station:SpatialDestination|null;parent:string|null};
/** Separate entry/exit thresholds prevent a trackpad from flickering levels. */
export function semanticZoom(current:ZoomContext,delta:number,target:SpatialDestination='demo',roleId:string|null=null):ZoomContext {
  if(!Number.isFinite(delta)||delta===0)return current;
  // Wheel deltas accumulate binary rounding error. Quantize navigation, while
  // the camera still interpolates continuously between the resulting targets.
  const next=clampZoom(Math.round((current.zoom+Math.max(-.3,Math.min(.3,delta)))*1000)/1000);
  if(delta<0&&current.parent&&next<1.85)return {zoom:1.95,station:current.station,parent:null};
  if(delta<0&&current.station&&!current.parent&&next<1.4)return {zoom:1.05,station:null,parent:null};
  if(delta>0&&!current.station&&next>=1.3)return {zoom:1.7,station:target,parent:null};
  if(delta>0&&current.station==='demo'&&!current.parent&&roleId&&next>=2.2)return {zoom:2.3,station:'demo',parent:roleId};
  return {...current,zoom:next};
}
