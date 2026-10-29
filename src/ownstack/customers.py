"""Vendor-owned customers and a deliberately separate, least-authority portal.

Portal identities are not User rows. Their opaque sessions cannot authenticate
staff APIs, approve policy, inspect code or start model calls. Customer text enters
a separate inbox; an authorized engineer explicitly adopts it into their team.
"""
from datetime import timedelta
import secrets
from uuid import uuid4
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from ownstack.auth import current_principal, db_session, require_role, hash_secret, password_hash, check_password, rate_limit
from ownstack.customer_models import (CustomerAccount, CustomerProject, CustomerInvitation,
    CustomerIdentity, CustomerSession, CustomerSubmission, CustomerRequestLink, CustomerRequirementLink, CustomerAudit)
from ownstack.models import Project, Tenant, ChangeRequest, ReleaseCheck
from ownstack.policy import aware
from ownstack.service import utcnow, create_request
from ownstack.team_scope import project_visible

router = APIRouter(tags=['vendor customers'])


class Body(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class NewCustomer(Body):
    name: str = Field(min_length=2, max_length=100)
    key: str = Field(min_length=2, max_length=80, pattern=r'^[a-z0-9][a-z0-9-]+$')

    @field_validator('name')
    @classmethod
    def nonblank(cls, value):
        if len(value.strip()) < 2:
            raise ValueError('A customer name is required')
        return value.strip()


class Toggle(Body):
    expected_revision: int = Field(ge=1)
    enabled: bool


class LinkProject(Toggle):
    project_id: str = Field(min_length=1, max_length=40)


class Register(Body):
    invitation: str = Field(min_length=40, max_length=128)
    username: str = Field(min_length=3, max_length=40, pattern=r'^[a-z0-9][a-z0-9_-]+$')
    name: str = Field(min_length=2, max_length=100)
    password: str = Field(min_length=12, max_length=128)


class SignIn(Body):
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=128)


class ShareReview(Body):
    discovery_id: str = Field(min_length=1, max_length=40)
    check_id: str = Field(min_length=1, max_length=40)
    evidence_hash: str = Field(pattern=r'^[a-f0-9]{64}$')

class ShareRepositoryReview(Body):
    item_id:str=Field(min_length=1,max_length=40)
    verification_id:str=Field(min_length=1,max_length=40)
    patch_hash:str=Field(pattern=r'^[a-f0-9]{64}$')
    context_hash:str=Field(pattern=r'^[a-f0-9]{64}$')


class Submit(Body):
    project_id: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=10, max_length=3000)
    idempotency_key: str = Field(min_length=8, max_length=80, pattern=r'^[A-Za-z0-9_-]+$')

    @field_validator('text')
    @classmethod
    def nonblank(cls, value):
        if len(value.strip()) < 10:
            raise ValueError('Describe the requested change')
        return value.strip()


def event(db, account, actor, action, **payload):
    db.add(CustomerAudit(id=str(uuid4()), tenant_id=account.tenant_id, customer_id=account.id,
                        actor_id=actor, action=action, payload=payload))


def reserve_vendor(db, tenant_id):
    # SQLite ignores FOR UPDATE. Reserve its writer before customer state reads.
    # PostgreSQL uses a short vendor row lock for these small catalog mutations.
    db.execute(update(Tenant).where(Tenant.id == tenant_id).values(name=Tenant.name))


def account(db, tenant_id, ident, *, lock=False, active=True):
    q = select(CustomerAccount).where(CustomerAccount.id == ident, CustomerAccount.tenant_id == tenant_id)
    if lock:
        q = q.with_for_update(read=True)
    item = db.scalar(q.execution_options(populate_existing=True))
    if item is None or (active and not item.enabled):
        raise HTTPException(404, 'Customer not found')
    return item


def customer_scope(db, tenant_id, customer_id, project_id, *, lock=False):
    a = account(db, tenant_id, customer_id, lock=lock)
    q = select(CustomerProject).join(Project, Project.id == CustomerProject.project_id).where(
        CustomerProject.tenant_id == tenant_id, CustomerProject.customer_id == customer_id,
        CustomerProject.project_id == project_id, CustomerProject.enabled.is_(True), Project.tenant_id == tenant_id)
    if lock:
        q = q.with_for_update(read=True, of=CustomerProject)
    link = db.scalar(q.execution_options(populate_existing=True))
    if link is None:
        raise HTTPException(404, 'Customer project not found')
    return a, link


