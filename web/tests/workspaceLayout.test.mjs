import test from 'node:test';
import assert from 'node:assert/strict';
import {defaultLayout,parseLayout,moveStation,layoutKey} from '../src/workspaceLayout.ts';
import {parseCommandPlan,layoutForPlan} from '../src/commandPlan.ts';

test('layouts round-trip with no shared mutable default positions',()=>{
  const a=defaultLayout(),b=defaultLayout();a.positions.access[0]=4;
  assert.notEqual(a.positions.access[0],b.positions.access[0]);assert.deepEqual(parseLayout(b),b);
  assert.notEqual(layoutKey('atlas','sam'),layoutKey('nova','sam'));
  assert.notEqual(layoutKey('atlas','sam'),layoutKey('atlas','taylor'));
});
test('import validation rejects malformed, huge and nonfinite layout fields',()=>{
  for(const value of [null,[],{}, {...defaultLayout(),scale:9},{...defaultLayout(),light:NaN},{...defaultLayout(),revision:.5},{...defaultLayout(),palette:'evil'},{...defaultLayout(),positions:{access:[0,0]}},{...defaultLayout(),snap:'yes'}])assert.equal(parseLayout(value),null);
});
test('drag clamps and snaps bounded coordinates without changing any authority',()=>{
  const a=defaultLayout(),b=moveStation(a,'access',200,-.42);
  assert.deepEqual(b.positions.access,[4,-.5]);assert.notDeepEqual(a.positions.access,b.positions.access);
  assert.equal(moveStation(a,'access',NaN,0),a);
  assert.deepEqual(moveStation({...a,snap:false},'access',.12,.37).positions.access,[.12,.37]);
});
test('untrusted command plans cannot introduce host effects or cross role navigation',()=>{
  for(const a of [{action:'deploy'},{action:'approve'},{action:'shell',command:'id'},{action:'navigate',target:'engineering'},{action:'move',target:'access',x:Infinity,z:0},{action:'draft',target:'feature',tenant_id:'nova'}])assert.equal(parseCommandPlan({actions:[a]},'member'),null);
  assert.equal(parseCommandPlan({actions:[{action:'refuse'},{action:'reset'}]},'admin'),null);
});
test('preview composes supported actions immutably and preserves its revision fence',()=>{
  const a=defaultLayout(),plan=parseCommandPlan({actions:[{action:'move',target:'access',x:-3,z:0},{action:'theme',target:'violet'}]},'admin');
  assert.ok(plan);const b=layoutForPlan(a,plan);assert.equal(b.palette,'violet');assert.equal(a.palette,'ice');assert.equal(b.revision,a.revision);assert.deepEqual(b.positions.access,[-3,0]);
});
