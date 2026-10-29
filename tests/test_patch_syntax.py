"""Reject malformed generated Python without executing or repairing its text.

Provider calls here are explicit doubles. Syntax validity is not PDF correctness
or a security verdict; independent verification still controls acceptance.
"""
import json
import httpx
import pytest
from sqlalchemy import select
from conftest import login
from test_ai import FakeResponse,live_settings
from ownstack.patch_agent import propose_patch,fixture_patch
from ownstack.models import Event,InferenceBudget


@pytest.mark.parametrize('replacement',[
    'def export_pdf(project, rows):\\n    return b"pdf"',
    'def export_pdf(project, rows):\n    return bytes()))\n',
    'def export_pdf(project, rows):\nreturn b"pdf"\n',
    'def export_pdf(project, rows):\n    return b"pdf"\x00\n',
])
def test_malformed_provider_source_is_rejected_once_without_normalization(monkeypatch,replacement):
    calls=[]
    def provider(*args,**kwargs):
        calls.append(1)
        return FakeResponse({'choices':[{'finish_reason':'stop','message':{
            'content':json.dumps({'lines':replacement.split('\n')})}}]})
    monkeypatch.setattr(httpx,'post',provider)
    with pytest.raises(ValueError,match='MODEL_SOURCE_(SYNTAX|PROTOCOL)_INVALID'):
        propose_patch('Add PDF export',live_settings())
    assert calls==[1]


def test_syntax_gate_preserves_literal_escapes_and_never_executes_source(monkeypatch,tmp_path):
    marker=tmp_path/'must-not-exist'
    replacement=f'open({str(marker)!r}, "w").write("candidate execution is forbidden here")\n'+'def export_pdf(project, rows):\n    return b"literal\\n"\n'
    monkeypatch.setattr(httpx,'post',lambda *a,**kw:FakeResponse({'choices':[{'message':{
        'content':json.dumps({'lines':replacement.removesuffix('\n').split('\n')})}}]}))
    patch,_,_=propose_patch('Add PDF export',live_settings())
    assert patch['edits'][0]['new']==replacement and not marker.exists()


def test_bad_syntax_http_failure_retains_manual_recovery_without_inference(
        client,fixture_db,monkeypatch):
    from ownstack import api
    from ownstack.runner import trusted_local_verification
    h=login(client,'atlas-engineer')
    created=client.post('/v1/requests',headers={**h,'Idempotency-Key':'bad-syntax-request'},json={
        'kind':'feature','project_id':'atlas-project','text':'Add PDF export.'})
    assert created.status_code==201
    ident=created.json()['id']
    assert client.post('/v1/requests/'+ident+'/manual-handoff',headers={**h,'Idempotency-Key':'bad-syntax-handoff'}).status_code==200
    iid=next(r['id'] for r in client.get('/v1/engineering',headers=h).json() if r['request_id']==ident)
    calls=[]
    def provider(*args,**kwargs):
        calls.append(1)
        return FakeResponse({'choices':[{'message':{'content':json.dumps({'lines':['def invalid(:']})}}]})
    monkeypatch.setattr(httpx,'post',provider)
    monkeypatch.setattr(api,'propose_patch',lambda *a,**kw:propose_patch('Add PDF export',live_settings()))
    result=client.post('/v1/engineering/'+iid+'/draft',headers=h)
    assert result.status_code==502 and len(calls)==1
    saved=client.get('/v1/engineering/'+iid,headers=h).json()
    assert saved['status']=='draft_failed' and saved['patch'] is None
    with fixture_db() as db:
        events=db.scalars(select(Event).where(Event.request_id==ident)).all()
        assert any(e.event_type=='engineering.draft_failed' and e.payload.get('error_code')=='MODEL_SOURCE_SYNTAX_INVALID' for e in events)
        assert db.get(InferenceBudget,'global').reserved_calls==0
    assert client.post('/v1/engineering/'+iid+'/manual-patch',headers=h,json={'patch':fixture_patch()}).status_code==200
    monkeypatch.setattr(api,'run_verifier',trusted_local_verification)
    assert client.post('/v1/engineering/'+iid+'/verify',headers=h).json()['passed']
    current=client.get('/v1/engineering/'+iid,headers=h).json()
    assert client.post('/v1/engineering/'+iid+'/decide',headers=h,json={
        'decision':'accept_for_manual_release','patch_hash':current['patch_hash']}).status_code==200
    assert client.get('/v1/engineering/'+iid+'/artifact',headers=h).json()['release_state']=='not_deployed'
    assert len(calls)==1
