import test from 'node:test';
import assert from 'node:assert/strict';
import {customerRequirementDraft} from '../src/customerRequirementDraft.ts';
const input={key:'contractor-document-access',title:'Project read',reference:'CUSTOMER-42',version:1,tenant:'atlas',controlTenant:'nova',owner:'atlas-engineer',fields:'id, title',at:'2026-10-27T12:00:00Z'};
test('guided draft includes both positive and negative customer controls without granting access',()=>{
  const value=customerRequirementDraft(input);
  assert.equal(value.cases.length,3);
  assert.deepEqual(value.cases.map(c=>c.expected.status_code),[403,200,404]);
  assert.equal(value.cases[2].input.actor_tenant_id,'atlas');assert.equal(value.cases[2].input.resource_tenant_id,'nova');
  assert.equal(value.owner_id,'atlas-engineer');assert.equal(value.schema_version,1);assert.equal(value.approved,undefined);
});
for(const patch of [{tenant:'../atlas'},{controlTenant:'atlas'},{fields:'id,id'},{fields:'__private'},{fields:''},{reference:''},{version:0},{at:'next Friday'}]) {
  test('ambiguous guided requirement is refused '+JSON.stringify(patch),()=>assert.throws(()=>customerRequirementDraft({...input,...patch})));
}
