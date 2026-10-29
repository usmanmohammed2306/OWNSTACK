import type { SpatialDestination } from './spatialWorkspaceModel.ts';

/** Category colors are navigation cues, never permission or execution status. */
export const workspaceColors: Record<SpatialDestination, {solid:number; pale:string; ink:string}> = {
  demo: {solid:0x3159e8, pale:'#edf0ff', ink:'#203ca1'},
  journey: {solid:0xe85c45, pale:'#fff0e9', ink:'#973723'},
  access: {solid:0x109b83, pale:'#e6f7ef', ink:'#09634e'},
  engineering: {solid:0x8154d6, pale:'#f2edff', ink:'#58369b'},
  convergence: {solid:0xe8aa32, pale:'#fff5dc', ink:'#7e540c'},
};
