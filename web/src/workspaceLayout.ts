import { worldStations, type SpatialDestination } from './spatialWorkspaceModel.ts';

export type Palette = 'ice' | 'violet' | 'mint';
export type WorkspaceLayout = { version: 1; revision: number; palette: Palette; scale: number; light: number;
  snap: boolean; positions: Record<SpatialDestination, [number, number]> };
export const defaultLayout = (): WorkspaceLayout => ({ version: 1, revision: 0, palette: 'ice', scale: 1, light: 1,
  snap: true, positions: Object.fromEntries(worldStations.map(s => [s.id, [s.position[0], s.position[2]]])) as WorkspaceLayout['positions'] });
const finite = (v: unknown, min: number, max: number): v is number => typeof v === 'number' && Number.isFinite(v) && v >= min && v <= max;
/** Import only known presentation fields. Never merge untrusted objects into app state. */
export function parseLayout(value: unknown): WorkspaceLayout | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const v = value as Record<string, unknown>, p = v.positions;
  if (v.version !== 1 || !finite(v.revision, 0, Number.MAX_SAFE_INTEGER) || !Number.isInteger(v.revision) ||
    !['ice','violet','mint'].includes(String(v.palette)) || !finite(v.scale, .7, 1.4) || !finite(v.light, .6, 1.5) ||
    typeof v.snap !== 'boolean' || !p || typeof p !== 'object' || Array.isArray(p)) return null;
  const positions = {} as WorkspaceLayout['positions'];
  for (const {id} of worldStations) {
    const pair = (p as Record<string, unknown>)[id];
    if (!Array.isArray(pair) || pair.length !== 2 || !pair.every(n => finite(n, -4, 4))) return null;
    positions[id] = [pair[0], pair[1]];
  }
  return {version:1, revision:v.revision, palette:v.palette as Palette, scale:v.scale, light:v.light, snap:v.snap, positions};
}
export function moveStation(layout: WorkspaceLayout, id: SpatialDestination, x: number, z: number): WorkspaceLayout {
  if (!Object.hasOwn(layout.positions, id) || !Number.isFinite(x) || !Number.isFinite(z)) return layout;
  const snap = (n: number) => Math.max(-4, Math.min(4, layout.snap ? Math.round(n * 4) / 4 : n));
  return {...layout, positions:{...layout.positions, [id]:[snap(x),snap(z)]}};
}
export function layoutKey(tenant: string, user: string) { return `ownstack:scene:v1:${encodeURIComponent(tenant)}:${encodeURIComponent(user)}`; }
