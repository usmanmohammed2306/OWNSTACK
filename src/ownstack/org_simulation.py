"""Explicit synthetic organization fixture. No usable new login credentials."""
from uuid import uuid4
import random
from sqlalchemy import select
from ownstack.models import Tenant,User,Team,TeamMembership,Project
from ownstack.workspace_models import OrganizationProfile

DEPARTMENTS=('Payments','Notifications','Billing','CRM','Deals','Platform','Identity','Core App','Data','AI',
    'Search','Infrastructure','Security','SRE','Developer Tools','Mobile','Web','Integrations','Customer Success',
    'Support','Finance','Accounting','Sales','Marketing','HR','Legal','Operations','Product','Design','Analytics')
POSITIONS=(('CTO','manager'),('CFO','member'),('COO','manager'),('CPO','member'),('CISO','manager'),
    ('VP Engineering','manager'),('VP Sales','manager'),('VP Customer Success','manager'),('General Counsel','member'),
    ('Architect','engineer'),('Staff Engineer','engineer'),('Senior Engineer','engineer'),('Software Engineer','engineer'),
    ('QA Engineer','engineer'),('Site Reliability Engineer','engineer'),('Security Engineer','engineer'),
    ('Data Scientist','engineer'),('ML Engineer','engineer'),('Product Manager','member'),('Product Designer','member'),
    ('Finance Analyst','member'),('Accountant','member'),('Sales Executive','member'),('Customer Success Manager','member'),
    ('Support Specialist','member'),('HR Partner','member'),('Legal Counsel','member'),('Operations Analyst','member'),
    ('Business Analyst','member'))


def simulation_names():
    first=('Ava','Liam','Maya','Noah','Amara','Ethan','Sofia','Arjun','Zara','Leo','Isla','Omar','Yuna','Mateo','Nia','Lucas','Anika','Eli','Leila','Kai')
    last=('Chen','Patel','Reed','Silva','Khan','Park','Rivera','Morgan','Shah','Okafor','Kim','Singh','Costa','Bennett','Nakamura','Ali','Martin','Gupta','Reyes','Wilson','Taylor','Hassan','Lee','Baker','Diaz')
    names=[a+' '+b for a in first for b in last];random.Random(20261028).shuffle(names)
    return names


def department_leader(department,executives):
    chief='CFO' if department in {'Finance','Accounting'} else 'CPO' if department in {'Product','Design'} else 'CISO' if department in {'Identity','Security'} else 'VP Sales' if department in {'Sales','Marketing','Deals'} else 'VP Customer Success' if department in {'Customer Success','Support'} else 'General Counsel' if department=='Legal' else 'COO' if department in {'Operations','HR'} else 'CTO'
    return executives[chief]


def seed_organization(db,tenant_id='atlas',size=500):
    if not 100<=size<=1000:raise ValueError('Fixture size must be between100 and1000')
    tenant=db.get(Tenant,tenant_id)
    if not tenant:raise ValueError('Existing synthetic tenant required')
    users=db.scalars(select(User).where(User.tenant_id==tenant_id).order_by(User.id)).all()
    if db.scalar(select(OrganizationProfile.user_id).where(OrganizationProfile.tenant_id==tenant_id)):
        raise ValueError('Reporting data already exists; never overwrite an organization')
    admin=next((u for u in users if u.role=='admin'),None)
    if not admin or len(users)>size:raise ValueError('Synthetic administrator and bounded initial people required')
    tenant.name='Atlas Industries · simulation'
    teams={}
    for index,name in enumerate(DEPARTMENTS):
        ident=f'sim-{tenant_id}-team-{index:02}'
        if db.get(Team,ident):raise ValueError('Simulation identifiers already in use')
        t=Team(id=ident,tenant_id=tenant_id,name=name,name_key=name.casefold());db.add(t);teams[name]=t
    db.flush()
    for t in teams.values():db.add(Project(id=t.id+'-app',tenant_id=tenant_id,team_id=t.id,name=t.name+' workspace',revision=1))
    names=simulation_names()
    generated=[];metadata=[]
    for i in range(size-len(users)):
        if i<9:title,role=POSITIONS[i];department={'CFO':'Finance','CPO':'Product','General Counsel':'Legal','VP Sales':'Sales','VP Customer Success':'Customer Success'}.get(title,'Platform')
        elif i<39:title=DEPARTMENTS[i-9]+' Manager';role='manager';department=DEPARTMENTS[i-9]
        else:
            title,role=POSITIONS[9+(i-39)%(len(POSITIONS)-9)]
            department=DEPARTMENTS[(i-39)%18]
            if title in {'Finance Analyst','Accountant'}:department='Finance'
            elif title in {'Legal Counsel'}:department='Legal'
            elif title in {'HR Partner'}:department='HR'
            elif title in {'Product Designer'}:department='Design'
            elif title in {'Product Manager'}:department='Product'
            elif title=='Sales Executive':department='Sales'
            elif title=='Customer Success Manager':department='Customer Success'
            elif title=='Support Specialist':department='Support'
            elif title=='Operations Analyst':department='Operations'
        ident=f'sim-{tenant_id}-{i+1:04}'
        # This string deliberately is not a valid password hash. Tests use the
        # isolated operator's signed local fixture identities, never new passwords.
        u=User(id=ident,tenant_id=tenant_id,role=role,password_hash='!simulation-no-login-'+uuid4().hex,
            display_name=names[i%len(names)]+(f' {i//500+1}' if i>=500 else ''),enabled=True)
        db.add(u);generated.append((u,title,department))
    db.flush()
    cto=generated[0][0].id
    executives={title:u.id for u,title,_ in generated[:9]}
    managers={department:u.id for u,title,department in generated if title.endswith(' Manager') and u.role=='manager' and title==department+' Manager'}
    for i,(u,title,department) in enumerate(generated):
        manager=admin.id if i<9 else department_leader(department,executives) if i<39 else managers[department]
        db.add(OrganizationProfile(user_id=u.id,tenant_id=tenant_id,title=title,manager_id=manager,revision=1,updated_by=admin.id))
        db.add(TeamMembership(id=str(uuid4()),tenant_id=tenant_id,team_id=teams[department].id,user_id=u.id,
            role='manager' if u.role=='manager' else 'member',enabled=True,revision=1))
        metadata.append({'id':u.id,'position':title,'role':u.role,'team':teams[department].id,'reports_to':manager})
    for u in users:
        title='CEO' if u.id==admin.id else 'Staff Engineer' if u.role=='engineer' else 'External Contractor' if u.role=='contractor' else 'Employee'
        manager=None if u.id==admin.id else cto
        db.add(OrganizationProfile(user_id=u.id,tenant_id=tenant_id,title=title,manager_id=manager,revision=1,updated_by=admin.id))
        metadata.append({'id':u.id,'position':title,'role':u.role,'reports_to':manager})
    db.flush()
    return {'simulation':True,'employees':len(metadata),'departments':len(teams),'new_credentials_created':False,'people':metadata}