def request_customer(db, request, *, lock=False):
    """Return current lineage; reactivation never restores an earlier grant."""
    witness = db.get(CustomerRequestLink, request.id, populate_existing=True)
    if witness is None:
        return None
    if witness.tenant_id != request.tenant_id:
        raise HTTPException(409, 'Customer request association changed')
    a, p = customer_scope(db, request.tenant_id, witness.customer_id, request.project_id, lock=lock)
    if (witness.account_revision, witness.project_revision) != (a.revision, p.revision):
        raise HTTPException(409, 'Customer access changed; adopt a fresh request')
    return {'customer_id': a.id, 'account_revision': a.revision, 'project_revision': p.revision}


def bind_requirement(db, item, customer_id):
    a, p = customer_scope(db, item.tenant_id, customer_id, item.project_id, lock=True)
    if item.spec['customer_tenant_id'] != a.id:
        raise HTTPException(422, 'Customer requirement must name the exact customer account ID')
    db.add(CustomerRequirementLink(requirement_id=item.id, tenant_id=item.tenant_id,
        customer_id=a.id, account_revision=a.revision, project_revision=p.revision))


def validate_requirement_customer(db, item):
    witness = db.get(CustomerRequirementLink, item.id, populate_existing=True)
    if witness is None:
        return
    try:
        a, p = customer_scope(db, item.tenant_id, witness.customer_id, item.project_id, lock=True)
    except HTTPException as error:
        raise ValueError('Customer account or project access was removed') from error
    if (witness.tenant_id != item.tenant_id or item.spec['customer_tenant_id'] != a.id or
            (witness.account_revision, witness.project_revision) != (a.revision, p.revision)):
        raise ValueError('Customer authority generation changed; approve a fresh requirement')


def public_account(a):
    return {'id': a.id, 'name': a.name, 'key': a.key, 'enabled': a.enabled, 'revision': a.revision}


@router.get('/v1/customers')
def customers(principal=Depends(current_principal), db=Depends(db_session)):
    require_role(principal, 'admin', 'engineer', 'manager')
    q = select(CustomerAccount).where(CustomerAccount.tenant_id == principal.tenant_id)
    if principal.role != 'admin':
        q = q.where(CustomerAccount.id.in_(select(CustomerProject.customer_id).where(
            CustomerProject.tenant_id == principal.tenant_id, CustomerProject.enabled.is_(True),
            CustomerProject.project_id.in_(select(Project.id).where(project_visible(principal))))))
    return [public_account(a) for a in db.scalars(q.order_by(CustomerAccount.name).limit(200))]


@router.post('/v1/customers', status_code=201)
def new_customer(body: NewCustomer, principal=Depends(current_principal), db=Depends(db_session)):
    require_role(principal, 'admin')
    reserve_vendor(db, principal.tenant_id)
    existing = db.scalar(select(CustomerAccount).where(CustomerAccount.tenant_id == principal.tenant_id, CustomerAccount.key == body.key))
    if existing:
        if existing.name != body.name:
            raise HTTPException(409, 'Customer key is already in use')
        return public_account(existing)
    a = CustomerAccount(id=str(uuid4()), tenant_id=principal.tenant_id, name=body.name, key=body.key)
    db.add(a); db.flush(); event(db, a, principal.user_id, 'customer.created')
    db.commit()
    return public_account(a)


@router.post('/v1/customers/{ident}/status')
def customer_status(ident: str, body: Toggle, principal=Depends(current_principal), db=Depends(db_session)):
    require_role(principal, 'admin'); reserve_vendor(db, principal.tenant_id)
    a = account(db, principal.tenant_id, ident, active=False)
    if a.revision != body.expected_revision:
        raise HTTPException(409, 'Customer changed; refresh first')
    if a.enabled != body.enabled:
        a.enabled = body.enabled; a.revision += 1
        event(db, a, principal.user_id, 'customer.status', enabled=a.enabled, revision=a.revision)
    db.commit()
    return public_account(a)


