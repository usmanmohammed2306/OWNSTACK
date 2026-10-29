"""Host-owned two-person approval, never a model-authored policy."""
from datetime import timedelta
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select,func,or_
from sqlalchemy.orm import Session
from ownstack.auth import current_principal,db_session,require_role
from ownstack.models import ApprovalWitness,Tenant,User,Variation,Proposal,VariationWitness,Team,TeamMembership
from ownstack.policy import Principal

router=APIRouter(prefix='/v1/governance')

def authorized_variation():
    """One correlated predicate shared by enforcement and every policy preview.

    Quorum is captured on activation. Changing the workspace's future approval
    policy does not silently reinterpret existing one-person grants.
    """
    live=select(func.count(func.distinct(ApprovalWitness.actor_id))).select_from(ApprovalWitness).join(User,User.id==ApprovalWitness.actor_id).join(
        VariationWitness,VariationWitness.witness_id==ApprovalWitness.id).where(
        VariationWitness.variation_id==Variation.id,VariationWitness.tenant_id==Variation.tenant_id,
        ApprovalWitness.proposal_id==Variation.proposal_id,ApprovalWitness.tenant_id==Variation.tenant_id,
        ApprovalWitness.proposal_hash==select(Proposal.proposal_hash).where(Proposal.id==Variation.proposal_id).correlate(Variation).scalar_subquery(),
        User.tenant_id==Variation.tenant_id,User.enabled.is_(True),User.role=='admin',
        User.token_version==ApprovalWitness.identity_version).correlate(Variation).scalar_subquery()
    return or_(Variation.approval_quorum==1,live>=Variation.approval_quorum)

def current_witnesses(db,proposal,request,at):
    # Lock the selected signers and membership rows until activation commits.
    # A concurrent identity/team revocation therefore has a definite ordering.
    return db.scalars(select(ApprovalWitness).join(User,User.id==ApprovalWitness.actor_id).join(
        TeamMembership,(TeamMembership.user_id==User.id)&(TeamMembership.tenant_id==User.tenant_id)).join(
        Team,(Team.id==TeamMembership.team_id)&(Team.tenant_id==TeamMembership.tenant_id)).where(
        TeamMembership.team_id==request.team_id,TeamMembership.tenant_id==request.tenant_id,
        TeamMembership.enabled.is_(True),TeamMembership.role.in_(['member','manager']),Team.enabled.is_(True),
        ApprovalWitness.proposal_id==proposal.id,ApprovalWitness.tenant_id==request.tenant_id,
        ApprovalWitness.proposal_hash==proposal.proposal_hash,User.tenant_id==request.tenant_id,
        User.enabled.is_(True),User.role=='admin',User.token_version==ApprovalWitness.identity_version,
        User.id!=request.requester_id,ApprovalWitness.created_at>=at-timedelta(minutes=15))
        .order_by(User.id,ApprovalWitness.id).with_for_update(read=True,of=(User,TeamMembership))).all()

class Policy(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    approval_quorum:int=Field(ge=1,le=2)
    expected_quorum:int=Field(ge=1,le=2)

@router.get('')
def policy(principal:Principal=Depends(current_principal),db:Session=Depends(db_session)):
    require_role(principal,'admin','engineer')
    return {'approval_quorum':db.get(Tenant,principal.tenant_id).approval_quorum,
        'scope':'Future temporary-access proposals; existing active grants retain their captured policy.',
        'requester_may_approve':db.get(Tenant,principal.tenant_id).approval_quorum==1}

@router.post('')
def configure(body:Policy,principal:Principal=Depends(current_principal),db:Session=Depends(db_session)):
    require_role(principal,'admin')
    row=db.scalar(select(Tenant).where(Tenant.id==principal.tenant_id).with_for_update(key_share=True))
    if row.approval_quorum!=body.expected_quorum:raise HTTPException(409,'Approval policy changed; refresh before saving')
    if body.approval_quorum==2:
        count=db.scalar(select(func.count()).select_from(User).where(User.tenant_id==principal.tenant_id,User.enabled.is_(True),User.role=='admin'))
        if count<2:raise HTTPException(409,'Provision at least two distinct administrators before enabling this policy')
    row.approval_quorum=body.approval_quorum
    # A tenant event with no request is intentionally not put in the request outbox.
    from ownstack.models import IdentityEvent
    from uuid import uuid4
    db.add(IdentityEvent(id=str(uuid4()),tenant_id=principal.tenant_id,actor_id=principal.user_id,
        subject_id=principal.user_id,action='approval_quorum_'+str(body.approval_quorum)))
    db.commit();return {'approval_quorum':row.approval_quorum,'effect':'future_proposals_only'}
