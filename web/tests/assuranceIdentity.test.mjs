import assert from 'node:assert/strict';
import { test } from 'node:test';
const { matchesReport, validReportCatalogue } = await import(process.env.OWNSTACK_ASSURANCE_MODULE || '../src/assuranceIdentity.ts');
const spec = { key: 'approval-inbox', title: 'Inbox', description: 'Diagnostic', filters: ['project_id'], required: [] };
const sample = { report: 'approval-inbox', tenant_id: 'atlas', scope: { project_id: 'atlas-project' },
  evaluated_at: '2026-10-23T12:00:00Z', items: [{ id: 'request' }], truncated: false, notice: 'Not permission', source_limit: 25, window_days: 7 };
test('catalogue permits supported scope only and rejects duplicate report identities', () => {
  assert.equal(validReportCatalogue([spec]), true);
  for (const value of [null, [spec, spec], [{ ...spec, filters: ['arbitrary_sql'] }], [{ ...spec, required: ['request_id'] }], [null], [{ ...spec, key: '../escape' }]])
    assert.equal(validReportCatalogue(value), false);
});
test('snapshot must match exact tenant, report and form scope', () => {
  assert.equal(matchesReport(sample, 'atlas', 'approval-inbox', sample.scope), true);
  assert.equal(matchesReport(sample, 'nova', 'approval-inbox', sample.scope), false);
  assert.equal(matchesReport(sample, 'atlas', 'other', sample.scope), false);
  assert.equal(matchesReport(sample, 'atlas', 'approval-inbox', {}), false);
});
test('rejects malformed records, clocks and limits before table rendering', () => {
  for (const value of [null, {}, { ...sample, items: [null] }, { ...sample, items: [[]] },
    { ...sample, items: Array(101).fill({}) }, { ...sample, evaluated_at: 'bad' }, { ...sample, scope: null },
    { ...sample, truncated: 'false' }, { ...sample, source_limit: 101 }, { ...sample, window_days: 0 }])
    assert.equal(matchesReport(value, 'atlas', 'approval-inbox', sample.scope), false);
});
