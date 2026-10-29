import test from 'node:test';
import assert from 'node:assert/strict';
import { springStep } from '../src/spatialMotion.ts';

test('the decorative spring converges and stops instead of scheduling perpetual animation', () => {
  let state={position:.75,velocity:0,settled:false};
  for(let i=0;i<400 && !state.settled;i++) state=springStep(state.position,state.velocity,1,1/60);
  assert.deepEqual(state,{position:1,velocity:0,settled:true});
});
test('large frame gaps are clamped and invalid physics inputs do not contaminate transforms', () => {
  assert.deepEqual(springStep(0,0,1,1000),springStep(0,0,1,1/30));
  assert.deepEqual(springStep(0,0,1,-10),{position:0,velocity:0,settled:false});
  for(const value of [NaN,Infinity,-Infinity]) assert.deepEqual(springStep(value,0,1,1/60),{position:0,velocity:0,settled:true});
});
