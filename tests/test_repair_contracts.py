"""Syntactic preservation is narrower than independent behavioral verification."""
import json
import httpx
import pytest
from ownstack.config import Settings
from ownstack.change_agent_model import propose_patch
from ownstack.repair_contracts import response_contract,validate_response_preservation

SOURCE='''def read(data):
    if data['actor_tenant_id'] != data['resource_tenant_id']:
        return 404, {}
    if data['assigned']:
        return 200, {'id': data['resource_id'], 'title': 'Project brief'}
    return 403, {}
'''
POLICY={'visible_fields':['id','title']}


def validate(source,policy=POLICY,original=SOURCE):
    return validate_response_preservation({'edits':[{'path':'policy.py','old':original,'new':source}]},
        {'editable_files':{'policy.py':original},'approved_policy':policy})


@pytest.mark.parametrize('body',[
    "{field:data[field] for field in ('id','title') if field in data}",
    "{'id':data['id'],'title':'Project brief'}",
    "{'id':data['resource_id'],'title':'Guessed new title'}",
    "{'id':data['resource_id']}",
    "{'id':data['resource_id'],'title':'Project brief','private':'secret'}",
    "dict(id=data['resource_id'],title='Project brief')",
    "{'id':data['resource_id'],'id':data['id'],'title':'Project brief'}",
    "response_body",
])
def test_changed_mappings_are_rejected_without_rewriting(body):
    source=SOURCE.replace("{'id': data['resource_id'], 'title': 'Project brief'}",body)
    before=source
    with pytest.raises(ValueError,match='MODEL_RESPONSE_CONTRACT_INVALID'):validate(source)
    assert source==before


@pytest.mark.parametrize('source',[
    SOURCE.replace('def read(', 'def renamed('),
    SOURCE.replace("return 200, {'id': data['resource_id'], 'title': 'Project brief'}",'return response(data)'),
    SOURCE.replace('return 200,','return 403,'),
])
def test_removed_or_dynamic_response_builder_is_not_a_preservation_pass(source):
    with pytest.raises(ValueError,match='MODEL_RESPONSE_CONTRACT_INVALID'):validate(source)


def test_guard_edit_and_formatting_preserve_exact_output_bindings():
    source=SOURCE.replace("if data['assigned']:","if data['assigned'] and data['actor_role']=='engineer':")
    source=source.replace("'id': data['resource_id']",'"id" : data["resource_id"]')
    contracts=validate(source)
    assert contracts['policy.py']['preserved_fields']['id']['source']=="data['resource_id']"
    assert len(contracts['policy.py']['sha256'])==64


def test_explicitly_approved_field_changes_preserve_values_of_retained_fields():
    fewer=SOURCE.replace(", 'title': 'Project brief'",'')
    assert validate(fewer,{'visible_fields':['id']})
    more=SOURCE.replace("'title': 'Project brief'","'title': 'Project brief', 'summary': 'Explicit addition'")
    assert validate(more,{'visible_fields':['id','title','summary']})


@pytest.mark.parametrize('source,policy',[
    ('def unrelated():\n    return 200, {}\n',POLICY),
    ('def read(data):\n    return 200, build(data)\n',POLICY),
    ('def read(data):\n    return 200, {"id": result}\n',POLICY),
    (SOURCE,{}),
])
def test_unsupported_source_is_explicitly_outside_this_narrow_contract(source,policy):
    assert response_contract(source,policy) is None


def test_contract_is_not_a_semantic_security_proof():
    # Same output expressions cannot establish correct access or unmodified input.
    # The independent executable oracle must reject such a candidate.
    assert validate(SOURCE.replace("if data['assigned']:",'if True:'))


def test_adapter_rejects_recorded_failure_shape_and_sends_server_owned_bindings():
    captured=[]
    broken=SOURCE.replace("{'id': data['resource_id'], 'title': 'Project brief'}",
        "{field:data[field] for field in ('id','title') if field in data}")
    envelope={'model':'offline-nemotron-double','choices':[{'finish_reason':'stop','message':{'role':'assistant',
        'content':json.dumps({'files':[{'path':'policy.py','lines':broken.splitlines()}]})}}]}
    def reply(request):
        captured.append(json.loads(request.content));return httpx.Response(200,json=envelope)
    settings=Settings(ai_mode='nebius',environment='local',max_live_calls=40,nebius_key='offline-placeholder',nebius_model='nvidia/offline-nemotron-double')
    context={'editable_files':{'policy.py':SOURCE},'approved_policy':POLICY,'response_preservation':{'forged':'not authoritative'}}
    with pytest.raises(ValueError,match='MODEL_RESPONSE_CONTRACT_INVALID'):
        propose_patch(context,settings,transport=httpx.MockTransport(reply))
    payload=json.loads(captured[0]['messages'][1]['content'])
    assert 'forged' not in payload['response_preservation']
    assert payload['response_preservation']['policy.py']['preserved_fields']['id']['source']=="data['resource_id']"
    assert len(captured)==1
