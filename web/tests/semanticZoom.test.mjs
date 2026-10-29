import test from 'node:test';import assert from 'node:assert/strict';
import {semanticZoom} from '../src/semanticZoom.ts';
test('zoom out ascends people to roles to the workspace, retaining distinct levels',()=>{
  let s={zoom:2.15,station:'demo',parent:'role:contractor'};
  for(let i=0;i<8&&s.parent;i++)s=semanticZoom(s,-.15);
  assert.equal(s.parent,null);assert.equal(s.station,'demo');
  for(let i=0;i<10&&s.station;i++)s=semanticZoom(s,-.15);
  assert.equal(s.station,null);assert.equal(s.zoom,1.05);
});
test('zoom entry follows the selected station with hysteresis and finite bounds',()=>{
  let s={zoom:1,station:null,parent:null};s=semanticZoom(s,.15,'engineering');assert.equal(s.station,null);
  s=semanticZoom(s,.15,'engineering');assert.equal(s.station,'engineering');
  assert.equal(semanticZoom(s,-.15).station,'engineering');
  for(let i=0;i<100;i++)s=semanticZoom(s,-.25);assert.equal(s.zoom,.65);assert.equal(s.station,null);
  assert.deepEqual(semanticZoom(s,NaN),s);
});
