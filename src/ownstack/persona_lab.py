"""Persistent synthetic identities for an isolated, credit-free local laboratory.

No production database, shared demo fixture, provider ledger or real person is
used. Profiles describe fictional needs; creating an account fulfills none of
those business needs. Passwords/configuration stay in a private operator folder.
"""
from __future__ import annotations
from collections import Counter
import csv
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import sqlite3
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
PROFILES=ROOT/'evals/personas_v1/profiles.tsv'
FIELDS={'id','name','occupation','need','constraint','success','experience','interaction'}
ROLES=('admin','engineer','member','contractor')
LAB_SCHEMA_REVISION='e28f10d3a603'


def load_profiles(path:Path=PROFILES)->list[dict]:
    with path.open(newline='') as file:rows=list(csv.DictReader(file,delimiter='\t'))
    if len(rows)!=100 or [r.get('id') for r in rows]!=[f'P{i:03}' for i in range(1,101)]:
        raise ValueError('Expected the hundred ordered synthetic profiles')
    for row in rows:
        if set(row)!=FIELDS or any(not isinstance(v,str) or not v.strip() for v in row.values()):
            raise ValueError('Invalid profile fields')
        if any(ord(c)<32 for value in row.values() for c in value):raise ValueError('Control character in profile')
    for field in ('name','occupation','need','constraint','success'):
        if len({r[field].casefold().strip() for r in rows})!=100:raise ValueError('Duplicate '+field)
    return rows


def audit_profiles(rows:list[dict])->dict:
    """Lexical diagnostics are not proof of zero semantic overlap."""
    stop={'a','an','the','and','or','of','to','in','for','with','from','its','must','not','be','as','that','each','every','can','is'}
    tokens={r['id']:set(re.findall(r'[a-z]{3,}',r['need'].lower()+' '+r['constraint'].lower()))-stop for r in rows}
    pairs=[]
    for i,left in enumerate(rows):
        for right in rows[i+1:]:
            a,b=tokens[left['id']],tokens[right['id']]
            pairs.append({'left':left['id'],'right':right['id'],'jaccard':round(len(a&b)/len(a|b),4)})
    return {'profiles':len(rows),'fictional':True,'unique_needs':len({r['need'] for r in rows}),
        'unique_constraints':len({r['constraint'] for r in rows}),'closest_lexical_pairs':sorted(pairs,key=lambda p:-p['jaccard'])[:15],
        'independent_semantic_review':False,'zero_similarity_guarantee':False,
        'scope':'Distinct authored profiles, not observed customers. Lexical difference does not establish semantic independence.'}


def avatar_svg(profile:dict)->str:
    """Code-native identity glyphs, not photographs or independent human artwork."""
    seed=hashlib.sha256(profile['id'].encode()).digest();hue=int.from_bytes(seed[:2],'big')%360
    nodes=[]
    for i in range(9):
        angle=(i/9*2*math.pi)+seed[i+2]/255
        radius=18+seed[i+11]%20;x=50+math.cos(angle)*radius;y=50+math.sin(angle)*radius
        nodes.append((round(x,2),round(y,2),2+seed[i+20]%5))
    edges=''.join(f'<path d="M50 50L{x} {y}" stroke="hsl({hue} 40% 42%)" stroke-width="1.3"/>' for x,y,_ in nodes)
    dots=''.join(f'<circle cx="{x}" cy="{y}" r="{r}" fill="hsl({(hue+r*9)%360} 55% 44%)"/>' for x,y,r in nodes)
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" role="img" aria-label="Synthetic identity {profile["id"]}"><title>{html.escape(profile["name"])}</title><rect width="100" height="100" rx="24" fill="hsl({hue} 40% 94%)"/>{edges}{dots}<circle cx="50" cy="50" r="13" fill="hsl({hue} 45% 27%)"/><text x="50" y="54" fill="white" font-size="12" text-anchor="middle" font-family="sans-serif">{profile["id"][1:]}</text></svg>'


def write_private(path:Path,value:dict)->None:
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as file:json.dump(value,file,indent=2);file.write('\n')


