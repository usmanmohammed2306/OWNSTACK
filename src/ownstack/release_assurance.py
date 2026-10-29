"""Local release assurance: exact human requirements, queued independent checks.

No HTTP route executes code or accepts execution results. A local operator with
private DB access runs the bounded adapter. Synthetic evidence is not buyer proof.
"""
from copy import deepcopy
from datetime import timedelta
import json
import os
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from ownstack.auth import current_principal, db_session, require_role
from ownstack.config import Settings
from ownstack.models import Project, ReleaseAudit, ReleaseCheck, ReleaseRequirement, Team, TeamMembership, User
from ownstack.policy import Principal, aware, digest
from ownstack.release_contracts import RequirementSpec, evaluate_observation, requirement_active, requirement_digest
from ownstack.service import utcnow
from ownstack.team_scope import project_visible, require_project

router = APIRouter(prefix='/v1/release', tags=['local release assurance'])
HASH = r'^[a-f0-9]{64}$'


def enabled():
    if Settings().environment != 'local' or os.getenv('OWNSTACK_RELEASE_ASSURANCE') != 'true':
        raise HTTPException(404, 'Local release assurance is not enabled')


@router.get('/local-proof',dependencies=[Depends(enabled)])
def local_proof(nonce:str):
    import hashlib,hmac,re
    if not re.fullmatch('[a-f0-9]{64}',nonce):raise HTTPException(422,'Bounded nonce required')
    settings=Settings()
    if settings.ai_mode!='off' or settings.max_live_calls!=0:raise HTTPException(404,'Offline local onboarding only')
    return {'proof':hmac.new(settings.signing_secret.encode(),(settings.public_origin+'|'+nonce).encode(),hashlib.sha256).hexdigest()}


class Body(BaseModel):
    model_config = ConfigDict(extra='forbid')


class NewRequirement(Body):
    project_id: str = Field(min_length=1, max_length=40)
    spec: RequirementSpec
    customer_account_id: str | None = Field(default=None, min_length=1, max_length=40)


class RegisterSource(Body):
    project_id: str = Field(min_length=1,max_length=40)
    label: str = Field(min_length=1,max_length=80,pattern=r'^[A-Za-z0-9][A-Za-z0-9 ._/-]*$')
    snapshot: dict


class Approve(Body):
    expected_hash: str = Field(pattern=HASH)


class NewCheck(Body):
    project_id: str = Field(min_length=1, max_length=40)
    baseline_sha256: str = Field(pattern=HASH)
    candidate_sha256: str = Field(pattern=HASH)
    requirement_ids: list[str] = Field(min_length=1, max_length=30)
    idempotency_key: str = Field(min_length=8, max_length=80, pattern=r'^[a-zA-Z0-9_-]+$')


class Version(Body):
    expected_revision: int = Field(ge=1, strict=True)


class Decide(Version):
    evidence_hash: str = Field(pattern=HASH)
    decision: Literal['accept_for_manual_release', 'reject']


def audit(db, project, subject, action, **payload):
    db.add(ReleaseAudit(id=str(uuid4()), tenant_id=project.tenant_id, project_id=project.id,
                        subject_id=subject, action=action, payload=payload))


def lock_project(db, principal, project_id):
    project = require_project(db, principal, project_id)
    if db.get_bind().dialect.name == 'sqlite':
        # SQLite ignores SELECT FOR UPDATE. Reserve its writer before reading
        # authority or deduplication rows, so overlapping local API requests
        # cannot both read an empty catalog and append the same source.
        # This is a no-op value update, not a project revision or effect change.
        db.execute(update(Project).where(Project.id==project.id,
            Project.tenant_id==principal.tenant_id).values(revision=Project.revision)
            .execution_options(synchronize_session=False))
    user=db.scalar(select(User).where(User.id==principal.user_id,User.tenant_id==principal.tenant_id)
        .with_for_update(read=True).execution_options(populate_existing=True))
    if not user or not user.enabled or user.role!=principal.role:
        raise HTTPException(401,'Identity changed')
    membership=select(TeamMembership).join(Team,(Team.id==TeamMembership.team_id)&(Team.tenant_id==TeamMembership.tenant_id)).where(
        TeamMembership.user_id==user.id,TeamMembership.tenant_id==user.tenant_id,
        TeamMembership.team_id==project.team_id,TeamMembership.enabled.is_(True),Team.enabled.is_(True))
    if user.role=='manager':membership=membership.where(TeamMembership.role=='manager')
    # Shared authority locks fence revocation while allowing independent readers.
    # Taking exclusive membership locks before/after the project would introduce
    # a cycle between queue claim, cancellation and requirement approval.
    if db.scalar(membership.with_for_update(read=True,of=[TeamMembership,Team]).execution_options(populate_existing=True)) is None:
        raise HTTPException(404,'Not found')
    return db.scalar(select(Project).where(Project.id == project.id).with_for_update(key_share=True).execution_options(populate_existing=True))


