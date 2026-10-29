from concurrent.futures import ThreadPoolExecutor
import json
import time
from ownstack.patch_agent import fixture_patch
from ownstack.runner import patch_hash, verify_via_queue
from ownstack.verifier_service import run_once


def test_file_queue_binds_result_to_exact_patch(tmp_path, monkeypatch):
    patch = fixture_patch()
    monkeypatch.setenv("OWNSTACK_VERIFIER_JOBS_DIR", str(tmp_path))
    monkeypatch.setattr("ownstack.verifier_service.check", lambda candidate: {
        "passed": True, "exit_code": 0, "stdout": "three checks", "stderr": "",
        "runner": "test-verifier", "patch_hash": patch_hash(candidate),
    })
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(verify_via_queue, patch)
        deadline = time.monotonic() + 3
        while not list((tmp_path / "incoming").glob("*.json")) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert run_once(tmp_path)
        result = future.result(timeout=3)
    assert result["passed"] and result["patch_hash"] == patch_hash(patch)
    assert not list((tmp_path / "incoming").glob("*.json"))


def test_submitted_hash_mismatch_is_rejected_before_candidate_execution(tmp_path, monkeypatch):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    job_id = "1" * 32
    (incoming / f"{job_id}.json").write_text(json.dumps({"id": job_id, "patch": fixture_patch(), "patch_hash": "wrong"}))
    calls = []
    monkeypatch.setattr("ownstack.verifier_service.check", lambda patch: calls.append(patch))
    assert run_once(tmp_path)
    assert calls == []
    result = json.loads((tmp_path / "outgoing" / f"{job_id}.json").read_text())
    assert not result["passed"]
