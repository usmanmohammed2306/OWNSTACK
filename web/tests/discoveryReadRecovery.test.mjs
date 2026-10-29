import test from 'node:test';
import assert from 'node:assert/strict';
import {forgetDiscoveryAfter} from '../src/discoveryReadRecovery.ts';
test('temporary network and service failures retain saved evidence for read-only recovery',()=>{
 for(const error of [new TypeError('Failed to fetch'),new Error('Deadline exceeded'),null,{status:429},{status:500},{status:503}])assert.equal(forgetDiscoveryAfter(error),false);
});
test('lost authentication or object authority forgets the private discovery',()=>{
 for(const status of [401,403,404])assert.equal(forgetDiscoveryAfter({status}),true);
});