def visible_projects(principal):
    return select(Project.id).where(project_visible(principal)).correlate(None)


def row(db, model, ident, principal, *, write=False):
    item = db.scalar(select(model).where(model.id == ident, model.tenant_id == principal.tenant_id,
                                        model.project_id.in_(visible_projects(principal))))
    if item is None:
        raise HTTPException(404, 'Not found')
    project = lock_project(db, principal, item.project_id) if write else require_project(db, principal, item.project_id)
    if write:
        db.refresh(item)
    return item, project


def serialize_requirement(item):
    return {k: getattr(item, k) for k in ('id', 'project_id', 'spec', 'requirement_hash', 'state',
            'created_by', 'approved_by', 'approved_at', 'created_at')}


def serialize_check(item):
    return {k: getattr(item, k) for k in ('id', 'project_id', 'state', 'revision', 'baseline_sha256',
        'candidate_sha256', 'requirement_ids', 'requirements_sha256', 'report', 'evidence_hash',
        'decision', 'reason', 'created_at', 'completed_at')}


def bundle_hash(requirements):
    return digest(sorted(requirements, key=lambda spec: (spec['key'], spec['version'])))


def approval_authority(db,approver,project):
    """Record the exact authority generation, not just currently restored access.

    Revoking then restoring membership increments its revision. The old approval
    must not revive after that gap. This witness stays in the atomic approval
    audit; old approvals without a witness require a fresh approved revision.
    """
    member=db.scalar(select(TeamMembership).join(Team,
        (Team.id==TeamMembership.team_id)&(Team.tenant_id==TeamMembership.tenant_id)).where(
            TeamMembership.tenant_id==project.tenant_id,TeamMembership.team_id==project.team_id,
            TeamMembership.user_id==approver.id,TeamMembership.enabled.is_(True),Team.enabled.is_(True))
        .with_for_update(read=True,of=[TeamMembership,Team]).execution_options(populate_existing=True))
    if member is None:raise ValueError('Requirement approver team changed')
    return {'actor_id':approver.id,'identity_version':approver.token_version,'team_id':project.team_id,
            'membership_id':member.id,'membership_revision':member.revision,'membership_role':member.role}


def approval_valid(db, item, project, at):
    from ownstack.customers import validate_requirement_customer
    validate_requirement_customer(db, item)
    spec = RequirementSpec.model_validate(item.spec)
    if (item.state != 'approved' or requirement_digest(spec) != item.requirement_hash
            or not requirement_active(spec, at) or item.approved_by is None):
        raise ValueError('Requirement approval changed, expired or is incomplete')
    approver = db.scalar(select(User).where(User.id==item.approved_by).with_for_update(read=True).execution_options(populate_existing=True))
    if (not approver or not approver.enabled or approver.role != 'admin'
            or approver.token_version != item.approver_version or approver.tenant_id != item.tenant_id):
        raise ValueError('Requirement approver authority changed')
    try:
        lock_project(db, Principal(approver.id, approver.tenant_id, approver.role), project.id)
    except HTTPException:
        raise ValueError('Requirement approver team changed') from None
    receipts=db.scalars(select(ReleaseAudit).where(ReleaseAudit.subject_id==item.id,
        ReleaseAudit.tenant_id==item.tenant_id,ReleaseAudit.project_id==project.id,
        ReleaseAudit.action=='requirement.approved')).all()
    if (len(receipts)!=1 or receipts[0].payload.get('actor')!=approver.id
            or receipts[0].payload.get('requirement_hash')!=item.requirement_hash
            or receipts[0].payload.get('authority')!=approval_authority(db,approver,project)):
        raise ValueError('Requirement approval authority generation changed or is missing; approve a new revision')
    if spec.source_ref.startswith('ownstack://discovery/'):
        from ownstack.change_agent import discovery_requirement_valid
        discovery_requirement_valid(db,item,project)
    return spec.model_dump(mode='json')


