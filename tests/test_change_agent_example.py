"""Reproducible owned fixture, never arbitrary candidate execution on the host."""
import importlib.util,json,subprocess,sys
from pathlib import Path
from ownstack.change_agent_contracts import VisibilityPolicy,counterexample_requirements
from ownstack.release_repository import load

ROOT=Path(__file__).resolve().parents[1]

def test_owned_example_matches_the_reviewed_domain():
    example=ROOT/'examples/counterexample_workspace'
    spec=importlib.util.spec_from_file_location('owned_public_policy_fixture',example/'customer_policy.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    policy=VisibilityPolicy.model_validate(json.loads((example/'policy.json').read_text()))
    requirements=counterexample_requirements(policy,session_id='public',customer='atlas',owner='e',source_ref='owned-fixture')
    for requirement in requirements:
        for case in requirement.cases:
            status,body=module.read(case.input.model_dump(mode='json'))
            assert status==case.expected.status_code and tuple(sorted(body))==case.expected.visible_fields

def test_example_builder_creates_bounded_candidate_and_refuses_overwrite(tmp_path):
    output=tmp_path/'sources';command=[sys.executable,str(ROOT/'scripts/make_change_agent_example.py'),'--output',str(output)]
    result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=15);assert result.returncode==0,result.stderr
    baseline,files=load(output/'baseline');candidate,changed=load(output/'candidate')
    assert baseline['sha256']!=candidate['sha256'] and files['serve.py']==changed['serve.py']
    assert b"data['assigned'] and" in files['customer_policy.py'] and b"data['assigned'] and" not in changed['customer_policy.py']
    before=(output/'candidate/customer_policy.py').read_bytes()
    assert subprocess.run(command,cwd=ROOT,capture_output=True,timeout=15).returncode!=0
    assert (output/'candidate/customer_policy.py').read_bytes()==before
