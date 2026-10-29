import json
import pytest
from ownstack.action_plans import validate_plan, validate_command_plan
from ownstack.planner_api import local_endpoint
from fastapi import HTTPException
from conftest import login

@pytest.mark.parametrize('action',[
    {'action':'move','target':'access','x':-3,'z':0},{'action':'navigate','target':'engineering'},
    {'action':'theme','target':'violet'},{'action':'draft','target':'feature'},
    {'action':'reset'},{'action':'clarify'},{'action':'refuse'},
])
def test_bounded_actions(action):
    assert validate_plan(json.dumps({'actions':[action]}),'admin').actions[0].action==action['action']

@pytest.mark.parametrize('action',[
    {'action':'approve'},{'action':'deploy'},{'action':'shell','command':'id'},
    {'action':'draft','target':'feature','tenant_id':'nova'},
    {'action':'navigate','target':'https://example.com'},
    {'action':'move','target':'access','x':float('nan'),'z':0},
    {'action':'move','target':'access','x':4.01,'z':0},
    {'action':'move','target':'access','x':True,'z':0},
    {'action':'theme','target':'url(javascript:alert(1))'},
])
def test_untrusted_model_fields_fail_closed(action):
    with pytest.raises(ValueError):validate_plan(json.dumps({'actions':[action]}),'admin')

@pytest.mark.parametrize('raw',['{}','{"actions":[]}','{"actions":[{"action":"reset","action":"deploy"}]}',
    '{"actions":[{"action":"reset"}],"actions":[{"action":"reset"}]}',
    json.dumps({'actions':[{'action':'reset'}]*5}),
    json.dumps({'actions':[{'action':'refuse'},{'action':'reset'}]}),
    json.dumps({'actions':[{'action':'draft','target':'access'},{'action':'draft','target':'feature'}]}),
    'x'*4097])
def test_ambiguous_or_oversized_plans(raw):
    with pytest.raises(ValueError):validate_plan(raw,'admin')

@pytest.mark.parametrize('role,target',[('member','engineering'),('contractor','access'),('product_owner','journey'),('unknown','convergence')])
def test_role_gate_is_independent_of_model(role,target):
    with pytest.raises(ValueError):validate_plan(json.dumps({'actions':[{'action':'navigate','target':target}]}),role)

@pytest.mark.parametrize('url',['https://example.com','http://169.254.169.254','http://localhost@evil.test','http://localhost/plan','http://localhost/?token=x',''])
def test_bridge_cannot_be_arbitrary_egress(monkeypatch,url):
    monkeypatch.setenv('OWNSTACK_TRAINED_PLANNER_URL',url)
    with pytest.raises(HTTPException):local_endpoint()

def test_bridge_is_local_only(monkeypatch):
    monkeypatch.setenv('OWNSTACK_TRAINED_PLANNER_URL','http://127.0.0.1:8811')
    assert local_endpoint()=='http://127.0.0.1:8811'
    monkeypatch.setenv('OWNSTACK_ENV','production')
    with pytest.raises(HTTPException):local_endpoint()

def test_no_checkpoint_has_no_fake_result(client,monkeypatch):
    monkeypatch.delenv('OWNSTACK_TRAINED_PLANNER_URL',raising=False)
    assert client.post('/v1/agent/planner',json={'text':'open access'}).status_code==401
    headers=login(client,'atlas-admin')
    assert client.post('/v1/agent/planner',headers=headers,json={'text':'open access'}).status_code==503


@pytest.mark.parametrize('command,action',[
    ('use violet',{'action':'theme','target':'violet'}),
    ('I prefer a silver scene',{'action':'theme','target':'ice'}),
    ('move access to the left',{'action':'move','target':'access','x':-3,'z':0}),
    ('restore the default scene arrangement',{'action':'reset'}),
])
def test_explicit_visual_mutations_survive_independent_grounding(command,action):
    assert validate_command_plan(json.dumps({'actions':[action]}),'admin',command).actions[0].action==action['action']


@pytest.mark.parametrize('command,action',[
    ('Explain recovery after a server clock error',{'action':'theme','target':'violet'}),
    ('use mint',{'action':'theme','target':'violet'}),
    ('move access left',{'action':'move','target':'access','x':3,'z':0}),
    ('move code left',{'action':'move','target':'access','x':-3,'z':0}),
    ('move access left or right',{'action':'move','target':'access','x':-3,'z':0}),
    ('open access',{'action':'move','target':'access','x':-3,'z':0}),
    ('reset the database',{'action':'reset'}),
])
def test_schema_valid_but_ungrounded_visual_mutations_are_rejected(command,action):
    raw=json.dumps({'actions':[action]})
    assert validate_plan(raw,'admin')
    with pytest.raises(ValueError):validate_command_plan(raw,'admin',command)


def test_authenticated_bridge_uses_grounding_before_returning_a_plan(client,monkeypatch):
    import httpx
    monkeypatch.setenv('OWNSTACK_TRAINED_PLANNER_URL','http://127.0.0.1:8812')
    class Companion:
        def __init__(self,*args,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,**kwargs):
            return httpx.Response(200,request=httpx.Request('POST',url),json={
                'output':'{"actions":[{"action":"theme","target":"violet"}]}',
                'artifact':'a'*64,'latency_ms':0})
    monkeypatch.setattr('ownstack.planner_api.httpx.Client',Companion)
    headers=login(client,'atlas-admin')
    denied=client.post('/v1/agent/planner',headers=headers,json={'text':'Explain a distributed clock fault'})
    assert denied.status_code==200
    assert denied.json()['plan']=={'actions':[{'action':'clarify'}]}
    assert denied.json()['resolution']=='intent_grounding'
    accepted=client.post('/v1/agent/planner',headers=headers,json={'text':'use violet'})
    assert accepted.status_code==200
    assert accepted.json()['effect']=='preview_only' and accepted.json()['provider_calls']==0