def current_requirements(db, project, at):
    # Approval/draft publication takes this project lock before changing the set.
    # Take it BEFORE reading coverage, not after an old SQL snapshot is selected.
    project=db.scalar(select(Project).where(Project.id==project.id).with_for_update(key_share=True)
        .execution_options(populate_existing=True))
    if project is None:raise ValueError('Requirement project disappeared')
    at=max(aware(at),utcnow())  # Waiting for a lock cannot extend an expiry.
    approved = db.scalars(select(ReleaseRequirement).where(ReleaseRequirement.project_id == project.id,
        ReleaseRequirement.tenant_id == project.tenant_id, ReleaseRequirement.state == 'approved')
        .execution_options(populate_existing=True)).all()
    if not approved:
        raise ValueError('No approved requirements; an empty suite cannot pass')
    if len(approved)>30 or sum(len(r.spec.get('cases',[])) for r in approved)>256:
        raise ValueError('Approved suite exceeds the supported 30 requirements / 256 cases')
    # Expired/invalid requirements block the gate for inspection. They are never
    # silently removed to turn a failing or uncovered release into a pass.
    return sorted([(r.id, approval_valid(db, r, project, at)) for r in approved], key=lambda pair: pair[0])


@router.get('/sources',dependencies=[Depends(enabled)])
def source_catalog(principal=Depends(current_principal),db=Depends(db_session)):
    require_role(principal,'admin','engineer','manager')
    rows=db.scalars(select(ReleaseAudit).where(ReleaseAudit.tenant_id==principal.tenant_id,
        ReleaseAudit.project_id.in_(visible_projects(principal)),ReleaseAudit.action=='source.registered')
        .order_by(ReleaseAudit.created_at.desc()).limit(500)).all()
    # List summaries, not hundreds of full repository inventories. Exact files
    # remain in scoped audit/check evidence for an explicit review.
    return [{'project_id':r.project_id,'label':r.payload['label'],'sha256':r.payload['snapshot']['sha256'],
        'profile':r.payload['snapshot']['profile'],'name':r.payload['snapshot']['config']['name'],
        'entrypoint':r.payload['snapshot']['config']['entrypoint'],'file_count':len(r.payload['snapshot']['files'])} for r in rows]


@router.post('/sources',status_code=201,dependencies=[Depends(enabled)])
def register_source(body:RegisterSource,principal=Depends(current_principal),db=Depends(db_session)):
    require_role(principal,'admin','engineer')
    from ownstack.release_repository import validate_snapshot
    try:
        if len(json.dumps(body.snapshot))>400000:raise ValueError('Source inventory exceeds supported size')
        validate_snapshot(body.snapshot)
    except (ValueError,TypeError,KeyError,AttributeError) as error:raise HTTPException(422,'Invalid reviewed source inventory') from None
    project=lock_project(db,principal,body.project_id)
    rows=db.scalars(select(ReleaseAudit).where(ReleaseAudit.project_id==project.id,
        ReleaseAudit.action=='source.registered')).all()
    previous=next((r for r in rows if r.payload['snapshot']['sha256']==body.snapshot['sha256']),None)
    if previous:return {'project_id':project.id,'label':previous.payload['label'],**previous.payload['snapshot']}
    if len(rows)>=50:raise HTTPException(409,'Project source catalog is full; retain history and review retention with the operator')
    audit(db,project,str(uuid4()),'source.registered',actor=principal.user_id,label=body.label,snapshot=body.snapshot)
    db.commit()
    return {'project_id':project.id,'label':body.label,**body.snapshot}