@router.get('/v1/customers/{ident}/projects')
def linked_projects(ident: str, principal=Depends(current_principal), db=Depends(db_session)):
    require_role(principal, 'admin', 'engineer', 'manager'); account(db, principal.tenant_id, ident, active=False)
    return [{'id': p.project_id, 'name': name, 'enabled': p.enabled, 'revision': p.revision}
        for p, name in db.execute(select(CustomerProject, Project.name).join(Project, Project.id == CustomerProject.project_id)
        .where(CustomerProject.customer_id == ident, CustomerProject.tenant_id == principal.tenant_id, project_visible(principal)))]


@router.post('/v1/customers/{ident}/projects')
def link_project(ident: str, body: LinkProject, principal=Depends(current_principal), db=Depends(db_session)):
    require_role(principal, 'admin')
    from ownstack.release_assurance import lock_project
    project = lock_project(db, principal, body.project_id)
    a = account(db, principal.tenant_id, ident, lock=True)
    p = db.scalar(select(CustomerProject).where(CustomerProject.customer_id == a.id, CustomerProject.project_id == project.id).with_for_update())
    if p is None:
        if body.expected_revision != 1 or not body.enabled:
            raise HTTPException(409, 'New project links start enabled at revision one')
        p = CustomerProject(id=str(uuid4()), tenant_id=a.tenant_id, customer_id=a.id, project_id=project.id)
        db.add(p); db.flush()
    else:
        if p.revision != body.expected_revision:
            raise HTTPException(409, 'Customer project changed; refresh first')
        if p.enabled != body.enabled:
            p.enabled = body.enabled; p.revision += 1
    event(db, a, principal.user_id, 'customer.project', project_id=project.id, enabled=p.enabled, revision=p.revision)
    db.commit()
    return {'id': project.id, 'enabled': p.enabled, 'revision': p.revision}


@router.post('/v1/customers/{ident}/invitations', status_code=201)
def invite(ident: str, principal=Depends(current_principal), db=Depends(db_session)):
    require_role(principal, 'admin'); reserve_vendor(db, principal.tenant_id)
    a = account(db, principal.tenant_id, ident)
    token = secrets.token_urlsafe(32)
    i = CustomerInvitation(id=str(uuid4()), tenant_id=a.tenant_id, customer_id=a.id, account_revision=a.revision,
        token_hash=hash_secret(token), expires_at=utcnow() + timedelta(hours=24))
    db.add(i); event(db, a, principal.user_id, 'customer.invited', invitation_id=i.id)
    db.commit()
    # One-time bearer invitation is shown only to the creating administrator.
    return {'id': i.id, 'invitation': token, 'expires_at': aware(i.expires_at).isoformat()}


@router.post('/v1/customers/{ident}/invitations/{invitation_id}/revoke')
def revoke_invitation(ident: str, invitation_id: str, principal=Depends(current_principal), db=Depends(db_session)):
    require_role(principal, 'admin'); reserve_vendor(db, principal.tenant_id)
    a = account(db, principal.tenant_id, ident, active=False)
    i = db.scalar(select(CustomerInvitation).where(CustomerInvitation.id == invitation_id,
        CustomerInvitation.tenant_id == a.tenant_id, CustomerInvitation.customer_id == a.id))
    if i is None:
        raise HTTPException(404, 'Not found')
    i.used = True; event(db, a, principal.user_id, 'customer.invitation_revoked', invitation_id=i.id)
    db.commit()
    return {'revoked': True}


@router.get('/v1/customers/{ident}/people')
def customer_people(ident: str, principal=Depends(current_principal), db=Depends(db_session)):
    require_role(principal, 'admin'); a = account(db, principal.tenant_id, ident, active=False)
    return [{'id': p.id, 'name': p.name, 'enabled': p.enabled, 'revision': p.revision} for p in
        db.scalars(select(CustomerIdentity).where(CustomerIdentity.tenant_id == a.tenant_id, CustomerIdentity.customer_id == a.id))]


