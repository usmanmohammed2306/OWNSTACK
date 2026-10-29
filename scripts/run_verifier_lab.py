"""Offline adversarial PDF verifier experiment. Requires a local Docker image.

No inference, no database, no image pull. Never execute these candidates on host.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import tempfile
import time
from uuid import uuid4
from ownstack.patch_agent import fixture_patch, REFERENCE_IMPLEMENTATION
from ownstack.runner import current_provenance, materialize, verify_in_docker
from ownstack.policy import digest
from ownstack.bounded_process import capture
SIDECAR_COMPOSE_ARGS = ['-f', 'compose.full.yaml']


def sidecar_check(patch):
    command = ["docker", "compose", *SIDECAR_COMPOSE_ARGS, "exec", "-T", "verifier", "python", "-c",
               "import json,sys; from ownstack.verifier_service import check; print(json.dumps(check(json.load(sys.stdin))))"]
    captured = capture(command, json.dumps(patch).encode(), timeout=30, limit=1048576)
    if captured["failure"] or captured["exit_code"] != 0:
        raise RuntimeError("Sidecar control unavailable: " + captured["stderr"])
    return json.loads(captured["stdout_bytes"])


def legacy_early_exit() -> dict:
    """Reproduce the previous exact exit-code oracle in a disposable container."""
    patch = fixture_patch()
    patch["edits"][0]["new"] = "import os\nos._exit(0)\n"
    name = "ownstack-legacy-control-" + uuid4().hex
    with tempfile.TemporaryDirectory(prefix="ownstack-legacy-control-") as temporary:
        directory = Path(temporary)
        materialize(patch, directory)
        directory.chmod(0o755)
        try:
            result = subprocess.run(["docker", "run", "--rm", "--pull", "never", "--name", name,
                "--user", "65534:65534", "--network", "none", "--read-only", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges", "--pids-limit", "16", "--memory", "256m", "--cpus", "1",
                "--mount", f"type=bind,src={directory},dst=/workspace,readonly", "--workdir", "/workspace",
                "python:3.12-slim", "python", "-B", "-m", "unittest", "discover", "-s", "checks", "-v"],
                capture_output=True, text=True, timeout=20)
            return {"exit_code": result.returncode, "legacy_would_pass": result.returncode == 0,
                    "stdout": result.stdout[-4000:], "stderr": result.stderr[-4000:],
                    "patch_hash": digest(patch), "valid_export_implemented": False}
        finally:
            subprocess.run(["docker", "rm", "--force", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)


def run(backend="docker") -> dict:
    mutations = {
        "known_reference": (REFERENCE_IMPLEMENTATION, True),
        "early_exit_zero": ("import os\nos._exit(0)\n", False),
        "system_exit_zero": ("raise SystemExit(0)\n", False),
        "forged_success_json": ('import os\nos.write(1,b\'{"passed":true,"checks_completed":7}\')\nos._exit(0)', False),
        "test_framework_patch": ('import unittest\nunittest.TestCase.run = lambda *args: None\ndef export_pdf(*args): return b"not pdf"', False),
        "wrong_scope": (REFERENCE_IMPLEMENTATION.replace('lines = [project_name, *rows]', 'lines = ["Project Nova", *rows]'), False),
        "bad_xref": (REFERENCE_IMPLEMENTATION.replace('xref = len(output)', 'xref = len(output) + 1'), False),
        "missing_rows": (REFERENCE_IMPLEMENTATION.replace('lines = [project_name, *rows]', 'lines = [project_name]'), False),
        "unescaped_text": (REFERENCE_IMPLEMENTATION.replace('({esc(line)}) Tj', '({line}) Tj'), False),
        "output_flood": ('import os\nwhile True: os.write(1,b"x"*65536)', False),
        "cpu_loop": ('while True: pass', False),
        "forbidden_write": ('open("/ownstack-forbidden-write","w").write("probe")\n' + REFERENCE_IMPLEMENTATION, False),
        "outbound_network": ('import socket\nsocket.create_connection(("1.1.1.1",443),timeout=1)\n' + REFERENCE_IMPLEMENTATION, False),
    }
    if backend == "sidecar":
        mutations["queue_volume_denied"] = ('open("/srv/jobs/heartbeat","rb").read(1)\n' + REFERENCE_IMPLEMENTATION, False)
        mutations["escaped_descendant_denied"] = (
            'import os,time\nif os.fork() == 0:\n    os.setsid()\n    if os.fork() > 0: os._exit(0)\n    time.sleep(120)\n    os._exit(0)\n' + REFERENCE_IMPLEMENTATION, False)
    records = []
    for name, (source, expected) in mutations.items():
        patch = fixture_patch()
        patch["edits"][0]["new"] = source
        started = time.monotonic()
        result = sidecar_check(patch) if backend == "sidecar" else verify_in_docker(patch)
        executed = result.get("exit_code") is not None and (result.get("image_id", "").startswith("sha256:")
                    if backend == "docker" else result.get("runner") == "no-network-sidecar-external-oracle")
        cleanup = (result.get("descendants_reaped") is True and result.get("remaining_descendants") == 0
                   and result.get("signalled_descendants", 0) == 0) if name == "escaped_descendant_denied" else True
        policy_matches = all(result.get(key) == value for key,value in current_provenance().items())
        records.append({"case": name, "expected_pass": expected, "candidate_executed": executed,
                        "matched_expectation": executed and cleanup and policy_matches and result["passed"] is expected,
                        "duration_ms": round((time.monotonic() - started) * 1000, 2), "result": result})
        print(f"{name}: passed={result['passed']} expected={expected}", flush=True)
    legacy = legacy_early_exit()
    return {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
            "kind": "offline-adversarial-verifier-experiment", "backend": backend, "live_inference_calls": 0,
            "provenance": current_provenance(), "script_hash": digest(Path(__file__).read_text()),
            "source_inventory": {str(path): digest(path.read_text()) for path in
                [Path("src/ownstack/") / name for name in ("runner.py", "bounded_process.py", "verifier_service.py", "patch_agent.py", "process_supervisor.py")]
                + [Path("compose.full.yaml")]},
            "legacy_control": legacy, "cases": records,
            "passed": all(row["matched_expectation"] for row in records) and legacy["legacy_would_pass"],
            "limitations": ["This finite authored matrix is not a hostile-code sandbox certification.",
                "Only this owned, narrow PDF subset is supported; other valid PDF layouts may be rejected.",
                "Docker uses a shared kernel. Queued runtime reuses its container with a fresh unprivileged process per job.",
                "No live model quality, real customer benefit, public deployment, or user-study outcome is measured."]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--backend", choices=("docker", "sidecar"), default="docker")
    parser.add_argument('--compose-project')
    parser.add_argument('--compose-env-file',action='append',default=[])
    parser.add_argument('--compose-overlay')
    args = parser.parse_args()
    if args.compose_project: SIDECAR_COMPOSE_ARGS.extend(['-p',args.compose_project])
    for path in args.compose_env_file: SIDECAR_COMPOSE_ARGS.extend(['--env-file',path])
    if args.compose_overlay: SIDECAR_COMPOSE_ARGS.extend(['-f',args.compose_overlay])
    # Reserve evidence path before execution; never overwrite a failed run.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as handle:
        try:
            report = run(args.backend)
        except Exception as error:
            report = {"passed": False, "error_type": type(error).__name__, "error": str(error)[:1000],
                      "live_inference_calls": 0, "incomplete": True}
        json.dump(report, handle, indent=2)
        handle.write("\n")
    raise SystemExit(0 if report["passed"] else 1)