@router.get('/requirements-receipt',dependencies=[Depends(enabled)])
def export_requirements(project_id:str,principal=Depends(current_principal),db=Depends(db_session)):
    require_role(principal,'admin','engineer')
    project=lock_project(db,principal,project_id)
    try:rows=current_requirements(db,project,utcnow())
    except ValueError as error:raise HTTPException(409,str(error)) from None
    at=utcnow();specs=[s for _,s in rows]
    payload={'schema_version':1,'project_id':project.id,'requirement_ids':[ident for ident,_ in rows],
        'requirements':specs,'requirements_sha256':bundle_hash(specs),'exported_at':at.isoformat(),
        'expires_at':(at+timedelta(minutes=10)).isoformat(),
        'authority':'Verified at export only; independently pin the file digest and revalidate before release'}
    return {**payload,'receipt_sha256':digest(payload)}


def context_valid(db, item):
    requester = db.scalar(select(User).where(User.id==item.requested_by).with_for_update(read=True).execution_options(populate_existing=True))
    if not requester or not requester.enabled or requester.token_version != item.requester_version or requester.role not in {'admin', 'engineer'}:
        raise ValueError('Requester authority changed')
    principal = Principal(requester.id, requester.tenant_id, requester.role)
    try:
        project = lock_project(db, principal, item.project_id)
    except HTTPException:
        raise ValueError('Requester team changed') from None
    # Present access is insufficient: a revoke/restore gap must not revive work
    # created under an older membership generation. Keep this witness in the
    # same transaction as enqueue. Old jobs without one fail closed.
    receipts=db.scalars(select(ReleaseAudit).where(ReleaseAudit.subject_id==item.id,
        ReleaseAudit.tenant_id==item.tenant_id,ReleaseAudit.project_id==project.id,
        ReleaseAudit.action=='check.queued')).all()
    if (len(receipts)!=1 or receipts[0].payload.get('actor')!=requester.id
            or receipts[0].payload.get('intent_hash')!=item.intent_hash
            or receipts[0].payload.get('authority')!=approval_authority(db,requester,project)):
        raise ValueError('Requester authority generation changed or is missing; queue a new check')
    current = current_requirements(db, project, utcnow())
    from ownstack.repository_registry import source_check_witness
    witness=source_check_witness(db,project,item.baseline_sha256,item.requirement_ids)
    if receipts[0].payload.get('repository')!=witness:
        raise ValueError('Repository connection changed or is missing; queue a fresh connected comparison')
    if sorted(item.requirement_ids) != [r[0] for r in current] or bundle_hash([r[1] for r in current]) != item.requirements_sha256:
        raise ValueError('Approved requirements changed; queue a new check')
    return project


@router.get('/requirements', dependencies=[Depends(enabled)])
def list_requirements(principal=Depends(current_principal), db=Depends(db_session)):
    require_role(principal, 'admin', 'engineer', 'manager')
    return [serialize_requirement(r) for r in db.scalars(select(ReleaseRequirement).where(
        ReleaseRequirement.tenant_id == principal.tenant_id, ReleaseRequirement.project_id.in_(visible_projects(principal))).order_by(ReleaseRequirement.created_at))]


@router.post('/requirements', status_code=201, dependencies=[Depends(enabled)])
def create_requirement(body: NewRequirement, principal=Depends(current_principal), db=Depends(db_session)):
    require_role(principal, 'admin', 'engineer')
    project = lock_project(db, principal, body.project_id)
    existing = db.scalars(select(ReleaseRequirement).where(ReleaseRequirement.project_id == project.id,
        ReleaseRequirement.key == body.spec.key)).all()
    if existing and body.spec.version != max(r.version for r in existing) + 1:
        raise HTTPException(409, 'Create the next immutable requirement version')
    if not existing and body.spec.version != 1:
        raise HTTPException(409, 'First requirement version must be one')
    item = ReleaseRequirement(id=str(uuid4()), tenant_id=principal.tenant_id, project_id=project.id,
        key=body.spec.key, version=body.spec.version, spec=body.spec.model_dump(mode='json'),
        requirement_hash=requirement_digest(body.spec), created_by=principal.user_id, state='draft')
    db.add(item);audit(db, project, item.id, 'requirement.drafted', actor=principal.user_id, requirement_hash=item.requirement_hash)
    db.flush()
    from ownstack.customer_models import CustomerAccount
    known_customer = db.get(CustomerAccount, body.spec.customer_tenant_id)
    if known_customer is not None and known_customer.tenant_id != principal.tenant_id:
        raise HTTPException(404, 'Customer not found')
    customer_id = body.customer_account_id or (known_customer.id if known_customer else None)
    if customer_id:
        from ownstack.customers import bind_requirement
        bind_requirement(db, item, customer_id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409, 'Requirement version already exists') from None
    return serialize_requirement(item)


