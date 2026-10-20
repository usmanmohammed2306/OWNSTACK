"""Runs proposed edits only in a no-network disposable Docker container.

This is an experimental boundary, not a certified hostile-code sandbox.
"""
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import time
import sys
from uuid import uuid4
from ownstack.policy import digest
from ownstack.bounded_process import capture
from ownstack.candidate_driver import DRIVER
from ownstack.pdf_oracle import MAX_OUTPUT_BYTES, cases, is_external_pass, judge
from ownstack.candidate_sandbox import POLICY_ID
from ownstack.job_files import read_json, write_json

ROOT = Path(os.getenv("OWNSTACK_SOURCE_ROOT", Path(__file__).resolve().parents[2]))
ALLOWED_PATH = "sample_app/report.py"
CHECKS = "checks/test_report.py"
MAX_PATCH_BYTES = 12_000


def validate_patch(patch: dict) -> None:
    if set(patch) != {"edits"} or not isinstance(patch["edits"], list) or len(patch["edits"]) != 1:
        raise ValueError("One bounded edit is required")
    edit = patch["edits"][0]
    if set(edit) != {"path", "old", "new"} or edit["path"] != ALLOWED_PATH:
        raise ValueError("Patch may edit only sample_app/report.py")
    if not all(isinstance(edit[k], str) for k in ("old", "new")) or len(edit["new"].encode()) > MAX_PATCH_BYTES:
        raise ValueError("Invalid patch text or size")
    source = (ROOT / ALLOWED_PATH).read_text()
    if not edit["old"] or source.count(edit["old"]) != 1:
        raise ValueError("Patch anchor must match exactly once")


def patch_hash(patch: dict) -> str:
    validate_patch(patch)
    return digest(patch)


def materialize(patch: dict, directory: Path) -> None:
    validate_patch(patch)
    (directory / "sample_app").mkdir(parents=True)
    (directory / "checks").mkdir(parents=True)
    for relative in ("sample_app/__init__.py", ALLOWED_PATH, CHECKS):
        shutil.copyfile(ROOT / relative, directory / relative)
    edit = patch["edits"][0]
    target = directory / ALLOWED_PATH
    target.write_text(target.read_text().replace(edit["old"], edit["new"], 1))


