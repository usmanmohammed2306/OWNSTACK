"""Approved customer regressions against a real, pinned Flask source tree.

This downstream consumer is a synthetic fixture, not a customer deployment.
Upstream issue tests and customer requirements are separate gates. Candidate
code never receives expected results or decides the final comparison verdict.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

from fastapi import HTTPException
from sqlalchemy import select, update

from ownstack.models import ChangeRequest, EngineeringItem
from ownstack.policy import digest
from ownstack.release_contracts import RequirementSpec
from ownstack.release_executor import (
    HTTP_CLIENT, READY_CLIENT, _json, _private_output, _stage,
    assess_observations, docker_command, requirements_digest,
)
from ownstack.repository_executor import ROOT, tree_digest
from ownstack.bounded_process import capture

PROFILE = 'flask-2.0-customer-visibility-v1'
CASE = 'pallets__flask-4160'
KEY = '_customer_release'

# Fixed downstream application. Its authorization logic is a fixture; the real
# candidate Flask implementation handles routing/request parsing/JSON responses.
SERVER = r'''
import sys
sys.path.insert(0,'/repo/src')
import flask
if flask.__file__!='/repo/src/flask/__init__.py':
    raise RuntimeError('Pinned repository import required')
from datetime import datetime
from flask import Flask,request,jsonify
app=Flask('ownstack-customer-consumer')
app.config['MAX_CONTENT_LENGTH']=16384
def moment(value):return datetime.fromisoformat(value.replace('Z','+00:00'))
@app.route('/health')
def health():return b'ready'
@app.route('/documents/<ident>',methods=['POST'])
def document(ident):
    d=request.get_json()
    if ident!=d['resource_id'] or d['actor_tenant_id']!=d['resource_tenant_id']:
        return jsonify({}),404
    if d['actor_role']=='contractor':
        grant=bool(d.get('grant_starts_at') and d.get('grant_expires_at') and not d.get('grant_revoked')
          and moment(d['grant_starts_at'])<=moment(d['at'])<moment(d['grant_expires_at']))
        if not d['assigned'] and not grant:return jsonify({}),403
        return jsonify(id=d['resource_id'],title='Synthetic project document')
    if d['actor_role'] in ('member','admin','engineer','manager'):
        return jsonify(id=d['resource_id'],title='Synthetic project document',internal_notes='Synthetic private notes')
    return jsonify({}),403
app.run(host='127.0.0.1',port=8765,debug=False,use_reloader=False)
'''


def _fingerprint():
    return digest({name: hashlib.sha256((ROOT/'src/ownstack'/name).read_bytes()).hexdigest()
        for name in ('repository_release.py','release_assurance.py','release_executor.py','release_contracts.py',
                     'repository_executor.py','repository_profiles.py','bounded_process.py','repository_registry.py','customers.py','customer_models.py')})


_LOADED = _fingerprint()


def fingerprint():
    if _fingerprint()!=_LOADED:raise ValueError('Repository release policy changed; restart operator and API')
    return _LOADED


def bound(item):
    return item.patch.get(KEY) if isinstance(item.patch,dict) else None


def current(db,item):
    """Fail closed when any approved coverage/authority changes, even after pass."""
    gate=bound(item)
    if gate is None:return None
    from ownstack.release_assurance import enabled,current_requirements,bundle_hash
    from ownstack.service import utcnow
    enabled()
    request=db.get(ChangeRequest,item.request_id)
    from ownstack.models import Project
    project=db.get(Project,request.project_id) if request else None
    if not project or project.tenant_id!=item.tenant_id or gate.get('project_id')!=project.id:
        raise HTTPException(409,'Release requirement project changed')
    try:
        rows=current_requirements(db,project,utcnow())
        specs=[value for _,value in rows]
        if (gate.get('profile')!=PROFILE or gate.get('policy_sha256')!=fingerprint()
                or gate.get('requirement_ids')!=[ident for ident,_ in rows]
                or gate.get('requirements_sha256')!=bundle_hash(specs)
                or gate.get('requirements')!=specs):
            raise ValueError('Approved release requirements changed; bind current coverage again')
    except (ValueError,TypeError,KeyError) as error:
        raise HTTPException(409,str(error)) from None
    return gate


def attach(db,item,principal,requirement_ids):
    from ownstack.release_assurance import enabled,current_requirements,bundle_hash
    from ownstack.repository_cockpit import binding,check_row,current_context
    from ownstack.service import record,utcnow
    from ownstack.team_scope import require_project
    enabled()
    # Serialize binding changes on the real row. JSON equality is not a portable
    # PostgreSQL JSON operator, and a stale in-memory payload is not a CAS fence.
    item=db.scalar(select(EngineeringItem).where(EngineeringItem.id==item.id,
        EngineeringItem.tenant_id==principal.tenant_id).with_for_update().execution_options(populate_existing=True))
    if item is None:raise HTTPException(404,'Not found')
    if binding(item)['case_id']!=CASE:
        raise HTTPException(422,'This downstream profile supports the pinned Flask Decimal case only')
    if item.human_decision or item.operation_id or item.status not in {'repository_bound','drafted','checks_failed','checks_passed'}:
        raise HTTPException(409,'Stop running work before changing release coverage')
    previous=check_row(db,item)
    if previous and previous.result.get('recovery_token') and not previous.result.get('lease_closed'):
        raise HTTPException(409,'Recovery must verify cleanup before changing coverage')
    # Validate repository provenance without consulting an old gate that might
    # need explicit rebinding after a requirement revision.
    saved=item.patch
    with db.no_autoflush:
        item.patch={k:v for k,v in saved.items() if k!=KEY}
        try:current_context(db,item)
        finally:item.patch=saved
    request=db.get(ChangeRequest,item.request_id)
    if not request.project_id:raise HTTPException(409,'A project-scoped request is required')
    project=require_project(db,principal,request.project_id)
    try:rows=current_requirements(db,project,utcnow())
    except ValueError as error:raise HTTPException(409,str(error)) from None
    if sorted(requirement_ids)!=[ident for ident,_ in rows] or len(set(requirement_ids))!=len(requirement_ids):
        raise HTTPException(409,'Bind every current approved requirement exactly once')
    specs=[value for _,value in rows]
    from ownstack.customers import request_customer
    from ownstack.customer_models import CustomerRequirementLink
    customer=request_customer(db,request,lock=True)
    if customer and not any((link:=db.get(CustomerRequirementLink,ident)) and link.customer_id==customer['customer_id'] for ident,_ in rows):
        raise HTTPException(409,'This customer needs an exact approved requirement before repository verification')
    gate={'profile':PROFILE,'project_id':project.id,'policy_sha256':fingerprint(),
          'requirement_ids':[ident for ident,_ in rows],'requirements':specs,'requirements_sha256':bundle_hash(specs)}
    if bound(item)==gate:return gate
    old_hash=digest(saved)
    payload={**deepcopy(saved),KEY:gate,'_verification_id':None}
    won=db.execute(update(EngineeringItem).where(EngineeringItem.id==item.id,
        EngineeringItem.tenant_id==principal.tenant_id,EngineeringItem.operation_id.is_(None),
        EngineeringItem.human_decision.is_(None),EngineeringItem.patch_hash==item.patch_hash,
        EngineeringItem.status==item.status)
        .values(patch=payload,status='drafted' if item.patch_hash else 'repository_bound')
        .execution_options(synchronize_session=False))
    if won.rowcount!=1:raise HTTPException(409,'Repository release context changed')
    record(db,item.tenant_id,item.request_id,'repository.release_requirements_bound',
           {'item_id':item.id,'requirements_sha256':gate['requirements_sha256'],'previous_context':old_hash,'actor_id':principal.user_id})
    db.expire(item)
    return gate


def command(name,image,tree):
    # Preserve every resource/isolation flag from the reviewed HTTP executor.
    args=docker_command(name,image,tree)
    return args[:-1]+['-c',SERVER]


def run(base,candidate,gate,output,*,image,expected_baseline,expected_candidate):
    if gate.get('profile')!=PROFILE or gate.get('policy_sha256')!=fingerprint():
        raise ValueError('Unsupported/stale downstream profile')
    if not re.fullmatch(r'sha256:[a-f0-9]{64}',image):raise ValueError('Pinned local image required')
    if os.environ.get('DOCKER_HOST') and not os.environ['DOCKER_HOST'].startswith('unix://'):
        raise ValueError('Remote Docker endpoint forbidden')
    context=capture(['docker','context','inspect','--format','{{json .Endpoints.docker.Host}}'],b'',timeout=10,limit=4096)
    if context['failure'] or context['exit_code']!=0 or not json.loads(context['stdout_bytes']).startswith('unix://'):
        raise ValueError('Verified local Docker context required')
    output=_private_output(output)
    for name,source,expected in (('baseline',base,expected_baseline),('candidate',candidate,expected_candidate)):
        if tree_digest(source)!=expected:raise ValueError('Repository tree changed before downstream execution')
        shutil.copytree(source,output/(name+'-source'))
        if tree_digest(output/(name+'-source'))!=expected:raise ValueError('Copied repository tree differs')
    specs=[RequirementSpec.model_validate(s) for s in gate['requirements']]
    rows=[{'requirement_key':s.key,'case_id':c.case_id,'input':c.input.model_dump(mode='json')} for s in specs for c in s.cases]
    if not 1<=len(rows)<=256:raise ValueError('Bounded customer case set required')
    phases={name:_stage(output/(name+'-source'),rows,output/name,image,timeout=60,command_factory=command)
            for name in ('baseline','candidate')}
    for name,expected in (('baseline',expected_baseline),('candidate',expected_candidate)):
        if tree_digest(output/(name+'-source'))!=expected:raise ValueError('Repository changed during downstream execution')
    result={'profile':PROFILE,'policy_sha256':fingerprint(),'image_id':image,
        'baseline_tree_sha256':expected_baseline,'candidate_tree_sha256':expected_candidate,
        'requirements_sha256':requirements_digest(specs),'binding_sha256':digest(gate),
        'oracle_sha256':hashlib.sha256((SERVER+HTTP_CLIENT+READY_CLIENT).encode()).hexdigest(),
        'provider_calls':0,'released':False,**phases,**assess_observations(specs,phases['baseline'],phases['candidate'])}
    _json(output/'report.json',result)
    return result


def validate(report,gate,source):
    if (not isinstance(report,dict) or len(json.dumps(report))>512000 or report.get('profile')!=PROFILE
        or report.get('policy_sha256')!=fingerprint() or report.get('binding_sha256')!=digest(gate)
        or report.get('requirements_sha256')!=requirements_digest(gate['requirements'])
        or report.get('oracle_sha256')!=hashlib.sha256((SERVER+HTTP_CLIENT+READY_CLIENT).encode()).hexdigest()
        or report.get('image_id')!=source.get('image_id')
        or not re.fullmatch(r'sha256:[a-f0-9]{64}',str(report.get('image_id','')))
        or any(report.get(key)!=source.get(key) or not re.fullmatch('[a-f0-9]{64}',str(report.get(key,'')))
               for key in ('baseline_tree_sha256','candidate_tree_sha256'))
        or type(report.get('provider_calls')) is not int or report['provider_calls']!=0 or report.get('released') is not False):
        raise ValueError('Customer evidence does not match the exact repository/requirements/policy')
    actual=assess_observations(gate['requirements'],report.get('baseline'),report.get('candidate'))
    if any(report.get(k)!=v for k,v in actual.items()):raise ValueError('Customer verdict differs from independent observations')
    return actual