@router.get('/requirements/{ident}', dependencies=[Depends(enabled)])
def get_requirement(ident: str, principal=Depends(current_principal), db=Depends(db_session)):
    require_role(principal, 'admin', 'engineer', 'manager')
    return serialize_requirement(row(db, ReleaseRequirement, ident, principal)[0])


@router.post('/requirements/{ident}/approve', dependencies=[Depends(enabled)])
def approve_requirement(ident: str, body: Approve, principal=Depends(current_principal), db=Depends(db_session)):
    result=approve_requirement_in_transaction(ident,body,principal,db)
    db.commit()
    return result


def approve_requirement_in_transaction(ident,body,principal,db):
    """Shared atomic primitive; discovery approves its whole partitioned suite."""
    require_role(principal, 'admin')
    item, project = row(db, ReleaseRequirement, ident, principal, write=True)
    from ownstack.customers import validate_requirement_customer
    try:
        validate_requirement_customer(db, item)
    except ValueError as error:
        raise HTTPException(409, str(error)) from None
    if item.created_by == principal.user_id:
        raise HTTPException(403, 'A different administrator must approve the requirement')
    if body.expected_hash != item.requirement_hash or requirement_digest(RequirementSpec.model_validate(item.spec)) != body.expected_hash:
        raise HTTPException(409, 'Requirement hash changed')
    if not requirement_active(RequirementSpec.model_validate(item.spec), utcnow()):
        raise HTTPException(409, 'Requirement expired')
    latest = db.scalar(select(ReleaseRequirement).where(ReleaseRequirement.project_id == project.id,
        ReleaseRequirement.key == item.key).order_by(ReleaseRequirement.version.desc()).limit(1))
    if latest.id != item.id:
        raise HTTPException(409, 'A newer requirement revision exists')
    if item.state == 'approved':
        return serialize_requirement(item)
    if item.state != 'draft':
        raise HTTPException(409, 'Requirement is not a draft')
    db.execute(update(ReleaseRequirement).where(ReleaseRequirement.project_id == project.id,
        ReleaseRequirement.key == item.key, ReleaseRequirement.state == 'approved').values(state='superseded'))
    user = db.get(User, principal.user_id)
    item.state='approved';item.approved_by=user.id;item.approver_version=user.token_version;item.approved_at=utcnow()
    audit(db, project, item.id, 'requirement.approved', actor=user.id, requirement_hash=item.requirement_hash,
          authority=approval_authority(db,user,project))
    return serialize_requirement(item)


@router.post('/checks', status_code=202, dependencies=[Depends(enabled)])
def create_check(body: NewCheck, principal=Depends(current_principal), db=Depends(db_session)):
    require_role(principal, 'admin', 'engineer')
    project = lock_project(db, principal, body.project_id)
    intent = digest(body.model_dump(exclude={'idempotency_key'}))
    previous = db.scalar(select(ReleaseCheck).where(ReleaseCheck.tenant_id == principal.tenant_id,
        ReleaseCheck.requested_by == principal.user_id, ReleaseCheck.idempotency_key == body.idempotency_key))
    if previous:
        if previous.intent_hash != intent:
            raise HTTPException(409, 'Idempotency key belongs to different check inputs')
        return serialize_check(previous)
    if len(body.requirement_ids) != len(set(body.requirement_ids)):
        raise HTTPException(422, 'Distinct requirement IDs required')
    try:
        requirements=current_requirements(db, project, utcnow())
    except ValueError as error:
        raise HTTPException(409, str(error)) from None
    if sorted(body.requirement_ids) != [r[0] for r in requirements]:
        raise HTTPException(409, 'Every current approved requirement must be included')
    user=db.get(User,principal.user_id)
    specs=[r[1] for r in requirements]
    from ownstack.repository_registry import source_check_witness
    try:repository=source_check_witness(db,project,body.baseline_sha256,body.requirement_ids)
    except ValueError as error:raise HTTPException(409,str(error)) from None
    item=ReleaseCheck(id=str(uuid4()),tenant_id=principal.tenant_id,project_id=project.id,
        requested_by=user.id,requester_version=user.token_version,idempotency_key=body.idempotency_key,
        intent_hash=intent,baseline_sha256=body.baseline_sha256,candidate_sha256=body.candidate_sha256,
        requirement_ids=sorted(body.requirement_ids),requirements=specs,requirements_sha256=bundle_hash(specs),state='queued',revision=1)
    db.add(item);audit(db,project,item.id,'check.queued',actor=user.id,intent_hash=intent,
                      authority=approval_authority(db,user,project),repository=repository)
    try:
        db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,'Concurrent check submission; replay the same key') from None
    return serialize_check(item)


