/** Authored template, never model output, approval or a grant. */
export function customerRequirementDraft(input:{key:string;title:string;reference:string;version:number;tenant:string;controlTenant:string;owner:string;fields:string;at:string}) {
  const identifier=/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$/;
  for(const value of [input.key,input.tenant,input.controlTenant,input.owner])if(!identifier.test(value))throw new Error('Use a valid customer, owner and requirement key.');
  if(input.key.length>80||input.tenant===input.controlTenant)throw new Error('Use a distinct control customer and a short requirement key.');
  if(!input.title.trim()||!input.reference.trim())throw new Error('Add a title and customer request reference.');
  const fields=input.fields.split(',').map(s=>s.trim()).filter(Boolean);
  if(!fields.length||fields.length>64||new Set(fields).size!==fields.length||fields.some(s=>!/^[A-Za-z_][A-Za-z0-9_]{0,63}$/.test(s)||s.startsWith('__')))throw new Error('List distinct public response field names.');
  if(!Number.isInteger(input.version)||input.version<1||!Number.isFinite(Date.parse(input.at))||!/(Z|[+-]\d{2}:\d{2})$/.test(input.at))throw new Error('Use a valid version and timezone-aware test time.');
  const context={actor_id:`${input.tenant}-contractor`,actor_tenant_id:input.tenant,actor_role:'contractor',resource_id:`${input.tenant}-document`,resource_tenant_id:input.tenant,assigned:false,at:input.at,grant_starts_at:null,grant_expires_at:null,grant_revoked:false};
  return {schema_version:1,key:input.key,version:input.version,customer_tenant_id:input.tenant,title:input.title.trim(),source_ref:input.reference.trim(),owner_id:input.owner,expires_at:null,cases:[
    {case_id:'contractor-denied',title:'No assignment, no access',kind:'target',input:context,expected:{status_code:403,visible_fields:[]}},
    {case_id:'contractor-allowed',title:'Assigned contractor can read',kind:'target',input:{...context,assigned:true},expected:{status_code:200,visible_fields:fields}},
    {case_id:'other-customer-denied',title:'Another customer stays private',kind:'control',input:{...context,resource_id:`${input.controlTenant}-document`,resource_tenant_id:input.controlTenant,assigned:true},expected:{status_code:404,visible_fields:[]}},
  ]};
}
