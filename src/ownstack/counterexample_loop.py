"""Counterexample-guided repository repair with a protected independent oracle.

Only the operator supplies execution/model capabilities. HTTP cannot supply
commands or passing reports. A successful run is ready for review, never released.
"""
from copy import deepcopy
from pathlib import Path
from typing import TypedDict
import json
from pydantic import BaseModel,ConfigDict,Field
from langgraph.graph import StateGraph,START,END
from langsmith import tracing_context
from ownstack.policy import digest
from ownstack.release_repository import load,MANIFEST,relative
from ownstack.repository_executor import private_json

class Edit(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid')
    path:str=Field(max_length=240)
    old:str=Field(min_length=1,max_length=12000)
    new:str=Field(max_length=20000)

class RepositoryPatch(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid')
    edits:list[Edit]=Field(min_length=1,max_length=4)

def apply_patch(source:Path,output:Path,value,editable):
    """Materialize only reviewed inventory; never copy private/unlisted files."""
    patch=RepositoryPatch.model_validate(value);snapshot,files=load(source)
    paths=[edit.path for edit in patch.edits]
    if len(paths)!=len(set(paths)) or len(json.dumps(patch.model_dump()).encode())>64000:raise ValueError('Duplicate or oversized patch')
    for edit in patch.edits:
        relative(edit.path)
        if (edit.path not in editable or edit.path not in files or not edit.path.endswith('.py')
                or edit.path==snapshot['config']['entrypoint']):raise ValueError('Patch exceeds reviewed editable capability')
        text=files[edit.path].decode()
        if text.count(edit.old)!=1 or edit.old==edit.new:raise ValueError('Patch anchor must match exactly once and change code')
        files[edit.path]=text.replace(edit.old,edit.new,1).encode()
    # Require a fresh private output and nonsymlink ancestors.
    output=output.absolute()
    if any(p.is_symlink() for p in (output,*output.parents)):raise ValueError('No symlink output')
    output.mkdir(mode=0o700,parents=False,exist_ok=False)
    for name,raw in files.items():
        target=output/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    (output/MANIFEST).write_text(json.dumps(snapshot['config'],indent=2)+'\n')
    result,_=load(output)
    return {'snapshot':result,'patch_hash':digest(patch.model_dump()),'patch':patch.model_dump()}


def counterexamples(report,requirements):
    """Choose the least-complex observed failure in the declared finite domain.

    This is not global minimization or proof over arbitrary program inputs.
    All observations remain saved; the summary gives the repairer one witness.
    """
    cases={(spec['key'],c['case_id']):c for spec in requirements for c in spec['cases']}
    failures=[]
    for row in report.get('assessments',[]):
        if row.get('baseline_passed') and not row.get('candidate_passed'):
            case=cases[(row['requirement_key'],row['case_id'])]
            complexity=int(case['input']['assigned'])+int(case['input']['grant_starts_at'] is not None)+int(case['input']['grant_revoked'])
            failures.append((complexity,case['case_id'],{'input':case['input'],'expected':row['expected'],
                'observed':row['observed_candidate'],'case_id':case['case_id'],'requirement_key':row['requirement_key']}))
    return {'count':len(failures),'minimal_observed':sorted(failures,key=lambda r:(r[0],r[1]))[0][2] if failures else None}


def preservation_witnesses(report, requirements):
    """Keep a bounded, deterministic sample of behavior that already works.

    A denied counterexample alone does not show a repairer what an allowed read
    returns. Include actual passing observations across access paths, without
    sending reference code or letting the model edit the approved expectations.
    Six witnesses are context, not a substitute for running every approved case.
    """
    cases={(spec['key'],c['case_id']):c for spec in requirements for c in spec['cases']}
    selected=[];seen=set()
    for row in sorted(report.get('assessments',[]), key=lambda r:(r['expected']['status_code']!=200,r['requirement_key'],r['case_id'])):
        if not row.get('baseline_passed') or not row.get('candidate_passed'):continue
        case=cases[(row['requirement_key'],row['case_id'])];data=case['input']
        category=(row['expected']['status_code'],bool(data['assigned']),
            data['grant_starts_at'] is not None,data['actor_tenant_id']==data['resource_tenant_id'])
        if category in seen:continue
        seen.add(category)
        selected.append({'input':deepcopy(data),'expected':deepcopy(row['expected']),
            'observed':deepcopy(row['observed_candidate']),'case_id':case['case_id'],'requirement_key':row['requirement_key']})
        if len(selected)==6:break
    return selected

class LoopState(TypedDict,total=False):
    attempt:int
    candidate:str
    report:dict
    result:dict
    failure:dict
    trace:list
    stop:bool

def run_loop(*,candidate,requirements,editable,output,verify,propose=None,max_attempts=2):
    """verify must run and save the real control-plane check for this source.

    propose receives untrusted source/evidence and returns an untrusted bounded
    patch plus provenance. Tests inject explicit model doubles. No default fake.
    """
    if type(max_attempts) is not int or not 1<=max_attempts<=3:raise ValueError('One to three attempts supported')
    output=Path(output).absolute()
    if any(p.is_symlink() for p in (output,*output.parents)):raise ValueError('No symlink result path')
    output.mkdir(mode=0o700,parents=True,exist_ok=False)
    frozen=deepcopy(requirements);oracle_hash=digest(frozen);editable=frozenset(editable)
    def check(state):
        if digest(requirements)!=oracle_hash:raise ValueError('Approved expectations changed')
        number=state['attempt']+1
        report=verify(Path(state['candidate']),output/f'attempt-{number}')
        if digest(requirements)!=oracle_hash:raise ValueError('Verifier changed protected expectations')
        private_json(output/f'attempt-{number}-summary.json',report)
        passed=report.get('state')=='passed' and report.get('report',{}).get('passed') is True
        stop=passed or report.get('state')!='regression' or number>=max_attempts or propose is None
        return {'attempt':number,'report':report,'stop':stop,'trace':state['trace']+[{'tool':'verify_candidate','attempt':number,'state':report.get('state')}],
            'result':{'state':'ready_for_human_review' if passed else 'manual_handoff','check_id':report.get('id'),
                'accepted':False,'released':False,'oracle_hash':oracle_hash}}
    def falsify(state):
        failure=counterexamples(state['report']['report'],frozen)
        private_json(output/f"counterexample-{state['attempt']}.json",failure)
        return {'failure':failure,'trace':state['trace']+[{'tool':'select_observed_counterexample','count':failure['count']}],
            'stop':failure['minimal_observed'] is None}
    def repair(state):
        snapshot,files=load(Path(state['candidate']))
        context={'source_sha256':snapshot['sha256'],'check_id':state['report']['id'],'editable_files':{p:files[p].decode() for p in sorted(editable) if p in files},
            'counterexample':deepcopy(state['failure']['minimal_observed']),
            'preservation_witnesses':preservation_witnesses(state['report']['report'],frozen),'oracle_hash':oracle_hash}
        if len(json.dumps(context).encode())>64000:raise ValueError('Bounded repair context exceeded')
        try:
            patch,provenance=propose(deepcopy(context))
            if digest(requirements)!=oracle_hash:raise ValueError('Repairer changed protected expectations')
            target=output/f"candidate-{state['attempt']+1}"
            changed=apply_patch(Path(state['candidate']),target,patch,editable)
            private_json(output/f"proposal-{state['attempt']}.json",{**changed,'provenance':provenance})
            return {'candidate':str(target),'trace':state['trace']+[{'tool':'propose_bounded_patch','patch_hash':changed['patch_hash']}], 'stop':False}
        except Exception as error:
            private_json(output/f"repair-failure-{state['attempt']}.json",{'error_type':type(error).__name__,'accepted':False,'released':False})
            return {'stop':True,'trace':state['trace']+[{'tool':'propose_bounded_patch','outcome':'failed','error_type':type(error).__name__}]}
    graph=StateGraph(LoopState)
    graph.add_node('verify',check);graph.add_node('falsify',falsify);graph.add_node('repair',repair)
    graph.add_edge(START,'verify');graph.add_conditional_edges('verify',lambda s:'done' if s['stop'] else 'falsify',{'done':END,'falsify':'falsify'})
    graph.add_conditional_edges('falsify',lambda s:'done' if s['stop'] else 'repair',{'done':END,'repair':'repair'})
    graph.add_conditional_edges('repair',lambda s:'done' if s['stop'] else 'verify',{'done':END,'verify':'verify'})
    with tracing_context(enabled=False):
        final=graph.compile(name='ownstack-counterexample-repair-v1').invoke({'attempt':0,'candidate':str(Path(candidate).absolute()),'trace':[]},
            config={'recursion_limit':16,'callbacks':[]})
    result={**final['result'],'attempts':final['attempt'],'trace':final['trace'],'final_candidate':final['candidate'],
        'limitation':'Bounded supported visibility profile. No release, exhaustive proof or live model result follows from a supplied patch.'}
    private_json(output/'result.json',result);return result