@router.get('/checks', dependencies=[Depends(enabled)])
def list_checks(principal=Depends(current_principal),db=Depends(db_session)):
    require_role(principal,'admin','engineer','manager')
    return [serialize_check(r) for r in db.scalars(select(ReleaseCheck).where(ReleaseCheck.tenant_id==principal.tenant_id,
        ReleaseCheck.project_id.in_(visible_projects(principal))).order_by(ReleaseCheck.created_at.desc()).limit(100))]


@router.get('/checks/{ident}', dependencies=[Depends(enabled)])
def get_check(ident: str,principal=Depends(current_principal),db=Depends(db_session)):
    require_role(principal,'admin','engineer','manager')
    return serialize_check(row(db,ReleaseCheck,ident,principal)[0])


@router.post('/checks/{ident}/cancel', dependencies=[Depends(enabled)])
def cancel_check(ident: str,body: Version,principal=Depends(current_principal),db=Depends(db_session)):
    require_role(principal,'admin','engineer')
    item,project=row(db,ReleaseCheck,ident,principal,write=True)
    if item.state=='canceled':return serialize_check(item)
    if item.revision!=body.expected_revision or item.state not in {'queued','running'}:
        raise HTTPException(409,'Check state changed')
    won=db.execute(update(ReleaseCheck).where(ReleaseCheck.id==item.id,ReleaseCheck.revision==body.expected_revision,
        ReleaseCheck.state.in_(['queued','running'])).values(state='canceled',claim_token=None,
        revision=item.revision+1,completed_at=utcnow(),reason='Canceled locally; remote process termination is not asserted')).rowcount
    if not won:db.rollback();raise HTTPException(409,'Check state changed')
    db.refresh(item)
    audit(db,project,item.id,'check.canceled',actor=principal.user_id)
    db.commit();return serialize_check(item)


@router.post('/checks/{ident}/decide', dependencies=[Depends(enabled)])
def decide_check(ident: str,body: Decide,principal=Depends(current_principal),db=Depends(db_session)):
    result=decide_check_in_transaction(ident,body,principal,db)
    db.commit()
    return result


def decide_check_in_transaction(ident,body,principal,db):
    require_role(principal,'admin','engineer')
    item,project=row(db,ReleaseCheck,ident,principal,write=True)
    if item.revision!=body.expected_revision or item.evidence_hash!=body.evidence_hash or not item.report or digest(item.report)!=item.evidence_hash:
        raise HTTPException(409,'Review must bind to exact current evidence')
    if item.decision:
        raise HTTPException(409,'A human decision is already recorded')
    if body.decision=='accept_for_manual_release':
        if item.state!='passed':raise HTTPException(409,'Only a passing check can be accepted')
        try:
            context_valid(db,item)
            if assess_report(item,item.report)!='passed':raise ValueError('Current execution evidence no longer passes')
        except (ValueError,KeyError,TypeError,AttributeError) as error:raise HTTPException(409,str(error)) from None
    won=db.execute(update(ReleaseCheck).where(ReleaseCheck.id==item.id,ReleaseCheck.revision==body.expected_revision,
        ReleaseCheck.evidence_hash==body.evidence_hash,ReleaseCheck.decision.is_(None)).values(
            decision=body.decision,decided_by=principal.user_id,revision=item.revision+1)).rowcount
    if not won:db.rollback();raise HTTPException(409,'Check decision changed')
    db.refresh(item)
    audit(db,project,item.id,'check.human_decision',actor=principal.user_id,decision=body.decision,evidence_hash=body.evidence_hash)
    return serialize_check(item)


