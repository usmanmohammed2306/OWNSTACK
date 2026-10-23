export type ReportSpec = { key: string; title: string; description: string; filters: string[]; required: string[] };
export type ReportSnapshot = { report: string; tenant_id: string; scope: Record<string, string>; evaluated_at: string;
  items: Record<string, unknown>[]; truncated: boolean; notice: string; source_limit: number; window_days: number };
const fields = ['project_id', 'viewer_id', 'request_id'];

export function validReportCatalogue(value: unknown): value is ReportSpec[] {
  if (!Array.isArray(value)) return false;
  return value.every(s => s && /^[a-z0-9-]{1,80}$/.test(s.key) && typeof s.title === 'string'
    && typeof s.description === 'string' && Array.isArray(s.filters) && Array.isArray(s.required)
    && s.filters.every((key: unknown) => typeof key === 'string' && fields.includes(key))
    && s.required.every((key: unknown) => s.filters.includes(key)))
    && new Set(value.map(s => s.key)).size === value.length;
}

/** This validates response identity and shape, not report correctness or authenticity. */
export function matchesReport(value: unknown, tenant: string, key: string, scope: Record<string, string>): value is ReportSnapshot {
  if (!value || typeof value !== 'object') return false;
  const r = value as Partial<ReportSnapshot>;
  return r.tenant_id === tenant && r.report === key && Array.isArray(r.items) && r.items.length <= 100
    && r.items.every(item => item && typeof item === 'object' && !Array.isArray(item))
    && typeof r.notice === 'string' && typeof r.truncated === 'boolean'
    && typeof r.evaluated_at === 'string' && Number.isFinite(Date.parse(r.evaluated_at))
    && !!r.scope && typeof r.scope === 'object' && !Array.isArray(r.scope)
    && JSON.stringify(Object.entries(r.scope).sort()) === JSON.stringify(Object.entries(scope).sort())
    && Number.isInteger(r.source_limit) && r.source_limit! >= 1 && r.source_limit! <= 100
    && Number.isInteger(r.window_days) && r.window_days! >= 1 && r.window_days! <= 30;
}
