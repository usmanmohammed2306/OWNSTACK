import assert from 'node:assert/strict';
import { test } from 'node:test';
const base = process.env.OWNSTACK_FORECAST_MODULE || '../src/accessForecast.ts';
const { validAccessForecast } = await import(base);
const at = '2026-10-23T12:00:00+00:00';
const valid = { status: 'predicted_change', through: '2026-10-30T12:00:00+00:00',
  next_change: { at: '2026-10-24T12:00:00+00:00', allowed: false }, notice: 'Conditional forecast' };

test('accepts a future opposite decision, including exactly at horizon', () => {
  assert.equal(validAccessForecast(valid, at, true), true);
  assert.equal(validAccessForecast({ ...valid, next_change: { ...valid.next_change, at: valid.through } }, at, true), true);
});
test('accepts explicit unavailable/no-change only without a fabricated transition', () => {
  for (const status of ['unavailable', 'no_scheduled_change']) {
    assert.equal(validAccessForecast({ ...valid, status, next_change: null }, at, true), true);
    assert.equal(validAccessForecast({ ...valid, status }, at, true), false);
  }
});
test('rejects malformed timestamps, contradictory decisions and wrong shapes', () => {
  for (const value of [null, false, {}, { ...valid, status: 'permanent' }, { ...valid, notice: null },
    { ...valid, through: 'invalid' }, { ...valid, through: at }, { ...valid, next_change: null },
    ...[at, '2026-10-22T12:00:00Z', '2026-10-31T12:00:00Z', 'bad'].map(time => ({ ...valid, next_change: { at: time, allowed: false } })),
    { ...valid, next_change: { ...valid.next_change, allowed: true } },
    { ...valid, next_change: { ...valid.next_change, allowed: 'false' } }]) {
    assert.equal(validAccessForecast(value, at, true), false, JSON.stringify(value));
  }
  assert.equal(validAccessForecast(valid, 'bad', true), false);
});