@router.post('/v1/customers/{ident}/people/{person_id}/status')
def contact_status(ident: str, person_id: str, body: Toggle, principal=Depends(current_principal), db=Depends(db_session)):
    require_role(principal, 'admin'); reserve_vendor(db, principal.tenant_id)
    a = account(db, principal.tenant_id, ident, active=False)
    p = db.scalar(select(CustomerIdentity).where(CustomerIdentity.id == person_id,
        CustomerIdentity.tenant_id == a.tenant_id, CustomerIdentity.customer_id == a.id))
    if p is None:
        raise HTTPException(404, 'Not found')
    if p.revision != body.expected_revision:
        raise HTTPException(409, 'Contact changed; refresh first')
    if p.enabled != body.enabled:
        p.enabled = body.enabled; p.revision += 1
        event(db, a, principal.user_id, 'customer.contact_status', identity_id=p.id, enabled=p.enabled, revision=p.revision)
    db.commit()
    return {'id': p.id, 'enabled': p.enabled, 'revision': p.revision}


def issue_session(db, person):
    a = account(db, person.tenant_id, person.customer_id)
    token = 'customer_' + secrets.token_urlsafe(32)
    db.add(CustomerSession(token_hash=hash_secret(token), identity_id=person.id, identity_revision=person.revision,
        account_revision=a.revision, expires_at=utcnow() + timedelta(hours=8)))
    return {'token': token, 'name': person.name, 'customer': public_account(a)}


@router.post('/v1/customer-portal/register', status_code=201)
def register(body: Register, request: Request, db=Depends(db_session)):
    rate_limit(db, 'customer-register', request.client.host if request.client else 'unknown', 10, 3600)
    invitation = db.scalar(select(CustomerInvitation).where(CustomerInvitation.token_hash == hash_secret(body.invitation)))
    if invitation is None:
        raise HTTPException(404, 'Invitation unavailable')
    reserve_vendor(db, invitation.tenant_id); db.refresh(invitation)
    a = account(db, invitation.tenant_id, invitation.customer_id)
    if invitation.used or aware(invitation.expires_at) <= utcnow() or invitation.account_revision != a.revision:
        raise HTTPException(409, 'Invitation expired, used or superseded')
    if db.scalar(select(CustomerIdentity.id).where(CustomerIdentity.username == body.username)):
        raise HTTPException(409, 'Username unavailable')
    person = CustomerIdentity(id=str(uuid4()), tenant_id=a.tenant_id, customer_id=a.id,
        username=body.username, name=body.name.strip(), password_hash=password_hash(body.password))
    db.add(person)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Username unavailable') from None
    invitation.used = True
    event(db, a, person.id, 'customer.registered')
    result = issue_session(db, person); db.commit()
    return result


@router.post('/v1/customer-portal/session')
def customer_login(body: SignIn, request: Request, db=Depends(db_session)):
    rate_limit(db, 'customer-login-ip', request.client.host if request.client else 'unknown', 15, 60)
    rate_limit(db, 'customer-login-name', body.username, 8, 60)
    person = db.scalar(select(CustomerIdentity).where(CustomerIdentity.username == body.username))
    if person is None or not check_password(body.password, person.password_hash) or not person.enabled:
        raise HTTPException(401, 'Invalid customer sign-in')
    a = db.get(CustomerAccount, person.customer_id)
    if a is None or not a.enabled:
        raise HTTPException(401, 'Invalid customer sign-in')
    result = issue_session(db, person); db.commit()
    return result


def customer_identity(authorization: str | None = Header(default=None), db=Depends(db_session)):
    token = (authorization or '').removeprefix('Bearer ')
    if not token.startswith('customer_') or len(token) > 128:
        raise HTTPException(401, 'Customer sign-in required')
    session = db.get(CustomerSession, hash_secret(token), populate_existing=True)
    person = db.get(CustomerIdentity, session.identity_id, populate_existing=True) if session else None
    a = db.get(CustomerAccount, person.customer_id, populate_existing=True) if person else None
    if (session is None or aware(session.expires_at) <= utcnow() or person is None or not person.enabled or
            a is None or not a.enabled or a.tenant_id != person.tenant_id or
            session.identity_revision != person.revision or session.account_revision != a.revision):
        raise HTTPException(401, 'Customer session expired or revoked')
    return person


@router.get('/v1/customer-portal/me')
def customer_me(person=Depends(customer_identity), db=Depends(db_session)):
    a = account(db, person.tenant_id, person.customer_id)
    projects = db.execute(select(Project.id, Project.name).join(CustomerProject, CustomerProject.project_id == Project.id).where(
        Project.tenant_id == person.tenant_id, CustomerProject.tenant_id == person.tenant_id,
        CustomerProject.customer_id == a.id, CustomerProject.enabled.is_(True))).all()
    return {'name': person.name, 'customer': public_account(a), 'projects': [{'id': i, 'name': n} for i, n in projects]}


