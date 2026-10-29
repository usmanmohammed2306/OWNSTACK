"""Local Cockpit repository jobs. The API queues; a separate operator runs Docker.

Existing tenant-scoped engineering/evidence/event records retain attempts. No new
inference authority, model call, API Docker socket or automatic release is added.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
import difflib
import json
import os
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ownstack.auth import current_principal, db_session, require_role
from ownstack.config import Settings
from ownstack.models import ChangeRequest, EngineeringItem, Evidence, User
from ownstack.policy import Principal, aware, digest
from ownstack.repository_executor import ROOT, PROFILE, canonical, digest as bytes_digest, execution_fingerprint
from ownstack.repository_profiles import PROFILES, CASE_PROFILES, EXAMPLES, by_id, SUPPLEMENT, supplemental_cases
from ownstack.service import record, scoped, utcnow

router = APIRouter(prefix='/v1', tags=['local repository review'])
CASES = tuple(CASE_PROFILES)
LIMITATION = 'Selected upstream tests in a local container. A pass is not security certification, a release, or Nemotron coding performance.'


def require_enabled():
    if Settings().environment != 'local' or os.getenv('OWNSTACK_REPOSITORY_COCKPIT') != 'true':
        raise HTTPException(404, 'Local repository review is not enabled')


def is_repository(item):
    return isinstance(item.patch, dict) and isinstance(item.patch.get('_repository'), dict)


def _read_policy_sources():
    return digest({name: bytes_digest((ROOT / name).read_bytes()) for name in (
        'src/ownstack/repository_cockpit.py', 'src/ownstack/repository_executor.py',
        'src/ownstack/repository_worker.py', 'src/ownstack/api.py',
        'src/ownstack/repository_release.py','src/ownstack/release_executor.py','src/ownstack/release_contracts.py',
        'src/ownstack/release_assurance.py',
        'src/ownstack/repository_registry.py','src/ownstack/customers.py','src/ownstack/customer_models.py',
        'src/ownstack/repository_recovery.py',
        'src/ownstack/repository_supervisor.py',
        'src/ownstack/bounded_process.py', 'src/ownstack/repository_profiles.py',
        'src/ownstack/team_scope.py','src/ownstack/team_identity.py','src/ownstack/models.py',
        'src/ownstack/auth.py','src/ownstack/host_access.py','src/ownstack/policy.py','src/ownstack/teams.py',
        'src/ownstack/service.py','src/ownstack/governance.py',
        SUPPLEMENT + '/cases.jsonl', SUPPLEMENT + '/manifest.json',
        *sorted({p.dockerfile for p in PROFILES.values()}))})


_LOADED_POLICY = _read_policy_sources()


def policy_hash():
    if _read_policy_sources() != _LOADED_POLICY:
        raise HTTPException(409, 'Local repository code changed; restart the API and operator before new checks')
    return _LOADED_POLICY


def catalog():
    raw = (ROOT / 'evals/real_issues_v1/cases.jsonl').read_bytes()
    manifest = json.loads((ROOT / 'evals/real_issues_v1/manifest.json').read_text())
    if bytes_digest(raw) != manifest['catalog_sha256']:
        raise HTTPException(409, 'Repository catalog changed')
    try:
        extra = list(supplemental_cases().values())
    except ValueError:
        raise HTTPException(409, 'Supplemental repository source changed') from None
    return {r['id']: {**r, 'profile': CASE_PROFILES[r['id']]}
            for r in [*map(json.loads, raw.decode().splitlines()), *extra] if r['id'] in CASES}


def request_hash(request):
    return digest(request_snapshot(request))


def request_snapshot(request):
    return {name: getattr(request, name) for name in
            ('id', 'tenant_id', 'team_id', 'text', 'kind', 'project_id', 'revision')}


def request_fence(item):
    snapshot = binding(item)['request_snapshot']
    return select(ChangeRequest.id).where(*[
        getattr(ChangeRequest, key) == value for key, value in snapshot.items()]).exists()


def binding(item):
    if not is_repository(item):
        raise HTTPException(409, 'Bind a supported repository case first')
    return item.patch['_repository']


def candidate(item):
    return {'edits': item.patch['edits']}


def context_hash(item):
    value={'binding': binding(item), 'patch_hash': item.patch_hash,
           'origin': item.patch.get('_candidate_origin')}
    if '_customer_release' in item.patch:value['customer_release']=item.patch['_customer_release']
    return digest(value)


def static_context(db, item):
    require_enabled()
    b = binding(item)
    request = scoped(db, ChangeRequest, item.request_id, item.tenant_id)
    case = catalog().get(b['case_id'])
    if (not case or b['request_hash'] != request_hash(request) or b['policy_hash'] != policy_hash()
            or b.get('execution_policy_sha256') != execution_fingerprint(b['profile'])
            or any(b.get(k) != case[k] for k in
                   ('base_commit', 'problem_sha256', 'required_tests_sha256', 'test_patch_sha256', 'profile'))):
        raise HTTPException(409, 'Request, repository, oracle or verification policy changed')
    return b,request


def current_context(db,item):
    b,request=static_context(db,item)
    from ownstack.repository_registry import validate_witness,connection_required
    if b.get('connection'):validate_witness(db,request,b['connection'])
    elif connection_required(db,request):raise HTTPException(409,'Onboard and connect this customer repository before running checks')
    from ownstack.repository_release import current
    current(db,item)
    return b


def validate_candidate(patch, profile_id=PROFILE):
    from ownstack.repository_executor import safe_relative
    profile = by_id(profile_id)
    if (not isinstance(patch, dict) or set(patch) != {'edits'} or not isinstance(patch['edits'], list)
            or not 1 <= len(patch['edits']) <= 8 or len(canonical(patch).encode()) > 128000):
        raise HTTPException(422, 'Supply one to eight bounded implementation edits')
    seen = set()
    for edit in patch['edits']:
        if not isinstance(edit, dict) or set(edit) != {'path', 'old', 'new'} or not all(isinstance(v, str) for v in edit.values()):
            raise HTTPException(422, 'Only path, old and new text are accepted')
        try:
            name = safe_relative(edit['path'])
            if not name.startswith(profile.source_prefixes) or name.startswith(profile.forbidden_prefixes):
                raise ValueError('Wrong profile path')
            if name in dict(profile.generated_files):
                raise ValueError('Generated profile metadata is read-only')
        except ValueError:
            raise HTTPException(422, 'Only declared repository implementation paths are allowed') from None
        anchor = (name, edit['old'])
        if (not name.endswith('.py') or name.endswith('conftest.py') or not edit['old']
                or edit['old'] == edit['new'] or anchor in seen):
            raise HTTPException(422, 'Distinct changed implementation anchors required')
        seen.add(anchor)
    return bytes_digest(canonical(patch))


def save_candidate(db, item, patch, origin, principal):
    previous = check_row(db, item)
    if previous and previous.result.get('recovery_token') and not previous.result.get('lease_closed'):
        raise HTTPException(409, 'Recovery must verify cleanup before replacing this candidate')
    current_context(db, item)
    if origin not in {'human', 'model'}:
        raise HTTPException(422, 'Declare whether the supplied candidate is human or AI-assisted')
    if item.human_decision or item.status not in {'repository_bound', 'drafted', 'checks_failed'}:
        raise HTTPException(409, 'Stop current checks before replacing a candidate')
    checksum = validate_candidate(patch, binding(item)['profile'])
    if item.patch_hash == checksum and item.patch.get('_candidate_origin') == origin:
        return {'id': item.id, 'status': item.status, 'patch_hash': checksum, 'ai_call': False}
    old = deepcopy(item.patch)
    payload = {**deepcopy(patch), '_repository': binding(item), '_candidate_origin': origin, '_verification_id': None}
    if '_customer_release' in old:payload['_customer_release']=deepcopy(old['_customer_release'])
    changed = db.execute(update(EngineeringItem).where(EngineeringItem.id == item.id,
        EngineeringItem.tenant_id == principal.tenant_id, EngineeringItem.status == item.status,
        EngineeringItem.patch_hash == item.patch_hash, request_fence(item),
        EngineeringItem.human_decision.is_(None), EngineeringItem.operation_id.is_(None))
        .values(patch=payload, patch_hash=checksum, status='drafted').execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        raise HTTPException(409, 'Work item changed')
    if item.patch_hash:
        db.add(Evidence(id=str(uuid4()), tenant_id=item.tenant_id, request_id=item.request_id,
            kind='repository_superseded', subject_hash=item.patch_hash,
            result={'patch': old, 'replacement_hash': checksum}, limitation='Historical supplied candidate, not current checks.'))
    record(db, item.tenant_id, item.request_id, 'repository.candidate_saved',
           {'item_id': item.id, 'patch_hash': checksum, 'origin': origin, 'actor_id': principal.user_id})
    db.expire(item)
    return {'id': item.id, 'status': item.status, 'patch_hash': item.patch_hash, 'ai_call': False}


def check_row(db, item):
    ident = item.patch.get('_verification_id') if is_repository(item) else None
    row = db.get(Evidence, ident) if ident else None
    if row and row.tenant_id == item.tenant_id and row.request_id == item.request_id and row.kind == 'repository_checks':
        return row
    return None


def expire_check(db, item):
    row = check_row(db, item)
    if row and row.result.get('state') in {'recovering', 'recovery_blocked'}:
        return  # Cleanup owns this operation; an HTTP read cannot bypass it.
    if item.status == 'checking' and item.operation_deadline and aware(item.operation_deadline) <= utcnow():
        operation = item.operation_id
        changed = db.execute(update(EngineeringItem).where(EngineeringItem.id == item.id,
            EngineeringItem.operation_id == operation, EngineeringItem.status == 'checking',
            EngineeringItem.operation_deadline <= utcnow()).values(status='checks_failed',
            operation_id=None, operation_deadline=None).execution_options(synchronize_session=False))
        if changed.rowcount and row:
            row.result = {**row.result, 'state': 'timed_out', 'error_code': 'LOCAL_DEADLINE',
                          'finished_at': utcnow().isoformat()}
            record(db, item.tenant_id, item.request_id, 'repository.check_timed_out', {'check_id': row.id})
        db.expire(item)


def enqueue(db, item, principal, *, retry=False, expected_id=None):
    current_context(db, item)
    from ownstack.repository_registry import connection_required
    from ownstack.repository_release import bound
    if connection_required(db,db.get(ChangeRequest,item.request_id)) and not bound(item):
        raise HTTPException(409,'Attach every approved customer requirement before running this customer repository')
    expected_context=context_hash(item)
    expected_patch=item.patch_hash
    expire_check(db, item)
    previous = check_row(db, item)
    if previous and previous.result.get('recovery_token') and not previous.result.get('lease_closed'):
        return public_check(previous)
    if item.human_decision or not item.patch_hash:
        raise HTTPException(409, 'An undecided saved candidate is required')
    if previous and previous.result['context_hash'] == context_hash(item):
        if previous.result['state'] in {'queued', 'running', 'recovering', 'recovery_blocked'} or not retry:
            return public_check(previous)
        if expected_id != previous.id:
            raise HTTPException(409, 'Retry must name the exact previous check')
    if item.status not in {'drafted', 'checks_failed', 'checks_passed'}:
        raise HTTPException(409, 'Candidate cannot be checked in this state')
    ident = str(uuid4()); deadline = utcnow() + timedelta(minutes=10)
    payload = {**item.patch, '_verification_id': ident}
    updated = db.execute(update(EngineeringItem).where(EngineeringItem.id == item.id,
        EngineeringItem.tenant_id == principal.tenant_id, EngineeringItem.status == item.status,
        EngineeringItem.patch_hash == item.patch_hash, EngineeringItem.operation_id.is_(None),
        EngineeringItem.patch['_verification_id'].as_string() == item.patch.get('_verification_id'),
        request_fence(item), EngineeringItem.human_decision.is_(None)).values(status='checking', operation_id=ident,
        operation_deadline=deadline, patch=payload).execution_options(synchronize_session=False))
    if updated.rowcount != 1:
        # A concurrent identical delivery may have queued the exact work while
        # this request waited for authorization. Return that saved attempt;
        # never replace it or silently adopt a different candidate/context.
        db.refresh(item)
        if (not item.human_decision and item.patch_hash==expected_patch
                and context_hash(item)==expected_context):
            current_context(db,item)
            saved=check_row(db,item)
            if (saved and saved.subject_hash==expected_patch
                    and saved.result.get('context_hash')==expected_context
                    and (not retry or saved.result.get('state') in {'queued','running','recovering','recovery_blocked'})):
                return public_check(saved)
        raise HTTPException(409, 'Checks already changed; refresh saved state')
    data = {'id': ident, 'item_id': item.id, 'state': 'queued', 'actor_id': principal.user_id,
            'case_id': binding(item)['case_id'], 'patch_hash': item.patch_hash, 'context_hash': context_hash(item),
            'queued_at': utcnow().isoformat(), 'deadline': deadline.isoformat(), 'report': None, 'error_code': None}
    row = Evidence(id=ident, tenant_id=item.tenant_id, request_id=item.request_id,
                   kind='repository_checks', subject_hash=item.patch_hash, result=data, limitation=LIMITATION)
    db.add(row)
    record(db, item.tenant_id, item.request_id, 'repository.check_queued', {'item_id': item.id, 'check_id': ident})
    db.flush(); db.expire(item)
    return public_check(row)


def public_check(row):
    data = row.result
    return {k: data.get(k) for k in ('id', 'state', 'case_id', 'patch_hash', 'context_hash',
        'queued_at', 'started_at', 'finished_at', 'deadline', 'report', 'error_code',
        'heartbeat_at', 'lease_until', 'recovery_count', 'previous_check_id', 'replacement_check_id',
        'recovery_requested_at', 'cleanup_verified', 'cleanup_attempts', 'recovery_exhausted', 'recovery_until')}


def matching(db, item):
    try:
        b = current_context(db, item)
    except HTTPException:
        return []
    row = check_row(db, item)
    if not row or row.subject_hash != item.patch_hash or row.result.get('state') != 'passed':
        return []
    data = row.result; report = data.get('report') or {}
    if not isinstance(report, dict):
        return []
    from ownstack.repository_release import bound,validate
    if bound(item) is not None:
        try:
            if not validate(report.get('customer_release'),bound(item),report)['passed']:return []
        except (ValueError,TypeError,KeyError):return []
    required = report.get('required_tests', [])
    if (not isinstance(required, list) or not all(isinstance(t, str) for t in required)
            or not isinstance(report.get('observed_tests'), dict)):
        return []
    if (data.get('context_hash') != context_hash(item) or data.get('patch_hash') != item.patch_hash
            or report.get('case_id') != b['case_id'] or report.get('origin') != item.patch.get('_candidate_origin')
            or report.get('candidate_sha256') != item.patch_hash or report.get('case_sha256') != b['problem_sha256']
            or report.get('oracle_sha256') != b['required_tests_sha256'] or report.get('base_commit') != b['base_commit']
            or report.get('profile') != b['profile'] or report.get('passed') is not True
            or report.get('execution_policy_sha256') != b['execution_policy_sha256']
            or report.get('baseline_failed') is not True or report.get('candidate_passed') is not True
            or report.get('released') is not False
            or not report.get('diff') or report.get('diff_hash') != digest(report.get('diff'))
            or len(required) != b['required_test_count'] or len(set(required)) != len(required)
            or not all(report.get('observed_tests', {}).get(t) is True for t in required)
            or data.get('receipt_hash') != digest(report)):
        return []
    return [report]


def view(db, item):
    if not is_repository(item):
        return None
    checks = db.scalars(select(Evidence).where(Evidence.tenant_id == item.tenant_id,
        Evidence.request_id == item.request_id, Evidence.kind == 'repository_checks')
        .order_by(Evidence.created_at, Evidence.id)).all()
    return {'binding': binding(item), 'context_hash': context_hash(item),
            'customer_release': item.patch.get('_customer_release'),
            'verification_id': item.patch.get('_verification_id'),
            'candidate_origin': item.patch.get('_candidate_origin'), 'checks': [public_check(r) for r in checks]}


def decide(db, item, principal, decision, patch_hash, verification_id, supplied_context):
    require_enabled()
    if item.human_decision:
        raise HTTPException(409, 'Decision already recorded')
    if decision == 'accept_for_manual_release':
        row = check_row(db, item)
        if (item.status != 'checks_passed' or patch_hash != item.patch_hash or not row
                or verification_id != row.id or supplied_context != context_hash(item) or not matching(db, item)):
            raise HTTPException(409, 'Exact current patch, verification and context are required')
    elif decision not in {'reject', 'take_over'}:
        raise HTTPException(422, 'Unknown review decision')
    # CAS also fences a concurrent check, patch replacement or second reviewer.
    updated = db.execute(update(EngineeringItem).where(EngineeringItem.id == item.id,
        EngineeringItem.tenant_id == principal.tenant_id, EngineeringItem.status == item.status,
        EngineeringItem.patch_hash == item.patch_hash,
        EngineeringItem.patch['_verification_id'].as_string() == item.patch.get('_verification_id'),
        request_fence(item), EngineeringItem.human_decision.is_(None))
        .values(human_decision=decision, status='human_decided', operation_id=None,
                operation_deadline=None).execution_options(synchronize_session=False))
    if updated.rowcount != 1:
        raise HTTPException(409, 'Review context changed')
    active = check_row(db, item)
    if active and active.result['state'] in {'queued', 'running', 'recovering', 'recovery_blocked'}:
        active.result = {**active.result, 'state': 'canceled', 'error_code': 'HUMAN_TAKEOVER'}
    record(db, item.tenant_id, item.request_id, 'repository.human_decision',
           {'item_id': item.id, 'decision': decision, 'patch_hash': item.patch_hash,
            'verification_id': verification_id, 'context_hash': supplied_context, 'actor_id': principal.user_id})
    return {'decision': decision, 'release_state': 'not_deployed'}


def artifact(db, item):
    if item.human_decision != 'accept_for_manual_release' or not matching(db, item):
        raise HTTPException(409, 'Current checked repository patch must be reviewed first')
    diff = matching(db, item)[0]['diff']
    return {'item_id': item.id, 'patch_hash': item.patch_hash, 'binding': binding(item),
            'verification_id': item.patch['_verification_id'], 'context_hash': context_hash(item),
            'diff': diff, 'patch': candidate(item), 'checks': matching(db, item), 'release_state': 'not_deployed'}


class BindBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    case_id: str
    repository_id: str | None = Field(default=None,min_length=1,max_length=40)


class RetryBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    verification_id: str


class ReleaseCoverageBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requirement_ids: list[str] = Field(min_length=1,max_length=30)


@router.post('/engineering/{item_id}/release-assurance')
def attach_release_coverage(item_id: str,body: ReleaseCoverageBody,principal: Principal=Depends(current_principal),db: Session=Depends(db_session)):
    require_enabled();require_role(principal,'engineer')
    item=scoped(db,EngineeringItem,item_id,principal.tenant_id,actor=principal,write=True)
    from ownstack.repository_release import attach
    result=attach(db,item,principal,body.requirement_ids)
    db.commit()
    return result


@router.get('/repository-cases')
def cases(principal: Principal = Depends(current_principal)):
    require_enabled(); require_role(principal, 'engineer', 'admin','manager')
    return [{'id': r['id'], 'title': r['title'], 'source_url': r['source_url'], 'base_commit': r['base_commit']}
            for r in catalog().values()]


@router.get('/repository-cases/{case_id}/example')
def example(case_id: str, principal: Principal = Depends(current_principal)):
    require_enabled(); require_role(principal, 'engineer')
    names = EXAMPLES
    if case_id not in names:
        raise HTTPException(404, 'Unknown local example')
    return {'patch': json.loads((ROOT / 'evals/repository_candidates' / names[case_id]).read_text()),
            'candidate_origin': 'model', 'source': 'Saved coding-assisted evaluator candidate, no new inference'}


@router.post('/engineering/{item_id}/repository')
def bind_case(item_id: str, body: BindBody, principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_enabled(); require_role(principal, 'engineer')
    item = scoped(db, EngineeringItem, item_id, principal.tenant_id, actor=principal, write=True)
    if is_repository(item):
        current_context(db, item)
        if binding(item)['case_id'] != body.case_id:
            raise HTTPException(409, 'This work item already has a different pinned case')
        return view(db, item)
    case = catalog().get(body.case_id)
    if not case:
        raise HTTPException(422, 'Only the reviewed local repository cases are available')
    request = scoped(db, ChangeRequest, item.request_id, principal.tenant_id, actor=principal, write=True)
    if request.kind != 'feature' or item.status != 'needs_engineer' or item.patch or item.human_decision:
        raise HTTPException(409, 'Bind a fresh engineering work item')
    b = {k: case[k] for k in ('id', 'repo', 'title', 'source_url', 'base_commit', 'problem_sha256',
                               'required_tests_sha256', 'test_patch_sha256')}
    b['case_id'] = b.pop('id')
    b.update(profile=case['profile'], request_hash=request_hash(request), request_snapshot=request_snapshot(request), policy_hash=policy_hash(),
             execution_policy_sha256=execution_fingerprint(case['profile']),
             required_test_count=case['fail_to_pass_count'] + case['pass_to_pass_count'])
    from ownstack.repository_registry import witness,connection_required
    if body.repository_id:
        connection=witness(db,request,body.repository_id,kind='pinned')
        if connection['source']['case_id']!=body.case_id:raise HTTPException(409,'Repository connection pins a different case')
        b['connection']=connection
    elif connection_required(db,request):
        raise HTTPException(422,'Select an onboarded repository connected to this customer')
    changed = db.execute(update(EngineeringItem).where(EngineeringItem.id == item.id,
        EngineeringItem.tenant_id == principal.tenant_id, EngineeringItem.status == 'needs_engineer',
        EngineeringItem.patch_hash.is_(None), EngineeringItem.operation_id.is_(None))
        .values(status='repository_bound', patch={'edits': [], '_repository': b})
        .execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        raise HTTPException(409, 'Work item changed during binding')
    record(db, item.tenant_id, item.request_id, 'repository.bound', {'item_id': item.id, 'binding_hash': digest(b), 'case_id': body.case_id})
    db.commit(); db.refresh(item)
    return view(db, item)


class ReconnectBody(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    repository_id:str=Field(min_length=1,max_length=40)
    expected_context_hash:str=Field(pattern=r'^[a-f0-9]{64}$')


@router.post('/engineering/{item_id}/repository/reconnect')
def reconnect(item_id:str,body:ReconnectBody,principal=Depends(current_principal),db=Depends(db_session)):
    require_enabled();require_role(principal,'engineer')
    item=scoped(db,EngineeringItem,item_id,principal.tenant_id,actor=principal,write=True)
    b,request=static_context(db,item)
    from ownstack.release_assurance import lock_project
    lock_project(db,principal,request.project_id)
    if context_hash(item)!=body.expected_context_hash:raise HTTPException(409,'Work item changed; refresh before reconnecting')
    if item.human_decision or item.operation_id:raise HTTPException(409,'Only stopped, undecided work can reconnect')
    previous=check_row(db,item)
    if previous and previous.result.get('recovery_token') and not previous.result.get('lease_closed'):
        raise HTTPException(409,'Recovery must verify cleanup before reconnecting')
    from ownstack.repository_registry import witness
    connection=witness(db,request,body.repository_id,kind='pinned')
    if connection['source']['case_id']!=b['case_id']:raise HTTPException(409,'Reconnect cannot change the pinned repository case')
    payload=deepcopy(item.patch);payload['_repository']['connection']=connection
    payload.pop('_customer_release',None);payload['_verification_id']=None
    item.patch=payload;item.status='drafted' if item.patch_hash else 'repository_bound'
    record(db,item.tenant_id,item.request_id,'repository.reconnected',{'repository_id':body.repository_id,'actor_id':principal.user_id})
    db.commit();return view(db,item)


@router.post('/engineering/{item_id}/repository/retry')
def retry(item_id: str, body: RetryBody, principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_enabled(); require_role(principal, 'engineer')
    item = scoped(db, EngineeringItem, item_id, principal.tenant_id, actor=principal, write=True)
    result = enqueue(db, item, principal, retry=True, expected_id=body.verification_id)
    db.commit(); return result


@router.post('/engineering/{item_id}/repository/cancel')
def cancel(item_id: str, body: RetryBody, principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_enabled(); require_role(principal, 'engineer')
    item = scoped(db, EngineeringItem, item_id, principal.tenant_id, actor=principal, write=True)
    row = check_row(db, item)
    if not row or row.id != body.verification_id or row.result['state'] not in {'queued', 'running', 'recovering', 'recovery_blocked'}:
        raise HTTPException(409, 'Name the current active check')
    updated = db.execute(update(EngineeringItem).where(EngineeringItem.id == item.id,
        EngineeringItem.operation_id == row.id, EngineeringItem.status == 'checking')
        .values(status='checks_failed', operation_id=None, operation_deadline=None)
        .execution_options(synchronize_session=False))
    if updated.rowcount != 1:
        raise HTTPException(409, 'Check already changed')
    # A reaper may have acquired its durable cleanup claim after our initial
    # read. Lock/reload evidence only after the item CAS, preserving item ->
    # evidence order and every ownership/cleanup field on the current record.
    row = db.scalar(select(Evidence).where(Evidence.id == row.id,
        Evidence.tenant_id == principal.tenant_id).with_for_update()
        .execution_options(populate_existing=True))
    if not row:
        raise HTTPException(409, 'Check already changed')
    row.result = {**row.result, 'state': 'canceled', 'finished_at': utcnow().isoformat(), 'error_code': 'CANCELED_LOCALLY'}
    record(db, item.tenant_id, item.request_id, 'repository.check_canceled', {'check_id': row.id})
    db.commit()
    return {**public_check(row), 'note': 'Saved cancellation prevents acceptance. The operator process may still be finishing cleanup.'}