def configure(directory:Path,port:int=8107)->dict:
    if directory.is_symlink():raise ValueError('Lab directory must not be a symlink')
    directory=directory.resolve()
    if stat.S_IMODE(directory.stat().st_mode)&0o077:raise ValueError('Lab directory requires private permissions')
    for name in ('lab.json','secrets.json','accounts.json','lab.sqlite'):
        p=directory/name
        if p.is_symlink() or not p.is_file():raise ValueError('Missing or unsafe private lab file')
        if stat.S_IMODE(p.stat().st_mode)&0o077:raise ValueError('Lab files require private permissions')
    manifest=json.loads((directory/'lab.json').read_text())
    secret=json.loads((directory/'secrets.json').read_text())
    if manifest.get('kind')!='ownstack-synthetic-persona-lab' or manifest.get('provider_calls_allowed')!=0:
        raise ValueError('This is not a credit-free persona laboratory')
    connection=sqlite3.connect((directory/'lab.sqlite').as_uri()+'?mode=ro',uri=True)
    try:
        revision=connection.execute('SELECT version_num FROM alembic_version').fetchone()
        if revision!=(LAB_SCHEMA_REVISION,):raise ValueError('Lab migration revision does not match this build')
    except sqlite3.DatabaseError as exc:raise ValueError('Lab migrations are incomplete') from exc
    finally:connection.close()
    for name,value in {'OWNSTACK_DATABASE_URL':'sqlite:///'+str(directory/'lab.sqlite'),
        'OWNSTACK_ENV':'local','OWNSTACK_AI_MODE':'off','OWNSTACK_MAX_LIVE_CALLS':'0',
        'NEBIUS_API_KEY':'','NEBIUS_MODEL_ID':'','NEBIUS_PATCH_MODEL_ID':'',
        'OWNSTACK_TRAINED_PLANNER_URL':'','OWNSTACK_PLANNER_SERVICE_TOKEN':'',
        'OWNSTACK_SIGNING_SECRET':secret['signing_secret'],'OWNSTACK_PUBLIC_SIGNUP':'false',
        'OWNSTACK_COOKIE_NAMESPACE':'lab-'+hashlib.sha256(secret['signing_secret'].encode()).hexdigest()[:12],
        'OWNSTACK_PUBLIC_ORIGIN':f'http://127.0.0.1:{port}','OWNSTACK_REQUIRE_BACKGROUND':'false',
        'OWNSTACK_ENFORCE_AUTH_CLOCK':'false'}.items():os.environ[name]=value
    return manifest


