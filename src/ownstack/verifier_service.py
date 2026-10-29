"""No-network verifier sidecar. Model-authored code runs as an unprivileged user."""
import json
import os
from pathlib import Path
import resource
import tempfile
import time
import sys
from ownstack.runner import candidate_payload, current_provenance, patch_hash, verdict
from ownstack.bounded_process import capture
from ownstack.candidate_driver import DRIVER, SANDBOX_SOURCE
from ownstack.candidate_sandbox import POLICY_ID
from ownstack.pdf_oracle import MAX_OUTPUT_BYTES
from ownstack.process_supervisor import cleanup_descendants, descendants, enable_subreaper
from ownstack.job_files import read_json, write_json


def _restrict_child() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    os.setgroups([])
    os.setgid(65534)
    os.setuid(65534)


def check(patch: dict) -> dict:
    payload, case_set = candidate_payload(patch)
    provenance = current_provenance()
    enable_subreaper()
    if descendants():
        raise RuntimeError("Unexpected existing descendants; stop verifier for inspection")
    with tempfile.TemporaryDirectory(prefix="ownstack-queued-check-") as temp:
        directory = Path(temp)
        directory.chmod(0o755)
        try:
            captured = capture([sys.executable, "-I", "-B", "-c", DRIVER], payload,
                               timeout=12, limit=MAX_OUTPUT_BYTES, cwd=directory,
                               env={"PATH": "/usr/local/bin:/usr/bin", "PYTHONDONTWRITEBYTECODE": "1"},
                               preexec_fn=_restrict_child)
        except OSError as error:
            captured = {"stdout_bytes": b"", "exit_code": None, "stderr": str(error), "failure": "Candidate runner unavailable"}
        finally:
            cleanup = cleanup_descendants()
        if not cleanup["descendants_reaped"]:
            # Do not process the next job in a container with unexplained children.
            raise RuntimeError("Candidate descendants remain; verifier restart required")
        return verdict(captured, case_set, patch, "no-network-sidecar-external-oracle", provenance,
                       isolation_profile=POLICY_ID, **cleanup)


def sandbox_preflight():
    """Trusted probe in a separate restricted child, never in this supervisor."""
    code = SANDBOX_SOURCE + '\nimport json\nprint(json.dumps(lockdown()))\n'
    result = capture([sys.executable, '-I', '-B', '-c', code], b'', timeout=5, limit=4096,
        env={'PATH': '/usr/local/bin:/usr/bin'}, preexec_fn=_restrict_child)
    if result['exit_code'] != 0 or result['failure']:
        raise RuntimeError('Required kernel isolation preflight failed')
    posture = json.loads(result['stdout_bytes'])
    if posture.get('policy') != POLICY_ID or posture.get('landlock_abi', 0) < 3:
        raise RuntimeError('Kernel isolation preflight identity mismatch')
    return posture


def run_once(jobs: Path) -> bool:
    incoming, outgoing = jobs / "incoming", jobs / "outgoing"
    incoming.mkdir(parents=True, exist_ok=True)
    outgoing.mkdir(parents=True, exist_ok=True)
    for path in sorted(incoming.glob("*.json")):
        payload = {}
        try:
            payload = read_json(path, 131_072)
            job_id = payload["id"]
            if len(job_id) != 32 or not all(character in "0123456789abcdef" for character in job_id):
                raise ValueError("Invalid job ID")
            if path.name != f"{job_id}.json":
                raise ValueError("Job filename does not match ID")
            if patch_hash(payload["patch"]) != payload["patch_hash"]:
                raise ValueError("Submitted patch hash mismatch")
            result = check(payload["patch"])
            result["id"] = job_id
            write_json(outgoing / f"{job_id}.json", result)
        except Exception:
            # A malformed or failed job is not represented as a passing check.
            if path.name.endswith(".json") and len(path.stem) == 32:
                failure = {"id": path.stem, "passed": False, "exit_code": None,
                           "stdout": "", "stderr": "Verifier rejected the job.",
                           "runner": "no-network-verifier-sidecar", "patch_hash": payload.get("patch_hash", "") if isinstance(payload, dict) else ""}
                write_json(outgoing / path.name, failure)
        # Dequeue only after an outcome has been persisted. A full/read-only
        # result directory must not erase the sole durable incoming request.
        path.unlink(missing_ok=True)
        return True
    return False


def main() -> None:
    jobs = Path(os.getenv("OWNSTACK_VERIFIER_JOBS_DIR", "/srv/jobs"))
    policy_path = jobs / 'sandbox-policy.json'
    policy_path.unlink(missing_ok=True)
    posture = sandbox_preflight()  # No permissive fallback or fresh heartbeat on failure.
    last_pulse = 0.0
    while True:
        if time.monotonic() - last_pulse > 5:
            policy_pending = jobs / 'sandbox-policy.pending'
            policy_pending.write_text(json.dumps({**posture, 'checked_at': time.time(),
                'execution_policy_hash': current_provenance()['execution_policy_hash']}))
            os.replace(policy_pending, policy_path)
            pending = jobs / "heartbeat.pending"
            pending.write_text(str(time.time()))
            os.replace(pending, jobs / "heartbeat")
            last_pulse = time.monotonic()
        if not run_once(jobs):
            time.sleep(0.1)


if __name__ == "__main__":
    main()
