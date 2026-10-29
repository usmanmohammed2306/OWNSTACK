import test from 'node:test';
import assert from 'node:assert/strict';
import {parseSavedCommand,commandStateMessage} from '../src/plannerState.ts';
test('recovery stores an opaque key and generation, never a model answer or identity authority',()=>{
  const key='d91f70c2-ab43-4000-8000-123456789012';
  assert.deepEqual(parseSavedCommand(JSON.stringify({key,generation:2})),{key,generation:2});
  for(const value of [{key,generation:0},{key,generation:4},{key,generation:true},{key:'../secret',generation:1},
      {key,generation:1,plan:{action:'approve'}},null,[]])assert.equal(parseSavedCommand(JSON.stringify(value)),null);
  assert.equal(parseSavedCommand('x'.repeat(201)),null);
});
test('failure messages distinguish a saved result from remote cancellation',()=>{
  assert.match(commandStateMessage({status:'timed_out'}),/late result cannot be applied/);
  assert.match(commandStateMessage({status:'cancelled'}),/not verified/);
  assert.match(commandStateMessage({status:'identity_changed'}),/Start a new command/);
});
