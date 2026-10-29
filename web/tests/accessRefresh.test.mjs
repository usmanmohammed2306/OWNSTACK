import test from 'node:test';
import assert from 'node:assert/strict';
import {accessRefreshDelay} from '../src/accessRefresh.ts';
test('access preview schedules the earliest grant expiry using server time',()=>{
 const snapshot={as_of:'2026-10-28T12:00:00Z',rules:[{expires_at:'2026-10-28T12:00:08Z'},{expires_at:'2026-10-28T12:00:03Z'}]};
 assert.equal(accessRefreshDelay(snapshot),3000);
});
test('malformed, expired and permanent rules never cause a tight polling loop',()=>{
 assert.equal(accessRefreshDelay({as_of:'2026-10-28T12:00:00Z',rules:[{expires_at:null},{expires_at:'bad'},{expires_at:'2026-10-28T11:59:59Z'}]}),15000);
 assert.equal(accessRefreshDelay({as_of:'bad',rules:[]}),1000);
 assert.equal(accessRefreshDelay({as_of:'2026-10-28T12:00:00Z',rules:[{expires_at:'2026-10-28T12:00:00.001Z'}]}),100);
});
