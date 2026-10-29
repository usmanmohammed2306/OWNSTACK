import type { SpatialDestination } from './spatialWorkspaceModel.ts';
export type SpatialRecord = { id:string;station:SpatialDestination;title:string;description:string;status:string;by?:string;code?:string;path?:string;parent?:string;parents?:string[];kind?:string;related?:string[];details?:{project:string;allowed:boolean;basis:string}[] };
export const stationDescriptions:Record<SpatialDestination,string>={demo:'People, reporting lines, teams and access',journey:'Customer requests and reusable patterns',access:'Who can access what, and until when',engineering:'Exact code changes and team review',convergence:'Repeated customer needs, considered together'};
/** A multi-team person is one saved record, reachable through each parent. */
export function collectionRecords(items:SpatialRecord[],station:SpatialDestination|null,parent:string|null=null):SpatialRecord[]{
  return items.filter(i=>i.station===station&&(station!=='demo'||(parent?i.parent===parent||i.parents?.includes(parent):i.kind==='role'||i.parent==='organization')));
}
/** Search only the supplied collection. It never fetches or broadens its scope. */
export function searchRecords(items:SpatialRecord[],query:string):SpatialRecord[]{
  const normalize=(s:string)=>s.normalize('NFKC').toLowerCase().replaceAll('_',' ');
  const words=normalize(query).trim().split(/\s+/).filter(Boolean);
  return words.length?items.filter(item=>{
    const text=normalize([item.title,item.description,item.status,item.by,item.path].filter(Boolean).join(' '));
    return words.every(word=>text.includes(word));
  }):items;
}
/** Refreshes and searches can reduce a collection while its old page is selected. */
export function collectionPage(page:number,count:number):number{
  return Math.max(0,Math.min(Number.isFinite(page)?Math.floor(page):0,Math.floor(Math.max(0,count-1)/6)));
}
/** Bounded pages keep each physical collection inspectable without inventing records. */
export function stationRecords(items:SpatialRecord[],station:SpatialDestination,page=0):SpatialRecord[]{const index=Number.isFinite(page)?Math.max(0,Math.floor(page)):0;return items.filter(i=>i.station===station).slice(index*6,index*6+6);}
export function safeRecord(items:SpatialRecord[],station:SpatialDestination,id:string){return items.find(i=>i.station===station&&i.id===id)||null;}
export const clampZoom=(n:number)=>Number.isFinite(n)?Math.max(.65,Math.min(3.2,n)):1;
