"""Append-only private experiment records and conservative training eligibility.

SQLite transactions preserve completed rows across interruptions. Hash chaining
detects accidental edits, not a compromised operator. A matching evidence file
is consistency evidence, not independent security or evaluator attestation.
"""
from __future__ import annotations
from collections import Counter
from contextlib import contextmanager
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4
from pydantic import BaseModel,ConfigDict,Field,model_validator

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)
def digest(value):return hashlib.sha256(value if isinstance(value,bytes) else value.encode()).hexdigest()
SHA=r'^[a-f0-9]{64}$'

class Result(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    case_id:str=Field(min_length=1,max_length=150)
    persona_id:str|None=Field(default=None,pattern=r'^P(?:00[1-9]|0[1-9][0-9]|100)$')
    scope:Literal['authentication','control','upstream_issue','persona_business']
    status:Literal['planned','running','passed','failed','blocked','aborted']
    source_group:str=Field(min_length=1,max_length=200)
    source_split:Literal['train','validation','test','unassigned']='unassigned'
    source_url:str|None=None
    reason:str=Field(default='',max_length=2000)
    checks:list[dict]=Field(default_factory=list)
    candidate_origin:Literal['none','model','human','reference']='none'
    case_sha256:str|None=Field(default=None,pattern=SHA)
    candidate_sha256:str|None=Field(default=None,pattern=SHA)
    oracle_sha256:str|None=Field(default=None,pattern=SHA)
    evidence_file:str|None=None
    evidence_sha256:str|None=Field(default=None,pattern=SHA)
    human_reviewed:bool=False
    reference_answer_visible:bool=False
    prompt:str|None=Field(default=None,max_length=100000)
    completion:str|None=Field(default=None,max_length=100000)

    @model_validator(mode='after')
    def boundaries(self):
        if self.source_url:
            u=urlsplit(self.source_url)
            if u.scheme!='https' or not u.hostname or u.username or u.password or u.query or u.fragment:
                raise ValueError('Use a plain public provenance URL without credentials or query data')
        for check in self.checks:
            if set(check)!={'name','passed'} or not isinstance(check['name'],str) or type(check['passed']) is not bool:
                raise ValueError('Checks contain only their name and boolean result')
        if self.status=='passed':
            if not self.checks or not all(c['passed'] for c in self.checks):raise ValueError('Passing requires nonempty passing checks')
            if self.scope in {'upstream_issue','persona_business'} and not all([
                self.case_sha256,self.candidate_sha256,self.oracle_sha256,self.evidence_file,self.evidence_sha256]):
                raise ValueError('Business/issue success requires exact candidate and independent-test evidence')
        return self


class ExperimentStore:
    def __init__(self,directory:Path):
        if directory.is_symlink():raise ValueError('Do not use a symlink result store')
        directory.mkdir(mode=0o700,parents=False,exist_ok=True)
        if directory.stat().st_mode&0o077:raise ValueError('Result directory requires private permissions')
        self.directory=directory.resolve();self.path=self.directory/'events.sqlite'
        if self.path.is_symlink():raise ValueError('Do not follow a database symlink')
        if not self.path.exists():
            fd=os.open(self.path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
        if self.path.stat().st_mode&0o077:raise ValueError('Result database requires private permissions')
        with self.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL, previous_hash TEXT NOT NULL, hash TEXT NOT NULL)')

    @contextmanager
    def connection(self):
        db=sqlite3.connect(self.path,timeout=20)
        db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA synchronous=FULL')
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:db.close()

    def _evidence(self,result:Result):
        if result.status!='passed' or result.scope not in {'upstream_issue','persona_business'}:return
        relative=Path(result.evidence_file)
        if relative.is_absolute() or '..' in relative.parts:raise ValueError('Evidence must be owned by the result store')
        path=self.directory/relative
        if path.is_symlink() or not path.resolve().is_relative_to(self.directory):raise ValueError('Unsafe evidence path')
        raw=path.read_bytes()
        if digest(raw)!=result.evidence_sha256:raise ValueError('Evidence bytes changed')
        proof=json.loads(raw)
        for field in ('case_id','case_sha256','candidate_sha256','oracle_sha256'):
            if proof.get(field)!=getattr(result,field):raise ValueError('Evidence does not match '+field)
        required=proof.get('required_tests');observed=proof.get('observed_tests')
        if (not isinstance(required,list) or not required or len(set(required))!=len(required)
                or not isinstance(observed,dict) or not all(observed.get(t) is True for t in required)
                or proof.get('baseline_failed') is not True or proof.get('candidate_passed') is not True):
            raise ValueError('Exact required tests and a reproducing baseline are necessary')

    def append(self,result:Result,event_id:str|None=None)->str:
        self._evidence(result)
        event_id=event_id or str(uuid4())
        body={'at':datetime.now(timezone.utc).isoformat(),'result':result.model_dump()}
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            prior=db.execute('SELECT payload FROM events WHERE event_id=?',(event_id,)).fetchone()
            if prior:
                if json.loads(prior[0])['result']!=result.model_dump():raise ValueError('Event identity reused with different result')
                return event_id
            last=db.execute('SELECT hash FROM events ORDER BY seq DESC LIMIT 1').fetchone()
            previous=last[0] if last else '0'*64
            payload=canonical(body);checksum=digest(previous+event_id+payload)
            db.execute('INSERT INTO events(event_id,payload,previous_hash,hash) VALUES(?,?,?,?)',(event_id,payload,previous,checksum))
        return event_id

    def records(self):
        previous='0'*64;rows=[]
        with self.connection() as db:
            for seq,event_id,payload,prev,checksum in db.execute('SELECT seq,event_id,payload,previous_hash,hash FROM events ORDER BY seq'):
                if prev!=previous or checksum!=digest(previous+event_id+payload):raise ValueError('Experiment history integrity check failed')
                parsed=json.loads(payload);Result.model_validate(parsed['result'])
                rows.append({'seq':seq,'event_id':event_id,**parsed});previous=checksum
        return rows

    def summary(self):
        rows=self.records();latest={}
        for row in rows:
            r=row['result'];latest[(r['scope'],r['case_id'],r['persona_id'])]=r
        return {'events':len(rows),'latest_cases':len(latest),'states':dict(Counter(r['status'] for r in latest.values())),
            'by_scope':dict(Counter(r['scope'] for r in latest.values())),
            'verified_business_outcomes':sum(r['status']=='passed' and r['scope'] in {'upstream_issue','persona_business'} for r in latest.values()),
            'running_is_not_passed':True,'hash_chain_is_attestation':False}


def training_rejection(result:Result,heldout_ids:set[str],heldout_groups:set[str])->str|None:
    if result.case_id in heldout_ids or result.source_group in heldout_groups or result.source_split!='train':return 'held_out_or_unassigned'
    if result.scope not in {'upstream_issue','persona_business'}:return 'not_a_business_trajectory'
    if result.status!='passed':return 'not_verified_success'
    if result.candidate_origin not in {'model','human'} or result.reference_answer_visible:return 'reference_answer_or_contamination'
    if not result.human_reviewed:return 'human_review_missing'
    if not result.prompt or not result.completion:return 'missing_prompt_or_completion'
    return None


def export_sft(store:ExperimentStore,destination:Path,heldout_ids:set[str],heldout_groups:set[str]):
    if destination.exists():raise FileExistsError('Keep prior training exports')
    records=store.records();latest={}
    for row in records:
        r=Result.model_validate(row['result']);latest[(r.scope,r.case_id,r.persona_id)]=r
    selected=[];excluded=Counter();seen=set()
    for r in latest.values():
        why=training_rejection(r,heldout_ids,heldout_groups)
        if why:excluded[why]+=1;continue
        store._evidence(r)
        key=digest(r.prompt+'\0'+r.completion)
        if key in seen:excluded['duplicate_training_pair']+=1;continue
        seen.add(key);selected.append({'prompt':r.prompt,'completion':r.completion,
            'case_id':r.case_id,'source_group':r.source_group,'candidate_sha256':r.candidate_sha256})
    destination.mkdir(mode=0o700,parents=False)
    fd=os.open(destination/'sft.jsonl',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as file:
        for row in selected:file.write(canonical(row)+'\n')
    manifest={'method_candidate':'supervised_fine_tuning_with_LoRA','eligible_examples':len(selected),'excluded':dict(excluded),
        'training_ready':False,'training_run':False,'provider_calls':0,
        'reason':'Data export only. Model selection, grouped validation, minimum dataset quality and explicit compute approval remain gates.',
        'sft_sha256':digest((destination/'sft.jsonl').read_bytes())}
    (destination/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest
