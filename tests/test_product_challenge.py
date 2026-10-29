"""Protocol checks, not proof that a fictional business scenario was fulfilled."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("product_challenge", ROOT / "scripts/product_challenge.py")
LAB = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LAB)


def test_fifty_independent_scenario_descriptions_have_explicit_gaps_and_real_test_references():
    protocol, cases = LAB.load_cases()
    assert len(cases) == 50
    assert protocol["training_relationship"].startswith("Written after")
    assert all(len(c["story"]) > 180 and c["gap"] for c in cases)
    assert sum(c["support"] == "unsupported" for c in cases) > 0


@pytest.mark.parametrize("url", ["https://api.tokenfactory.nebius.com", "http://127.0.0.1.evil.invalid",
    "http://127.0.0.1@evil.invalid", "http://user:secret@localhost", "http://localhost/proxy",
    "http://localhost?redirect=https://evil.invalid", "http://localhost#data"])
def test_evaluation_cannot_become_remote_inference_or_arbitrary_proxy(url):
    with pytest.raises(ValueError, match="loopback"):
        LAB.local_endpoint(url)


def test_schema_valid_semantically_wrong_plans_are_not_counted_as_correct():
    case = LAB.load_cases()[1][0]
    result = LAB.score('{"actions":[{"action":"reset"}]}', case)
    assert result["schema_valid"] and not result["acceptable_ui_plan"]
    assert not LAB.score('{"actions":[{"action":"approve"}]}', case)["schema_valid"]


def test_duplicate_keys_cannot_hide_approval_from_scoring():
    case = LAB.load_cases()[1][0]
    assert not LAB.score('{"actions":[],"actions":[{"action":"refuse"}]}', case)["schema_valid"]


def test_control_binding_does_not_treat_missing_skipped_or_partially_failed_as_passing(tmp_path):
    path = tmp_path / "synthetic-unit-test-report.xml"
    path.write_text('''<testsuites><testsuite>
    <testcase classname="tests.test_api" name="test_direct_host_isolation_and_revoke[a]"/>
    <testcase classname="tests.test_api" name="test_direct_host_isolation_and_revoke[b]"><failure/></testcase>
    <testcase classname="tests.test_api" name="test_host_enforces_expiry_without_worker"><skipped/></testcase>
    </testsuite></testsuites>''')
    cases = LAB.load_cases()[1]
    evidence = LAB.control_evidence(cases, path)
    assert evidence["tests/test_api.py::test_direct_host_isolation_and_revoke"]["status"] == "not_passed"
    assert evidence["tests/test_api.py::test_host_enforces_expiry_without_worker"]["status"] == "not_passed"
    assert evidence["tests/test_api.py::test_timeout_retry_discards_late_result"]["status"] == "not_run"


def test_a_passing_related_control_has_no_full_scenario_success_field(tmp_path):
    path = tmp_path / "synthetic-unit-test-report.xml"
    path.write_text('<testsuites><testsuite><testcase classname="tests.test_api" name="test_direct_host_isolation_and_revoke"/></testsuite></testsuites>')
    evidence = LAB.control_evidence(LAB.load_cases()[1], path)
    assert evidence["tests/test_api.py::test_direct_host_isolation_and_revoke"]["status"] == "passed"
    assert "complete_scenario_verified" not in evidence["tests/test_api.py::test_direct_host_isolation_and_revoke"]


def test_run_preserves_prior_results_and_does_not_dispatch_without_explicit_opt_in(tmp_path, monkeypatch):
    junit = tmp_path / "empty.xml"; junit.write_text('<testsuites/>')
    output = tmp_path / "run"
    def no_network(*args, **kwargs):
        raise AssertionError("Offline mode must never dispatch a request")
    monkeypatch.setattr(LAB.httpx.Client, "get", no_network)
    monkeypatch.setattr(LAB.httpx.Client, "post", no_network)
    report = LAB.run(output, junit)
    assert report["full_scenarios_executed"] == report["external_provider_calls"] == report["app_mutations"] == 0
    assert len(report["rows"]) == 50 and all(not r["complete_scenario_verified"] for r in report["rows"])
    assert "model" not in report["measures"]
    before = (output / "report.json").read_bytes()
    with pytest.raises(FileExistsError):
        LAB.run(output, junit)
    assert before == (output / "report.json").read_bytes()


def test_checkpoint_change_stops_evaluation_before_another_generation(tmp_path,monkeypatch):
    junit=tmp_path/'empty.xml';junit.write_text('<testsuites/>')
    calls=[]
    expected='a'*64
    class Local:
        def __init__(self,*args,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def get(self,url):
            return LAB.httpx.Response(200,request=LAB.httpx.Request('GET',url),json={'ready':True,'artifact':expected})
        def post(self,url,**kwargs):
            calls.append(url)
            return LAB.httpx.Response(200,request=LAB.httpx.Request('POST',url),json={
                'artifact':'b'*64,'output':'{"actions":[{"action":"clarify"}]}','latency_ms':1})
    monkeypatch.setattr(LAB.httpx,'Client',Local)
    with pytest.raises(RuntimeError,match='Checkpoint changed'):
        LAB.run(tmp_path/'run',junit,'http://127.0.0.1:8812',expected)
    assert len(calls)==1
    assert not (tmp_path/'run/report.json').exists()