def initialize(directory:Path,profiles_path:Path=PROFILES)->dict:
    """Explicit new fixture only. Never merge, reseed, overwrite or reset one."""
    profiles=load_profiles(profiles_path)
    if directory.is_symlink() or directory.exists():raise FileExistsError('Preserve the existing laboratory; use it or choose a new directory')
    directory.mkdir(mode=0o700,parents=False)
    dbpath=directory/'lab.sqlite';dbpath.touch(mode=0o600,exist_ok=False)
    manifest={'kind':'ownstack-synthetic-persona-lab','version':1,'accounts':100,'tenants':100,
        'profiles_sha256':hashlib.sha256(profiles_path.read_bytes()).hexdigest(),
        'provider_calls_allowed':0,'scenario_target_per_persona':1000,'scenario_target_total':100000,
        'business_journeys_completed':0,'source':'Fictional authored profiles, not observed customers'}
    write_private(directory/'lab.json',manifest)
    write_private(directory/'secrets.json',{'signing_secret':secrets.token_urlsafe(48)})
    accounts={r['id']:{'username':'persona-'+r['id'].lower(),'password':secrets.token_urlsafe(32),
        'role':ROLES[i%4],'tenant_id':'lab-'+r['id'].lower(),'project_id':'project-'+r['id'].lower()} for i,r in enumerate(profiles)}
    write_private(directory/'accounts.json',accounts)
    # Use only the explicit new fixture engine, never the module's default engine.
    from sqlalchemy.orm import sessionmaker
    from ownstack.db import make_engine
    from ownstack.auth import password_hash
    from ownstack.models import Contract,Document,InferenceBudget,Project,Tenant,User
    from ownstack import repair_models  # noqa: F401
    from ownstack.policy import CONTRACT,digest
    from ownstack.team_scope import ensure_general_team,add_general_member
    migration_env={**os.environ,'OWNSTACK_DATABASE_URL':'sqlite:///'+str(dbpath.resolve()),
        'OWNSTACK_AI_MODE':'off','OWNSTACK_MAX_LIVE_CALLS':'0','NEBIUS_API_KEY':'','NEBIUS_MODEL_ID':'','NEBIUS_PATCH_MODEL_ID':''}
    migrated=subprocess.run([sys.executable,'-m','alembic','upgrade','head'],cwd=ROOT,env=migration_env,
        capture_output=True,text=True,timeout=60)
    fd=os.open(directory/'migrations.log',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as file:file.write(migrated.stdout+migrated.stderr)
    if migrated.returncode:raise RuntimeError('Fixture migration failed; private log and partial fixture retained')
    engine=make_engine('sqlite:///'+str(dbpath))
    with sessionmaker(bind=engine)() as db:
        for p in profiles:
            a=accounts[p['id']]
            db.add(Tenant(id=a['tenant_id'],name='Synthetic '+p['name'],ai_enabled=False));db.flush()
            ensure_general_team(db,a['tenant_id'])
            user=User(id=a['username'],tenant_id=a['tenant_id'],role=a['role'],display_name=p['name'],password_hash=password_hash(a['password']))
            db.add(user);db.flush();add_general_member(db,user)
            db.add(Project(id=a['project_id'],tenant_id=a['tenant_id'],name=p['id']+' casework',revision=1));db.flush()
            db.add(Document(id='brief-'+p['id'].lower(),tenant_id=a['tenant_id'],project_id=a['project_id'],title='Fictional persona brief',body=json.dumps(p)))
        db.add(Contract(id=CONTRACT['id'],version=1,manifest=CONTRACT,manifest_hash=digest(CONTRACT)))
        if db.get(InferenceBudget,'global').reserved_calls!=0:raise ValueError('New fixture counter must be zero')
        db.commit()
    engine.dispose()
    avatars=directory/'avatars';avatars.mkdir(mode=0o700)
    for p in profiles:(avatars/(p['id']+'.svg')).write_text(avatar_svg(p))
    write_private(directory/'profiles.json',{'profiles':profiles,'audit':audit_profiles(profiles)})
    write_private(directory/'coverage.json',{'target':100000,'business_journeys_completed':0,
        'personas':[{'persona_id':p['id'],'target':1000,'source_cases_assigned':0,'business_outcomes_verified':0} for p in profiles],
        'rule':'Never multiply source cases across personas to reach the target. Auth checks do not count as business outcomes.'})
    return {**manifest,'roles':dict(Counter(a['role'] for a in accounts.values())),
        'credentials_printed':False,'avatars':100,'database':'isolated local SQLite fixture, not a provider authority'}


def gallery(profiles:list[dict])->str:
    cards=[]
    for i,p in enumerate(profiles):
        e={k:html.escape(v,quote=True) for k,v in p.items()}
        cards.append(f'<article data-search="{html.escape(" ".join(p.values()).lower(),quote=True)}"><header><img src="/lab/avatar/{e["id"]}" alt="Abstract synthetic avatar {e["id"]}" width="64" height="64"/><div><small>{e["id"]} · {ROLES[i%4]}</small><h2>{e["name"]}</h2><p>{e["occupation"]}</p></div></header><p>{e["need"]}</p><details><summary>Constraints &amp; success</summary><h3>Boundary</h3><p>{e["constraint"]}</p><h3>Success means</h3><p>{e["success"]}</p><h3>Interaction</h3><p>{e["interaction"]}</p></details></article>')
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OwnStack | Synthetic persona laboratory</title><style>
    *{box-sizing:border-box}body{margin:0;background:#eef4f7;color:#213e50;font:15px system-ui,sans-serif}main{max-width:1300px;padding:40px 24px;margin:auto}nav{display:flex;justify-content:space-between;gap:20px}a{color:#245d75}h1{font-size:clamp(30px,5vw,54px);letter-spacing:-.055em;max-width:650px;margin:55px 0 18px}main>p{max-width:760px;line-height:1.7;color:#506d7d}.stats{display:flex;gap:24px;margin:30px 0;flex-wrap:wrap}.stats div{padding:14px 20px;background:#fff;border-radius:16px}.stats strong{font-size:25px;display:block}.stats small{color:#527082}label{display:block;margin:30px 0 10px}input{width:min(100%,600px);padding:15px;border:1px solid #cadce6;border-radius:12px;font:inherit}#count{display:block;margin:15px 0;color:#537286}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:18px}article{padding:24px;background:#ffffffd9;border:1px solid #fff;border-radius:22px;box-shadow:0 12px 35px #244a6010}article header{display:flex;align-items:center;gap:14px}article h2{margin:3px 0;font-size:23px;letter-spacing:-.03em}article p{line-height:1.65;color:#456274}article header p{font-size:12px;line-height:1.4;margin:3px 0}small{font-size:11px;color:#6b8797}details{margin-top:15px}summary{cursor:pointer;font-size:13px}h3{font-size:11px;text-transform:uppercase;letter-spacing:.08em;margin-top:22px}details p{font-size:13px}input:focus-visible,summary:focus-visible,a:focus-visible{outline:3px solid #1986a8;outline-offset:4px}[hidden]{display:none!important}</style><main><nav><strong>OwnStack / Laboratory</strong><a href="/">Open test workspace</a></nav><h1>Different people.<br>Different definitions of success.</h1><p>These are fictional test personas with saved synthetic accounts. Their needs are not customer interviews or verified product capabilities. The identity glyphs are generated graphics. Shared human needs and permission roles remain; zero similarity is not claimed.</p><section class="stats" aria-label="Laboratory coverage"><div><strong>100</strong><small>Saved personas</small></div><div><strong>100,000</strong><small>Requested scenario target</small></div><div><strong>0</strong><small>Business outcomes verified for this catalog</small></div><div><strong>0</strong><small>Provider calls allowed here</small></div></section><label for="search">Find a person, need or constraint</label><input id="search" type="search" placeholder="Search the laboratory…" autocomplete="off"><output id="count" aria-live="polite">100 personas</output><section class="grid" aria-label="Synthetic personas">'''+''.join(cards)+'''</section><p>Passwords and the signing secret are stored in private local operator files, never in this page or API. Accounts belong to separate isolated tenants. The four permission roles are balanced test coverage, not inferred real-world authority.</p></main><script>const search=document.getElementById('search'),cards=[...document.querySelectorAll('article')],count=document.getElementById('count');search.addEventListener('input',()=>{const q=search.value.trim().toLowerCase();let n=0;cards.forEach(c=>{c.hidden=!c.dataset.search.includes(q);if(!c.hidden)n++});count.textContent=n+' persona'+(n===1?'':'s')});</script></html>'''
