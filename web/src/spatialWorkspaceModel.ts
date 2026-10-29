/** Spatial navigation is scoped presentation, never authorization or tenant switching. */
export type SpatialDestination = 'demo' | 'journey' | 'access' | 'engineering' | 'convergence';
export const worldStations: { id: SpatialDestination; label: string; position: [number, number, number] }[] = [
  { id: 'demo', label: 'OwnStack', position: [0, .6, 0] },
  { id: 'journey', label: 'Requests', position: [-2.65, .8, 1.35] },
  { id: 'access', label: 'Access', position: [2.6, .4, 1.35] },
  { id: 'engineering', label: 'Code', position: [2.5, .55, -2.2] },
  { id: 'convergence', label: 'Patterns', position: [-2.5, .45, -2.2] },
];
export function allowedStations(role: string): SpatialDestination[] {
  if (role === 'product_owner') return ['demo', 'convergence'];
  if (role === 'contractor') return ['demo', 'journey'];
  if (role === 'member') return ['demo', 'journey', 'access'];
  if (role === 'admin' || role === 'engineer'||role==='manager') return ['demo', 'journey', 'access', 'engineering', 'convergence'];
  return ['demo'];
}
export function scopedDestination(id: string, role: string): SpatialDestination | null {
  return allowedStations(role).includes(id as SpatialDestination) ? id as SpatialDestination : null;
}

/** Three entry points. Nested access/pattern capabilities retain their existing
 * role checks; simplifying navigation never widens server authority. */
export function homeStations(role:string):SpatialDestination[]{
  return allowedStations(role).filter(id=>id!=='access'&&(id!=='convergence'||role==='product_owner'));
}
export function stationLabel(id:SpatialDestination){return id==='demo'?'Organization':id==='engineering'?'Code review':id==='convergence'?'Requests':id==='journey'?'Requests':'Access';}

/** Empty predefined categories are not evidence of a customer's repeated need. */
export function observedNeedCount(role: string, rows: {your_tenant_request_count: number; affected_tenant_count: number | null}[]): number {
  return rows.filter(row => (role === 'product_owner' ? row.affected_tenant_count || 0 : row.your_tenant_request_count) > 0).length;
}
