"""HTTP transport doubles, never live model or submission proof."""
import json
import httpx
import pytest
from ownstack.config import Settings
from ownstack.change_agent_model import decide,propose_patch

@pytest.fixture
def model_transport(monkeypatch):
    original=httpx.Client;captured=[];reply={'action':'ask','field':'roles','reason':'Allowed roles are not specified.','citations':['request']}
    envelope={'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':json.dumps(reply)}}],
        'usage':{'prompt_tokens':12,'completion_tokens':8},'model':'nvidia/test-nemotron-double'}
    def respond(request):captured.append(json.loads(request.content));return httpx.Response(200,json=envelope)
    monkeypatch.setattr(httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(respond),trust_env=False))
    settings=Settings(ai_mode='nebius',environment='local',max_live_calls=40,nebius_key='offline-placeholder',nebius_model='nvidia/test-nemotron-double',nebius_patch_model='')
    return settings,envelope,captured

def test_decision_payload_and_usage_are_bounded_and_typed(model_transport):
    settings,envelope,calls=model_transport
    result,usage=decide({'answers':{},'notes':[]},{'policy.py':'pass'},'Customer needs a change',settings)
    assert result['action']=='ask' and result['field']=='roles' and usage['input_tokens']==12
    assert len(calls)==1 and calls[0]['response_format']=={'type':'json_object'}
    assert 'Never' in calls[0]['messages'][0]['content']

@pytest.mark.parametrize('mode',['length','tools','invented-citation','unknown-action','invented-fact'])
def test_invalid_decisions_are_rejected_without_authorization(model_transport,mode):
    settings,envelope,calls=model_transport;message=envelope['choices'][0]['message']
    if mode=='length':envelope['choices'][0]['finish_reason']='length'
    elif mode=='tools':message['tool_calls']=[{'function':{'name':'approve'}}]
    else:
        content=json.loads(message['content'])
        if mode=='invented-citation':content['citations']=['/etc/passwd']
        if mode=='unknown-action':content['action']='deploy'
        if mode=='invented-fact':content.update(action='suggest_answers',field=None,facts={'roles':['admin']},quotes=[{'field':'roles','source':'request','quote':'admin permission approved'}])
        message['content']=json.dumps(content)
    with pytest.raises(ValueError):decide({'answers':{},'notes':[]},{'policy.py':'pass'},'Customer needs a change',settings)
    assert len(calls)==1

def test_repository_patch_response_contains_edits_only(model_transport):
    settings,envelope,calls=model_transport
    envelope['choices'][0]['message']['content']=json.dumps({'files':[{'path':'policy.py','lines':['def visible():','    return False']}]})
    patch,usage=propose_patch({'editable_files':{'policy.py':'def visible():\n    return True\n'},'counterexample':{'status':403}},settings)
    assert patch['edits'][0]['new']=='def visible():\n    return False\n' and usage['output_tokens']==8
    envelope['choices'][0]['message']['content']=json.dumps({**patch,'command':'touch anything'})
    with pytest.raises(ValueError):propose_patch({'editable_files':{}},settings)

def test_patch_prompt_preserves_observed_allowed_response_mappings(model_transport):
    settings,envelope,calls=model_transport
    envelope['choices'][0]['message']['content']=json.dumps({'files':[{'path':'policy.py','lines':['pass']}]})
    witness={'input':{'resource_id':'doc'},'expected':{'status_code':200,'visible_fields':['id','title']}}
    propose_patch({'editable_files':{'policy.py':'x=1\n'},'preservation_witnesses':[witness]},settings)
    payload=json.loads(calls[0]['messages'][1]['content'])
    assert payload['preservation_witnesses']==[witness]
    assert 'output keys' in calls[0]['messages'][0]['content']
    assert 'field mappings and values' in calls[0]['messages'][0]['content']

@pytest.mark.parametrize('mode',['off','fixture'])
def test_no_implicit_fixture_or_offline_network_dispatch(model_transport,mode):
    settings,envelope,calls=model_transport
    from dataclasses import replace
    settings=replace(settings,ai_mode=mode)
    with pytest.raises(RuntimeError):decide({'answers':{},'notes':[]},{},'Request',settings)
    with pytest.raises(RuntimeError):propose_patch({},settings)
    assert calls==[]
