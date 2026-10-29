"""Bounded visibility discovery and independently generated counterexamples.

This is one explicit application profile, not an oracle for arbitrary software.
Models may choose questions and propose repairs, never alter approved semantics.
"""
from datetime import datetime,timedelta,timezone
from itertools import product
from pathlib import Path
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,field_validator
from ownstack.policy import digest
from ownstack.release_contracts import VisibilityInput,VisibilityExpectation,VisibilityCase,RequirementSpec

FIELDS=('roles','requires_assignment','temporary_grants','visible_fields','denial_status')
ROLES=('anonymous','contractor','member','engineer','manager','admin')
QUESTIONS={
 'roles':'Which application roles may read without a temporary grant?',
 'requires_assignment':'Must those people also be assigned to the resource?',
 'temporary_grants':'May a valid temporary grant allow an otherwise denied authenticated person?',
 'visible_fields':'Exactly which public fields may an allowed read return?',
 'denial_status':'Should an ordinary denied read return403 or404? Cross-tenant reads always return404.',
}

def workflow_identity():
    return digest({name:Path(__file__).with_name(name).read_text() for name in
        ('change_agent_contracts.py','change_agent.py','counterexample_loop.py','change_agent_model.py',
         'repository_registry.py','customers.py','customer_models.py','source_proposals.py','repair_contracts.py')})

class VisibilityPolicy(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid',frozen=True)
    roles:list[Literal['anonymous','contractor','member','engineer','manager','admin']]=Field(min_length=1,max_length=6)
    requires_assignment:bool
    temporary_grants:bool
    visible_fields:list[str]=Field(min_length=1,max_length=16)
    denial_status:Literal[403,404]

    @field_validator('roles')
    @classmethod
    def unique_roles(cls,value):
        if len(set(value))!=len(value):raise ValueError('Distinct roles required')
        if 'anonymous' in value:raise ValueError('This profile never authorizes anonymous access')
        return sorted(value)

    @field_validator('visible_fields')
    @classmethod
    def public_fields(cls,value):
        return list(VisibilityExpectation(status_code=200,visible_fields=tuple(value)).visible_fields)

    @field_validator('denial_status',mode='before')
    @classmethod
    def actual_integer(cls,value):
        if type(value) is not int:raise ValueError('Integer status required')
        return value


def checked_answers(value):
    """Validate partial answers using the exact complete-policy validators."""
    if not isinstance(value,dict) or set(value)-set(FIELDS):raise ValueError('Unknown clarification answer')
    defaults={'roles':['manager'],'requires_assignment':True,'temporary_grants':False,'visible_fields':['id'],'denial_status':403}
    policy=VisibilityPolicy.model_validate({**defaults,**value}).model_dump()
    return {key:policy[key] for key in value}


def expected(policy:VisibilityPolicy,context:VisibilityInput):
    if context.actor_tenant_id!=context.resource_tenant_id:return VisibilityExpectation(status_code=404,visible_fields=())
    authenticated=context.actor_role!='anonymous'
    role=context.actor_role in policy.roles and (context.assigned or not policy.requires_assignment)
    grant=(policy.temporary_grants and context.grant_starts_at is not None and not context.grant_revoked
        and context.grant_starts_at<=context.at<context.grant_expires_at)
    allowed=authenticated and (role or grant)
    return VisibilityExpectation(status_code=200 if allowed else policy.denial_status,
        visible_fields=tuple(policy.visible_fields) if allowed else ())


def counterexample_requirements(policy:VisibilityPolicy,*,session_id:str,customer:str,owner:str,source_ref:str):
    """144 reviewed inputs over a declared domain, partitioned below existing bounds.

    Every generated expectation follows the human-approved policy. Candidate code
    never receives these expectations. This finite domain is not exhaustive.
    """
    at=datetime(2026,10,28,12,tzinfo=timezone.utc);cases=[]
    for role,assigned,foreign,grant in product(ROLES,(False,True),(False,True),('none','future','start','active','expiry','revoked')):
        start=end=None
        if grant!='none':
            start=at+timedelta(seconds=1) if grant=='future' else at if grant=='start' else at-timedelta(seconds=1)
            end=at if grant=='expiry' else at+timedelta(seconds=2)
        context=VisibilityInput(actor_id='actor-'+role,actor_tenant_id=customer,actor_role=role,
            resource_id='document-one',resource_tenant_id=customer+'-other' if foreign else customer,
            assigned=assigned,at=at,grant_starts_at=start,grant_expires_at=end,grant_revoked=grant=='revoked')
        cases.append(VisibilityCase(case_id=f'c{len(cases):03}',title=f'{role}, assigned={assigned}, foreign={foreign}, grant={grant}',
            kind='control' if foreign else 'target',input=context,expected=expected(policy,context)))
    return [RequirementSpec(key=f'agent-{session_id}-{i//60}',version=1,customer_tenant_id=customer,
        title='Reviewed visibility policy counterexamples',source_ref=source_ref,owner_id=owner,cases=tuple(cases[i:i+60]))
        for i in range(0,len(cases),60)]


class EvidenceQuote(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid')
    field:Literal['roles','requires_assignment','temporary_grants','visible_fields','denial_status']
    source:str=Field(min_length=1,max_length=240)
    quote:str=Field(min_length=2,max_length=300)

class AgentDecision(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid')
    action:Literal['ask','suggest_answers','propose']
    field:Literal['roles','requires_assignment','temporary_grants','visible_fields','denial_status']|None=None
    reason:str=Field(min_length=5,max_length=1000)
    citations:list[str]=Field(min_length=1,max_length=10)
    facts:dict=Field(default_factory=dict,max_length=5)
    quotes:list[EvidenceQuote]=Field(default_factory=list,max_length=10)


def validate_decision(raw,state,sources,ticket=None):
    from ownstack.model_contracts import strict_json
    value=AgentDecision.model_validate(strict_json(raw,limit=12000) if isinstance(raw,str) else raw)
    missing=[key for key in FIELDS if key not in state['answers']]
    if any(ref not in {'request',*sources} for ref in value.citations):raise ValueError('Unobserved citation')
    if value.action=='ask' and value.field not in missing:raise ValueError('Question must resolve an unanswered field')
    if value.action=='propose' and (missing or value.field is not None):raise ValueError('Unresolved requirements cannot become a proposal')
    if value.action!='suggest_answers' and (value.facts or value.quotes):raise ValueError('Only explicit suggestions carry unconfirmed facts')
    if value.action=='suggest_answers':
        facts=checked_answers(value.facts)
        if not facts or set(facts)-set(missing) or value.field is not None:raise ValueError('Suggestions must concern unanswered fields')
        evidence={'request':ticket,**sources};cited=set()
        for q in value.quotes:
            if q.field not in facts or q.source not in value.citations or not evidence.get(q.source) or q.quote not in evidence[q.source]:raise ValueError('Unobserved quoted evidence')
            cited.add(q.field)
        if cited!=set(facts):raise ValueError('Every proposed answer needs a source quote and human confirmation')
        value.facts=facts
    return value.model_dump()


def policy_hash(state):
    return digest({'request_id':state['request_id'],'request_revision':state['request_revision'],
        'workflow':state['workflow'],'repository':state.get('repository'),
        'source_sha256':state['source_sha256'],'code_hash':state['code_hash'],
        'policy':VisibilityPolicy.model_validate(state['answers']).model_dump()})
