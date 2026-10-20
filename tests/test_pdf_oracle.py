import base64
import json
import pytest
from ownstack.patch_agent import REFERENCE_IMPLEMENTATION, fixture_patch
from ownstack.pdf_oracle import cases, is_external_pass, judge, validate_pdf
from ownstack.runner import current_provenance, trusted_local_verification


def exports():
    namespace = {}
    # Only repository-owned reference source runs in this test process.
    exec(REFERENCE_IMPLEMENTATION, namespace)
    case_set = cases()
    return case_set, [namespace["export_pdf"](c["project"], c["rows"]) for c in case_set]


def test_external_oracle_checks_bytes_and_all_cases():
    case_set, documents = exports()
    output = json.dumps([base64.b64encode(p).decode() for p in documents]).encode()
    result = judge(output, case_set, exit_code=0)
    assert is_external_pass(result)
    assert result["checks_completed"] == 7


@pytest.mark.parametrize("output", [b"", b'{"passed":true}', b"[]", b"garbage", b"null", b"[1]", b"\xff", b"[" * 2000 + b"]" * 2000])
def test_exit_zero_and_printed_success_are_not_proof(output):
    assert not judge(output, cases(), exit_code=0)["passed"]


@pytest.mark.parametrize("mutate", [
    lambda pdf: pdf.replace(b"Project Atlas", b"Project Nova!"),
    lambda pdf: pdf.replace(b"xref\n0 6", b"xref\n0 7"),
    lambda pdf: pdf.replace(b"/Length ", b"/Length 9"),
    lambda pdf: pdf.replace(b"/Catalog", b"/JavaScript"),
    lambda pdf: pdf + b"%%EOF",
    lambda pdf: pdf[:20],
])
def test_external_oracle_rejects_wrong_content_and_corrupt_pdf(mutate):
    case_set, documents = exports()
    with pytest.raises(ValueError):
        validate_pdf(mutate(documents[0]), case_set[0])


def test_failure_and_partial_success_are_not_passes():
    case_set, documents = exports()
    output = json.dumps([base64.b64encode(p).decode() for p in documents]).encode()
    assert not judge(output, case_set, exit_code=0, failure="deadline")["passed"]
    assert not judge(output, case_set, exit_code=1)["passed"]
    result = judge(output, case_set, exit_code=0)
    result["cases"][0]["id"] = result["cases"][1]["id"]
    assert not is_external_pass(result)


def test_host_execution_rejects_nonfixture_source():
    patch = fixture_patch()
    patch["edits"][0]["new"] = "import os; os._exit(0)"
    with pytest.raises(ValueError, match="exact trusted fixture"):
        trusted_local_verification(patch)


def test_provenance_binds_external_oracle_and_driver():
    assert {"oracle_hash", "driver_hash", "execution_policy_hash", "source_hash", "checks_hash", "build_revision"} == set(current_provenance())


@pytest.mark.parametrize("field,value", [("exit_code", 1), ("oracle_error", "failed"), ("checks_completed", 6)])
def test_contradictory_verdict_is_not_external_proof(field, value):
    proof = trusted_local_verification(fixture_patch())
    proof[field] = value
    assert not is_external_pass(proof)


def test_missing_document_hash_is_not_proof():
    proof = trusted_local_verification(fixture_patch())
    proof["cases"][0].pop("pdf_sha256")
    assert not is_external_pass(proof)


def test_legacy_or_stale_sidecar_pass_is_rejected(monkeypatch):
    from ownstack import runner
    monkeypatch.setenv("OWNSTACK_VERIFIER_BACKEND", "queue")
    monkeypatch.setattr(runner, "verify_via_queue", lambda patch: {"passed": True, **current_provenance()})
    assert not runner.verify_patch(fixture_patch())["passed"]
    proof = trusted_local_verification(fixture_patch())
    proof["oracle_hash"] = "old-oracle"
    monkeypatch.setattr(runner, "verify_via_queue", lambda patch: proof)
    assert not runner.verify_patch(fixture_patch())["passed"]