def claim_next(factory,only_id=None):
    """One CAS claim, no Docker execution inside a DB transaction or API process."""
    with factory() as db:
        query=select(ReleaseCheck).where(ReleaseCheck.state=='queued')
        if only_id is not None:query=query.where(ReleaseCheck.id==only_id)
        item=db.scalar(query.order_by(ReleaseCheck.created_at).limit(1))
        if item is None:return None
        # Always acquire the project before a check-row write. Cancellation and
        # completion use the same order; check->project creates a real PG cycle.
        db.scalar(select(Project).where(Project.id==item.project_id).with_for_update(key_share=True))
        token=uuid4().hex
        won=db.execute(update(ReleaseCheck).where(ReleaseCheck.id==item.id,ReleaseCheck.state=='queued',ReleaseCheck.revision==item.revision)
            .values(state='running',claim_token=token,deadline_at=utcnow()+timedelta(minutes=5),revision=item.revision+1)).rowcount
        if not won:db.rollback();return None
        db.refresh(item)
        try:project=context_valid(db,item)
        except ValueError as error:
            item.state='blocked';item.reason=str(error);item.claim_token=None;item.completed_at=utcnow();db.commit();return None
        audit(db,project,item.id,'check.claimed',revision=item.revision)
        result={**serialize_check(item),'claim_token':token,'requirements':deepcopy(item.requirements)}
        db.commit();return result


def assess_report(item,report):
    """Recompute all verdicts from bounded observations, never trust claimed pass."""
    if not isinstance(report,dict) or len(json.dumps(report))>512_000 or report.get('baseline_sha256')!=item.baseline_sha256 or report.get('candidate_sha256')!=item.candidate_sha256 or report.get('requirements_sha256')!=item.requirements_sha256:
        raise ValueError('Result identity or size mismatch')
    if report.get('profile') not in {'python-http-visibility-v1','python-repository-http-v1'} or report.get('runner')!='release-http-docker-v1' or report.get('provider_calls')!=0 or report.get('released') is not False:
        raise ValueError('Unsupported execution provenance')
    from ownstack.release_executor import validate_report
    validate_report(report,item.requirements,item.baseline_sha256,item.candidate_sha256)
    specs=[RequirementSpec.model_validate(s) for s in item.requirements]
    expected={(s.key,c.case_id):c for s in specs for c in s.cases}
    evaluations={}
    for phase in ('baseline','candidate'):
        run=report.get(phase,{})
        if not isinstance(run,dict):raise ValueError('Malformed execution phase')
        if run.get('state')!='completed' or run.get('cleanup_verified') is not True:return 'blocked'
        observed=run.get('observations',[])
        if not isinstance(observed,list) or len(observed)!=len(expected):raise ValueError('Incomplete observed case coverage')
        seen={};results={}
        for observation in observed:
            if not isinstance(observation,dict):raise ValueError('Malformed observation')
            identity=(observation.get('requirement_key'),observation.get('case_id'))
            if identity not in expected or identity in seen or observation.get('error'):
                raise ValueError('Missing, duplicate or erroneous case observation')
            seen[identity]=True
            result=evaluate_observation(expected[identity],{'status_code':observation['status_code'],'visible_fields':observation['visible_fields']})
            results[identity]=result.passed
        evaluations[phase]=results
    if not all(evaluations['baseline'].values()):return 'baseline_failed'
    return 'passed' if all(evaluations['candidate'].values()) else 'regression'


