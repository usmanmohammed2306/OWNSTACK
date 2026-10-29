import test from 'node:test';
import assert from 'node:assert/strict';
import { allowedStations, homeStations, stationLabel, observedNeedCount, scopedDestination, worldStations } from '../src/spatialWorkspaceModel.ts';

test('spatial destinations match the supported roles without inventing a tenant switch', () => {
  assert.deepEqual(allowedStations('member'), ['demo', 'journey', 'access']);
  assert.deepEqual(allowedStations('contractor'), ['demo', 'journey']);
  assert.deepEqual(allowedStations('product_owner'), ['demo', 'convergence']);
  for (const role of ['admin', 'engineer','manager']) assert.deepEqual(allowedStations(role), worldStations.map(s => s.id));
  for (const role of ['', 'guest', 'administrator']) assert.deepEqual(allowedStations(role), ['demo']);
});
test('stale or forged spatial picks do not enter a disallowed destination', () => {
  for (const id of ['engineering', 'convergence', 'people', 'nova', 'https://example.com', '__proto__']) {
    assert.equal(scopedDestination(id, 'member'), null);
  }
  assert.equal(scopedDestination('engineering', 'engineer'), 'engineering');
  assert.equal(scopedDestination('journey', 'contractor'), 'journey');
  assert.equal(scopedDestination('access', 'contractor'), null);
});
test('every physical station has a unique finite position and a native navigation label', () => {
  assert.equal(new Set(worldStations.map(s => s.id)).size, 5);
  assert.equal(new Set(worldStations.map(s => s.position.join(','))).size, 5);
  for (const station of worldStations) {
    assert.ok(station.label.trim());
    assert.ok(station.position.length === 3 && station.position.every(Number.isFinite));
  }
});

test('a new workspace has no observed needs just because predefined categories exist', () => {
  const rows=[{your_tenant_request_count:0,affected_tenant_count:null},{your_tenant_request_count:0,affected_tenant_count:null}];
  assert.equal(observedNeedCount('admin',rows),0);
  assert.equal(observedNeedCount('member',rows),0);
  assert.equal(observedNeedCount('admin',[{your_tenant_request_count:1,affected_tenant_count:null},rows[0]]),1);
});
test('only the product-owner presentation uses the supplied cross-workspace aggregates', () => {
  const rows=[{your_tenant_request_count:0,affected_tenant_count:2},{your_tenant_request_count:0,affected_tenant_count:0}];
  assert.equal(observedNeedCount('product_owner',rows),1);
  assert.equal(observedNeedCount('admin',rows),0);
});
test('the three home entries nest access and patterns without widening role scope',()=>{
  assert.deepEqual(homeStations('engineer'),['demo','journey','engineering']);
  assert.deepEqual(homeStations('member'),['demo','journey']);
  assert.deepEqual(homeStations('product_owner'),['demo','convergence']);
  for(const role of ['engineer','manager','member','contractor','product_owner'])for(const id of homeStations(role))assert.ok(allowedStations(role).includes(id));
  assert.equal(stationLabel('demo'),'Organization');assert.equal(stationLabel('engineering'),'Code review');
});