@router.post('/v1/customer-portal/logout')
def customer_logout(authorization: str | None = Header(default=None), person=Depends(customer_identity), db=Depends(db_session)):
    session = db.get(CustomerSession, hash_secret(authorization.removeprefix('Bearer ')))
    db.delete(session); db.commit()
    return {'signed_out': True}


@router.post('/v1/customer-portal/requests', status_code=201)
def submit(body: Submit, authorization: str | None = Header(default=None), person=Depends(customer_identity), db=Depends(db_session)):
    reserve_vendor(db, person.tenant_id)
    person = customer_identity(authorization, db)  # Revalidate after waiting for another writer.
    a, _ = customer_scope(db, person.tenant_id, person.customer_id, body.project_id, lock=True)
    existing = db.scalar(select(CustomerSubmission).where(CustomerSubmission.identity_id == person.id,
                                                         CustomerSubmission.idempotency_key == body.idempotency_key))
    if existing:
        if (existing.text, existing.project_id) != (body.text, body.project_id):
            raise HTTPException(409, 'Request key belongs to different inputs')
        return public_submission(db, existing)
    item = CustomerSubmission(id=str(uuid4()), tenant_id=a.tenant_id, customer_id=a.id,
        identity_id=person.id, project_id=body.project_id, text=body.text, idempotency_key=body.idempotency_key)
    db.add(item); db.flush(); event(db, a, person.id, 'customer.request_submitted', submission_id=item.id)
    result = public_submission(db, item); db.commit()
    return result


def public_submission(db, item):
    linked = db.scalar(select(CustomerRequestLink).where(CustomerRequestLink.submission_id == item.id))
    # Deliberate allowlist. No code, guidance, model history, staff identities,
    # verdict, internal request ID or inferred release claim reaches customers.
    shared = db.scalar(select(CustomerAudit).where(CustomerAudit.tenant_id == item.tenant_id,
        CustomerAudit.customer_id == item.customer_id, CustomerAudit.action == 'customer.review_shared',
        CustomerAudit.payload['submission_id'].as_string() == item.id).order_by(CustomerAudit.created_at.desc()).limit(1))
    return {'id': item.id, 'project_id': item.project_id, 'text': item.text,
            'status': 'with_engineering' if linked else 'received', 'revision': item.revision,
            'created_at': aware(item.created_at).isoformat(), 'released': False,
            'review_update': 'A candidate was reviewed for manual release. Release is not confirmed.' if shared else None}


@router.get('/v1/customer-portal/requests')
def my_submissions(person=Depends(customer_identity), db=Depends(db_session)):
    return [public_submission(db, i) for i in db.scalars(select(CustomerSubmission).where(
        CustomerSubmission.tenant_id == person.tenant_id, CustomerSubmission.customer_id == person.customer_id,
        CustomerSubmission.identity_id == person.id).order_by(CustomerSubmission.created_at.desc()).limit(200))]


@router.get('/v1/customers/inbox/requests')
def inbox(principal=Depends(current_principal), db=Depends(db_session)):
    require_role(principal, 'admin', 'engineer', 'manager')
    rows = db.scalars(select(CustomerSubmission).where(CustomerSubmission.tenant_id == principal.tenant_id,
        CustomerSubmission.project_id.in_(select(Project.id).where(project_visible(principal))))
        .order_by(CustomerSubmission.created_at.desc()).limit(200))
    return [{**public_submission(db, i), 'customer_id': i.customer_id,
             'request_id': db.scalar(select(CustomerRequestLink.request_id).where(CustomerRequestLink.submission_id == i.id))} for i in rows]