def finish_check(factory,ident,claim_token,report):
    """Only the current bounded claim may publish; late answers remain audit only."""
    with factory() as db:
        item=db.get(ReleaseCheck,ident)
        if item is None:return False
        # Lock the project before the check, like every API mutation. This fences
        # requirement approval against completion and avoids reverse lock order.
        project=db.scalar(select(Project).where(Project.id==item.project_id).with_for_update(key_share=True))
        item=db.scalar(select(ReleaseCheck).where(ReleaseCheck.id==ident).with_for_update().execution_options(populate_existing=True))
        if item.state!='running' or item.claim_token!=claim_token:
            audit(db,project,item.id,'check.late_result_discarded',result_digest=digest(report));db.commit();return False
        reason=None
        try:
            context_valid(db,item)
            if not item.deadline_at or aware(item.deadline_at)<=utcnow():raise ValueError('Check deadline elapsed')
            state=assess_report(item,report)
        except (ValueError,KeyError,TypeError,AttributeError) as error:
            state='blocked';reason=str(error)[:300]
        # Keep malformed/oversized operator input out of API displays. Its
        # separately retained operator artifact remains the raw diagnostic.
        value=deepcopy(report)
        if state=='blocked' and (reason is not None or not isinstance(value,dict)):
            value={'state':'blocked','raw_report_sha256':digest(report),'raw_type':type(report).__name__,
                   'assessments':[],'limitation':'Invalid operator report quarantined; inspect private operator artifact'}
        # CAS also protects SQLite, whose SELECT FOR UPDATE is a no-op.
        won=db.execute(update(ReleaseCheck).where(ReleaseCheck.id==ident,ReleaseCheck.state=='running',ReleaseCheck.claim_token==claim_token)
            .values(state=state,report=value,evidence_hash=digest(value),reason=reason,claim_token=None,
                    revision=item.revision+1,completed_at=utcnow())).rowcount
        if not won:db.rollback();return False
        audit(db,project,item.id,'check.completed',state=state,evidence_hash=digest(value))
        db.commit();return True


def expire_checks(factory):
    """Explicit local maintenance, not an assertion that a remote runner stopped."""
    count=0
    with factory() as db:
        rows=db.scalars(select(ReleaseCheck).where(ReleaseCheck.state=='running',ReleaseCheck.deadline_at<=utcnow())).all()
        for item in rows:
            won=db.execute(update(ReleaseCheck).where(ReleaseCheck.id==item.id,ReleaseCheck.state=='running',ReleaseCheck.claim_token==item.claim_token)
                .values(state='blocked',claim_token=None,reason='Worker deadline elapsed; inspect owned runner before retry',revision=item.revision+1,completed_at=utcnow())).rowcount
            if won:
                audit(db,db.get(Project,item.project_id),item.id,'check.deadline_elapsed');count+=1
        db.commit()
    return count


def review_markdown(item):
    """Local CI artifact only. This function never publishes a PR comment."""
    lines=['# OwnStack customer release review', '', 'State: '+item.state,
        '', 'Baseline snapshot: `'+item.baseline_sha256+'`', 'Candidate snapshot: `'+item.candidate_sha256+'`',
        'Requirements: `'+item.requirements_sha256+'`', 'Evidence: `'+(item.evidence_hash or 'pending')+'`',
        '', '| Requirement / case | Expected | Baseline | Candidate | Result |', '| --- | --- | --- | --- | --- |']
    report=item.report if isinstance(item.report,dict) else {}
    assessments=report.get('assessments',[])
    if not isinstance(assessments,list):assessments=[]
    for result in assessments:
        if not isinstance(result,dict):continue
        # IDs/statuses come from schema-checked immutable inputs and observations.
        key=str(result.get('requirement_key','')).replace('|','').replace('\n',' ')
        case=str(result.get('case_id','')).replace('|','').replace('\n',' ')
        expected=result.get('expected',{});base=result.get('observed_baseline',{});candidate=result.get('observed_candidate',{})
        expected=expected if isinstance(expected,dict) else {}
        base=base if isinstance(base,dict) else {}
        candidate=candidate if isinstance(candidate,dict) else {}
        lines.append('| '+key+' / '+case+' | '+str(expected.get('status_code','?'))+' | '+str(base.get('status_code','?'))+' | '+str(candidate.get('status_code','?'))+' | '+('regression' if result.get('regression') else 'pass' if result.get('candidate_passed') else 'failed')+' |')
    lines+=['','Checked synthetic adapter behavior only. A pass is not a release or security certification.',
             'Human decision: '+(item.decision or 'pending')+'. Nothing was deployed.']
    return '\n'.join(lines)+'\n'


@router.get('/checks/{ident}/review', dependencies=[Depends(enabled)])
def get_review(ident: str,principal=Depends(current_principal),db=Depends(db_session)):
    from fastapi.responses import PlainTextResponse
    require_role(principal,'admin','engineer','manager')
    item,_=row(db,ReleaseCheck,ident,principal)
    return PlainTextResponse(review_markdown(item),media_type='text/markdown')
