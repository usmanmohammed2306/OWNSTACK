/** A conditional schedule is diagnostic data, never an authorization capability. */
export type AccessForecast = {
  status: 'predicted_change' | 'no_scheduled_change' | 'unavailable';
  through: string; next_change: { at: string; allowed: boolean } | null; notice: string;
};

export function validAccessForecast(value: unknown, evaluatedAt: string, allowed: boolean): value is AccessForecast {
  if (!value || typeof value !== 'object') return false;
  const f = value as Partial<AccessForecast>;
  const start = Date.parse(evaluatedAt), end = typeof f.through === 'string' ? Date.parse(f.through) : NaN;
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start || typeof f.notice !== 'string') return false;
  if (f.status === 'no_scheduled_change' || f.status === 'unavailable') return f.next_change === null;
  if (f.status !== 'predicted_change' || !f.next_change || typeof f.next_change.at !== 'string'
      || typeof f.next_change.allowed !== 'boolean' || f.next_change.allowed === allowed) return false;
  const next = Date.parse(f.next_change.at);
  return Number.isFinite(next) && next > start && next <= end;
}