@router.post('/v1/customers/inbox/{ident}/adopt')
def adopt(ident: str, principal=Depends(current_principal), db=Depends(db_session)):
    require_role(principal, 'admin', 'engineer')
    item = db.scalar(select(CustomerSubmission).where(CustomerSubmission.id == ident,
        CustomerSubmission.tenant_id == principal.tenant_id,
        CustomerSubmission.project_id.in_(select(Project.id).where(project_visible(principal)))))
    if item is None:
        raise HTTPException(404, 'Not found')
    from ownstack.release_assurance import lock_project
    lock_project(db, principal, item.project_id)
    a, p = customer_scope(db, item.tenant_id, item.customer_id, item.project_id, lock=True)
    linked = db.scalar(select(CustomerRequestLink).where(CustomerRequestLink.submission_id == item.id))
    if linked:
        return {'request_id': linked.request_id, 'customer_id': a.id}
    result = create_request(db, principal, {'text': item.text, 'kind': 'feature', 'project_id': item.project_id}, 'customer-' + item.id)
    db.add(CustomerRequestLink(request_id=result['id'], submission_id=item.id, tenant_id=a.tenant_id,
        customer_id=a.id, account_revision=a.revision, project_revision=p.revision))
    event(db, a, principal.user_id, 'customer.request_adopted', submission_id=item.id, request_id=result['id'])
    db.commit()
    return {'request_id': result['id'], 'customer_id': a.id}


@router.post('/v1/customers/inbox/{ident}/share-review')
def share_review(ident: str, body: ShareReview, principal=Depends(current_principal), db=Depends(db_session)):
    require_role(principal, 'admin', 'engineer')
    from ownstack.change_agent import review_item
    from ownstack.release_assurance import context_valid
    state, check, project = review_item(db, principal, body.discovery_id, body.check_id, True)
    linked = db.scalar(select(CustomerRequestLink).where(CustomerRequestLink.submission_id == ident,
        CustomerRequestLink.tenant_id == principal.tenant_id, CustomerRequestLink.request_id == state['request_id']))
    if linked is None:
        raise HTTPException(404, 'Not found')
    request_customer(db, db.get(ChangeRequest, linked.request_id), lock=True)
    if check.decision != 'accept_for_manual_release' or check.evidence_hash != body.evidence_hash:
        raise HTTPException(409, 'Exact accepted review required')
    try:
        context_valid(db, check)
    except ValueError:
        raise HTTPException(409, 'Review is no longer current') from None
    a = account(db, principal.tenant_id, linked.customer_id)
    previous = db.scalars(select(CustomerAudit).where(CustomerAudit.customer_id == a.id,
        CustomerAudit.action == 'customer.review_shared')).all()
    if not any(r.payload == {'submission_id': ident, 'check_id': check.id, 'evidence_hash': check.evidence_hash} for r in previous):
        event(db, a, principal.user_id, 'customer.review_shared', submission_id=ident,
              check_id=check.id, evidence_hash=check.evidence_hash)
    db.commit()
    return {'shared': True, 'released': False}


@router.post('/v1/customers/inbox/{ident}/share-repository-review')
def share_repository_review(ident:str,body:ShareRepositoryReview,principal=Depends(current_principal),db=Depends(db_session)):
    require_role(principal,'engineer')
    from ownstack.models import EngineeringItem
    from ownstack.service import scoped
    from ownstack.repository_cockpit import matching,context_hash,current_context
    item=scoped(db,EngineeringItem,body.item_id,principal.tenant_id,actor=principal,write=True)
    linked=db.scalar(select(CustomerRequestLink).where(CustomerRequestLink.submission_id==ident,
        CustomerRequestLink.tenant_id==principal.tenant_id,CustomerRequestLink.request_id==item.request_id))
    if linked is None:raise HTTPException(404,'Not found')
    current_context(db,item)
    if (item.human_decision!='accept_for_manual_release' or item.patch_hash!=body.patch_hash
        or item.patch.get('_verification_id')!=body.verification_id or context_hash(item)!=body.context_hash or not matching(db,item)):
        raise HTTPException(409,'Exact current reviewed repository evidence required')
    a=account(db,principal.tenant_id,linked.customer_id)
    payload={'submission_id':ident,'item_id':item.id,'verification_id':body.verification_id,'patch_hash':body.patch_hash}
    previous=db.scalars(select(CustomerAudit).where(CustomerAudit.customer_id==a.id,CustomerAudit.action=='customer.review_shared')).all()
    if not any(r.payload==payload for r in previous):event(db,a,principal.user_id,'customer.review_shared',**payload)
    db.commit();return {'shared':True,'released':False}