def verify_in_docker(patch: dict) -> dict:
    """Disposable candidate container; the host independently judges its PDF bytes."""
    payload, case_set = candidate_payload(patch)
    container_name = "ownstack-check-" + uuid4().hex
    provenance = current_provenance()
    try:
        # Resolve a locally installed image to an immutable ID. Never pull implicitly.
        inspected = subprocess.run(["docker", "image", "inspect", "python:3.12-slim", "--format", "{{.Id}}"],
                                   capture_output=True, text=True, timeout=10, check=True)
        image_id = inspected.stdout.strip()
        if not image_id.startswith("sha256:") or len(image_id) != 71:
            raise ValueError("Invalid local candidate image ID")
        cmd = ["docker", "run", "--name", container_name, "--rm", "--pull", "never", "--log-driver", "none", "-i",
               "--user", "65534:65534", "--network", "none", "--read-only", "--cap-drop", "ALL",
               "--security-opt", "no-new-privileges", "--pids-limit", "16", "--memory", "256m",
               "--memory-swap", "256m", "--cpus", "1", "--ulimit", "cpu=8:8",
               "--ulimit", "fsize=1048576:1048576", "--ulimit", "nofile=64:64",
               image_id, "python", "-I", "-B", "-c", DRIVER]
        captured = capture(cmd, payload, timeout=20, limit=MAX_OUTPUT_BYTES)
        return verdict(captured, case_set, patch, "docker-external-oracle", provenance,
                       image_id=image_id, isolation_profile=POLICY_ID)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        return verdict({"stdout_bytes": b"", "exit_code": None, "stderr": str(error), "failure": "Candidate runner unavailable"},
                       case_set, patch, "unavailable", provenance)
    finally:
        # Only this invocation's uniquely named disposable job is removed.
        try:
            subprocess.run(["docker", "rm", "--force", container_name], timeout=10,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        except (OSError, subprocess.TimeoutExpired):
            pass


def candidate_payload(patch: dict) -> tuple[bytes, list[dict]]:
    validate_patch(patch)
    edit = patch["edits"][0]
    source = (ROOT / ALLOWED_PATH).read_text().replace(edit["old"], edit["new"], 1)
    case_set = cases()
    return json.dumps({"source": source, "cases": case_set}).encode(), case_set


def verdict(captured: dict, case_set: list[dict], patch: dict, runner: str, provenance: dict, **extra) -> dict:
    result = judge(captured["stdout_bytes"], case_set, exit_code=captured["exit_code"], failure=captured["failure"])
    return {**result, "exit_code": captured["exit_code"], "stdout": "Candidate output judged externally; PDF hashes are in cases.",
            "stderr": captured["stderr"] or result["oracle_error"], "runner": runner,
            "patch_hash": patch_hash(patch), **provenance, **extra}


def verify_via_queue(patch: dict) -> dict:
    """Hand the exact patch to a separate no-network verifier container."""
    expected_hash = patch_hash(patch)
    jobs = Path(os.getenv("OWNSTACK_VERIFIER_JOBS_DIR", "/srv/jobs"))
    incoming, outgoing = jobs / "incoming", jobs / "outgoing"
    job_id = uuid4().hex
    incoming.mkdir(parents=True, exist_ok=True)
    outgoing.mkdir(parents=True, exist_ok=True)
    submitted = incoming / f"{job_id}.json"
    response = outgoing / f"{job_id}.json"
    write_json(submitted, {"id": job_id, "patch": patch, "patch_hash": expected_hash}, 131_072)
    deadline = time.monotonic() + 55
    while time.monotonic() < deadline:
        if response.exists():
            try:
                result = read_json(response, 1_048_576)
            finally:
                response.unlink(missing_ok=True)
            if result.get("id") != job_id or result.get("patch_hash") != expected_hash:
                raise ValueError("Verifier result did not match the submitted patch")
            return {key: value for key, value in result.items() if key != "id"}
        time.sleep(0.1)
    return {"passed": False, "exit_code": None, "stdout": "",
            "stderr": "Verifier did not respond before the local deadline; execution state is unknown.",
            "runner": "no-network-queue-timeout", "patch_hash": expected_hash}


def current_provenance() -> dict:
    return {"source_hash": digest((ROOT / ALLOWED_PATH).read_text()),
            "checks_hash": digest((ROOT / CHECKS).read_text()),
            "oracle_hash": digest(Path(__file__).with_name("pdf_oracle.py").read_text()),
            "driver_hash": digest(DRIVER),
            "execution_policy_hash": digest({name: Path(__file__).with_name(name).read_text() for name in
                ("runner.py", "bounded_process.py", "verifier_service.py", "process_supervisor.py", "candidate_sandbox.py", "job_files.py")}),
            "build_revision": os.getenv("OWNSTACK_BUILD_REVISION", "uncommitted-reference")}


def verify_patch(patch: dict) -> dict:
    backend = os.getenv("OWNSTACK_VERIFIER_BACKEND", "docker")
    if backend == "docker":
        result = verify_in_docker(patch)
    elif backend == "queue":
        result = verify_via_queue(patch)
    else:
        raise ValueError("Unknown verifier backend")
    # Never relabel a stale sidecar's result with the current API's provenance.
    if result.get("passed") and (result.get('isolation_profile') != POLICY_ID
            or not is_external_pass(result) or any(result.get(k) != v for k, v in current_provenance().items())):
        return {**result, "passed": False, "stderr": "External oracle proof missing, incomplete, or stale; reverify this patch."}
    return result


def trusted_local_verification(patch: dict) -> dict:
    """Developer-only check for the repository's known fixture patch, never model output."""
    from ownstack.patch_agent import fixture_patch
    if patch != fixture_patch():
        raise ValueError("Host execution permits only the repository's exact trusted fixture")
    payload, case_set = candidate_payload(patch)
    payload = json.dumps({**json.loads(payload), "trusted_local_fixture": True}).encode()
    captured = capture([sys.executable, "-I", "-B", "-c", DRIVER], payload,
                       timeout=10, limit=MAX_OUTPUT_BYTES,
                       env={"PATH": "/usr/local/bin:/usr/bin", "PYTHONDONTWRITEBYTECODE": "1"})
    return verdict(captured, case_set, patch, "trusted-local-fixture-only", current_provenance(),
                   isolation_profile='trusted-local-fixture-only-not-sandboxed')
