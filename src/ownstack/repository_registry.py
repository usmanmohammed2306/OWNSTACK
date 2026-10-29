"""Project-owned repository connections and explicit customer associations.

Append-only project audit state provides durable revisions without reclassifying
legacy sources. Registration is metadata, not proof of execution or GitHub access.
Only installed, reviewed execution profiles can run; no URL, shell or host path
is accepted by these API routes.
"""
from copy import deepcopy
from typing import Literal
from uuid import uuid4
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select,update
from ownstack.auth import current_principal,db_session,require_role
from ownstack.models import ReleaseAudit,Project,EngineeringItem
from ownstack.release_assurance import enabled,lock_project,audit,visible_projects
from ownstack.team_scope import require_project
from ownstack.customers import customer_scope,request_customer
from ownstack.policy import digest

router=APIRouter(prefix='/v1/repositories',tags=['customer repository onboarding'],dependencies=[Depends(enabled)])

class Body(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid')

class Register(Body):
    project_id:str=Field(min_length=1,max_length=40)
    key:str=Field(min_length=2,max_length=60,pattern=r'^[a-z0-9][a-z0-9-]+$')
    label:str=Field(min_length=2,max_length=80,pattern=r'^[A-Za-z0-9][A-Za-z0-9 ._/-]+$')
    kind:Literal['python','pinned']
    source_sha256:str|None=Field(default=None,pattern=r'^[a-f0-9]{64}$')
    case_id:str|None=Field(default=None,min_length=1,max_length=100)

class Version(Body):
    expected_revision:int=Field(ge=1,strict=True)

class Toggle(Version):
    enabled:bool

class CustomerLink(Toggle):
    customer_id:str=Field(min_length=1,max_length=40)

class Handoff(Body):
    request_id:str=Field(min_length=1,max_length=40)
    repository_id:str=Field(min_length=1,max_length=40)


def states(db,project):
    rows=db.scalars(select(ReleaseAudit).where(ReleaseAudit.tenant_id==project.tenant_id,
        ReleaseAudit.project_id==project.id,ReleaseAudit.action=='repository.state').limit(5001)).all()
    if len(rows)>5000:raise HTTPException(409,'Repository history limit reached; preserve history for operator review')
    latest={}
    for row in rows:
        value=row.payload['state']
        if value['id'] not in latest or value['revision']>latest[value['id']]['revision']:latest[value['id']]=deepcopy(value)
    return latest


def load(db,tenant_id,project_id,ident):
    project=db.get(Project,project_id,populate_existing=True)
    if project is None or project.tenant_id!=tenant_id:raise HTTPException(404,'Not found')
    state=states(db,project).get(ident)
    if state is None:raise HTTPException(404,'Not found')
    return state


def persist(db,project,state,actor,action):
    if state['revision']>100:raise HTTPException(409,'Repository revision limit reached; preserve history before replacement')
    audit(db,project,state['id'],'repository.state',state=deepcopy(state))
    audit(db,project,state['id'],action,actor=actor,revision=state['revision'])


def witness(db,req,ident,*,kind=None,source_sha256=None):
    # A registry publication and a check/review must observe a legal ordering.
    # Acquire the same project lock before reading append-only registry state.
    if db.get_bind().dialect.name=='sqlite':
        db.execute(update(Project).where(Project.id==req.project_id,Project.tenant_id==req.tenant_id)
            .values(revision=Project.revision).execution_options(synchronize_session=False))
    db.scalar(select(Project).where(Project.id==req.project_id,Project.tenant_id==req.tenant_id)
        .with_for_update(key_share=True).execution_options(populate_existing=True))
    state=load(db,req.tenant_id,req.project_id,ident)
    if not state['enabled']:raise HTTPException(409,'Repository connection is disabled')
    if kind and state['kind']!=kind:raise HTTPException(422,'Choose a repository with the matching execution profile')
    if source_sha256 and state['source'].get('sha256')!=source_sha256:raise HTTPException(409,'Source differs from the registered repository version')
    customer=request_customer(db,req,lock=True)
    binding=None
    if customer:
        binding=state['customers'].get(customer['customer_id'])
        if not binding or not binding['enabled'] or any(binding.get(k)!=v for k,v in customer.items()):
            raise HTTPException(409,'Connect this customer to the current repository version first')
    return {'repository_id':state['id'],'revision':state['revision'],'source':deepcopy(state['source']),
            'customer':deepcopy(binding),'kind':state['kind']}


def validate_witness(db,req,value):
    if not value:raise HTTPException(409,'Repository connection witness is missing')
    current=witness(db,req,value['repository_id'],kind=value['kind'])
    if current!=value:raise HTTPException(409,'Repository or customer connection changed; reconnect and run fresh checks')
    return current


def connection_required(db,req):
    return bool(request_customer(db,req,lock=True))


def source_check_witness(db,project,baseline_sha256,requirement_ids):
    """Caller holds the project lock. Legacy checks cannot bypass onboarding.

    Existing projects without a registry remain compatible. Once configured,
    customer-bound comparisons need one exact active Python source connection
    covering every customer in the approved suite, not a browser-supplied claim.
    """
    from ownstack.customer_models import CustomerRequirementLink
    customers=sorted(set(db.scalars(select(CustomerRequirementLink.customer_id).where(
        CustomerRequirementLink.tenant_id==project.tenant_id,CustomerRequirementLink.requirement_id.in_(requirement_ids))).all()))
    registered=states(db,project)
    if not customers or not registered:return None
    for state in sorted(registered.values(),key=lambda s:s['id']):
        if not state['enabled'] or state['kind']!='python' or state['source']['sha256']!=baseline_sha256:continue
        witnesses=[]
        for ident in customers:
            a,p=customer_scope(db,project.tenant_id,ident,project.id,lock=True)
            expected={'customer_id':a.id,'account_revision':a.revision,'project_revision':p.revision,'enabled':True}
            if state['customers'].get(a.id)!=expected:break
            witnesses.append(expected)
        else:
            return {'repository_id':state['id'],'revision':state['revision'],'source_sha256':baseline_sha256,'customers':witnesses}
    raise ValueError('No active exact Python repository covers these customer requirements; use the connected repository workflow')


@router.get('')
def list_repositories(project_id:str|None=None,customer_id:str|None=None,principal=Depends(current_principal),db=Depends(db_session)):
    require_role(principal,'admin','engineer','manager')
    projects=db.scalars(select(Project).where(Project.id.in_(visible_projects(principal)))).all()
    result=[]
    for project in projects:
        if project_id and project.id!=project_id:continue
        for state in states(db,project).values():
            if customer_id and customer_id not in state['customers']:continue
            result.append(state)
    return sorted(result,key=lambda r:(r['label'],r['id']))


@router.post('',status_code=201)
def register(body:Register,principal=Depends(current_principal),db=Depends(db_session)):
    require_role(principal,'admin','engineer');project=lock_project(db,principal,body.project_id)
    if body.kind=='pinned':
        if body.source_sha256 or not body.case_id:raise HTTPException(422,'A pinned repository requires only a reviewed case ID')
        from ownstack.repository_cockpit import catalog
        case=catalog().get(body.case_id)
        if case is None:raise HTTPException(422,'No installed reviewed profile for this repository case')
        source={k:case[k] for k in ('repo','base_commit','source_url','profile','required_tests_sha256','test_patch_sha256')}
        source['case_id']=case['id']
    else:
        if body.case_id or not body.source_sha256:raise HTTPException(422,'A Python repository requires only a registered source snapshot')
        rows=db.scalars(select(ReleaseAudit).where(ReleaseAudit.tenant_id==project.tenant_id,
            ReleaseAudit.project_id==project.id,ReleaseAudit.action=='source.registered')).all()
        found=next((r.payload['snapshot'] for r in rows if r.payload['snapshot']['sha256']==body.source_sha256),None)
        if found is None:raise HTTPException(409,'Onboard the selected source inventory before connecting it')
        source={'sha256':found['sha256'],'profile':found['profile'],'name':found['config']['name']}
    catalog_states=states(db,project)
    existing=next((s for s in catalog_states.values() if s['key']==body.key),None)
    if existing:
        if (existing['kind'],existing['source'],existing['label'])!=(body.kind,source,body.label):raise HTTPException(409,'Repository key belongs to a different source version')
        return existing
    if len(catalog_states)>=50:raise HTTPException(409,'Project repository limit reached')
    state={'id':str(uuid4()),'tenant_id':project.tenant_id,'project_id':project.id,'key':body.key,
        'label':body.label,'kind':body.kind,'source':source,'revision':1,'enabled':True,'customers':{},
        'registration_proof':'Metadata only; actual source and execution are verified by the independent operator.'}
    persist(db,project,state,principal.user_id,'repository.registered');db.commit();return state


def editable(db,principal,ident):
    require_role(principal,'admin','engineer')
    row=db.scalar(select(ReleaseAudit).where(ReleaseAudit.subject_id==ident,ReleaseAudit.tenant_id==principal.tenant_id,
        ReleaseAudit.project_id.in_(visible_projects(principal)),ReleaseAudit.action=='repository.state').limit(1))
    if row is None:raise HTTPException(404,'Not found')
    project=lock_project(db,principal,row.project_id)
    return project,load(db,principal.tenant_id,project.id,ident)


@router.post('/{ident}/customers')
def connect_customer(ident:str,body:CustomerLink,principal=Depends(current_principal),db=Depends(db_session)):
    project,state=editable(db,principal,ident)
    if state['revision']!=body.expected_revision:raise HTTPException(409,'Repository changed; refresh first')
    if body.enabled and state['kind']=='pinned' and state['source']['case_id']!='pallets__flask-4160':
        raise HTTPException(422,'Customer compatibility currently supports the reviewed Flask Decimal profile only')
    a,p=customer_scope(db,principal.tenant_id,body.customer_id,project.id,lock=True)
    previous=state['customers'].get(a.id)
    binding={'customer_id':a.id,'account_revision':a.revision,'project_revision':p.revision,'enabled':body.enabled}
    if previous==binding:return state
    if not previous and len(state['customers'])>=200:raise HTTPException(409,'Repository customer limit reached')
    state['customers'][a.id]=binding;state['revision']+=1
    persist(db,project,state,principal.user_id,'repository.customer_connected');db.commit();return state


@router.post('/{ident}/status')
def status(ident:str,body:Toggle,principal=Depends(current_principal),db=Depends(db_session)):
    project,state=editable(db,principal,ident)
    if state['revision']!=body.expected_revision:raise HTTPException(409,'Repository changed; refresh first')
    if state['enabled']==body.enabled:return state
    state['enabled']=body.enabled;state['revision']+=1
    persist(db,project,state,principal.user_id,'repository.connection_status');db.commit();return state


@router.get('/request-options/{request_id}')
def request_options(request_id:str,principal=Depends(current_principal),db=Depends(db_session)):
    require_role(principal,'admin','engineer','manager')
    from ownstack.team_scope import require_request
    req=require_request(db,principal,request_id);project=require_project(db,principal,req.project_id)
    from ownstack.customer_models import CustomerRequestLink
    link=db.get(CustomerRequestLink,req.id)
    result=[]
    for state in states(db,project).values():
        if not state['enabled'] or (link and not state['customers'].get(link.customer_id,{}).get('enabled')):continue
        result.append({'id':state['id'],'label':state['label'],'kind':state['kind'],'source':state['source']})
    item=db.scalar(select(EngineeringItem).where(EngineeringItem.tenant_id==req.tenant_id,EngineeringItem.request_id==req.id))
    return {'customer_id':link.customer_id if link else None,'repositories':result,'engineering_id':item.id if item else None}


@router.post('/handoff')
def handoff(body:Handoff,principal=Depends(current_principal),db=Depends(db_session)):
    require_role(principal,'engineer')
    from ownstack.team_scope import require_request
    from ownstack.service import manual_handoff
    from ownstack.repository_cockpit import bind_case,BindBody,is_repository,binding,current_context
    req=require_request(db,principal,body.request_id,write=True);lock_project(db,principal,req.project_id)
    connection=witness(db,req,body.repository_id,kind='pinned')
    item=db.scalar(select(EngineeringItem).where(EngineeringItem.tenant_id==req.tenant_id,EngineeringItem.request_id==req.id))
    if item is None:
        manual_handoff(db,req,principal);db.flush()
        item=db.scalar(select(EngineeringItem).where(EngineeringItem.tenant_id==req.tenant_id,EngineeringItem.request_id==req.id))
    if item is None:raise HTTPException(409,'Engineering handoff was not saved')
    if is_repository(item):
        if (binding(item).get('connection') or {}).get('repository_id')!=body.repository_id:
            raise HTTPException(409,'Work item already belongs to another repository')
        current_context(db,item);db.commit()
    else:
        bind_case(item.id,BindBody(case_id=connection['source']['case_id'],repository_id=body.repository_id),principal,db)
    return {'engineering_id':item.id,'repository_id':body.repository_id,'ai_call':False,'released':False}


@router.get('/review-sharing/{item_id}')
def review_sharing(item_id:str,principal=Depends(current_principal),db=Depends(db_session)):
    require_role(principal,'admin','engineer','manager')
    from ownstack.service import scoped
    from ownstack.customer_models import CustomerRequestLink,CustomerAudit
    from ownstack.repository_cockpit import is_repository,matching
    item=scoped(db,EngineeringItem,item_id,principal.tenant_id,actor=principal)
    link=db.get(CustomerRequestLink,item.request_id)
    if not link or not is_repository(item):return {'submission_id':None,'can_share':False,'shared':False}
    verification=item.patch.get('_verification_id')
    rows=db.scalars(select(CustomerAudit).where(CustomerAudit.tenant_id==principal.tenant_id,
        CustomerAudit.customer_id==link.customer_id,CustomerAudit.action=='customer.review_shared')).all()
    shared=any(r.payload.get('verification_id')==verification and r.payload.get('item_id')==item.id for r in rows)
    return {'submission_id':link.submission_id,'can_share':principal.role=='engineer' and
        item.human_decision=='accept_for_manual_release' and bool(matching(db,item)), 'shared':shared}
