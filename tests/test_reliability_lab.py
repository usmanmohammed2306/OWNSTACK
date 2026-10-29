"""Lab safety and exact mutation checks; process evidence comes from the lab run."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock

import pytest
from sqlalchemy.engine import make_url
from ownstack import service

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ops.reliability.harness import CheckFailed, Lab, child_environment, local_url, percentiles
from ops.reliability.mutations import mutated
from ops.reliability.child import validate_lab_environment


@pytest.mark.parametrize("kind,function", [
    ("late_fence", service.accept_result), ("accepted_redelivery", service.accept_result),
    ("snapshot_fence", service.approve), ("tenant_scope", service.scoped),
    ("outbox", service.record),
])
def test_mutants_are_exact_in_memory_copies(kind, function):
    original = function.__code__
    changed, fingerprint = mutated(function, kind)
    assert function.__code__ is original
    assert changed.__code__ is not original
    assert changed.__name__ == function.__name__
    assert len(fingerprint) == 64
    assert changed.__code__.co_filename == f"<ownstack-lab-only:{kind}>"


def test_unknown_or_mismatched_mutant_refuses():
    with pytest.raises(ValueError, match="exactly one"):
        mutated(service.scoped, "late_fence")
    with pytest.raises(ValueError, match="exactly one"):
        mutated(service.record, "unknown")


@pytest.mark.parametrize("url", ["sqlite:///test.db", "postgresql+psycopg://u:p@remote.example/db",
    "postgresql+psycopg://u:p@db/db?options=-csearch_path=public"])
def test_lab_refuses_nonlocal_or_ambiguous_database(url):
    with pytest.raises(ValueError):
        local_url(url)


def test_child_environment_does_not_inherit_secrets(monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "never-inherit")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "never-inherit")
    schema = "ownstack_lab_" + "a" * 32
    url = make_url("postgresql+psycopg://u:p@db/db").update_query_dict({"options":
        f"-csearch_path={schema},pg_catalog -cstatement_timeout=5000 -clock_timeout=2000"})
    env = child_environment(url, schema, "synthetic-signing-secret")
    assert env["NEBIUS_API_KEY"] == ""
    assert env["OWNSTACK_MAX_LIVE_CALLS"] == "0"
    assert env["OWNSTACK_AI_MODE"] == "fixture"
    assert "AWS_SECRET_ACCESS_KEY" not in env and "HOME" not in env


def test_child_guard_refuses_main_runtime_before_connecting(monkeypatch):
    monkeypatch.setenv("OWNSTACK_DATABASE_URL", "postgresql+psycopg://u:p@db/db")
    monkeypatch.setenv("OWNSTACK_LAB_SCHEMA", "public")
    with pytest.raises(RuntimeError, match="own schema"):
        validate_lab_environment()


def test_percentiles_include_raw_denominator():
    assert percentiles([]) == {"samples": 0, "raw_ms": []}
    values = [4, 1, 2, 3]
    measured = percentiles(values)
    assert measured["samples"] == 4 and measured["raw_ms"] == values
    assert measured["p50_ms"] == 2.5 and measured["p95_ms"] == 4


def test_cli_refuses_existing_evidence(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("lab_cli", ROOT / "scripts/run_reliability_lab.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setenv("OWNSTACK_LAB_DATABASE_URL", "postgresql+psycopg://u:p@db/db")
    monkeypatch.setattr(sys, "argv", ["lab", "--output", str(tmp_path)])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2


def test_failed_run_preserves_report_and_reaps_real_child(tmp_path, monkeypatch):
    # Exercise failure cleanup without PostgreSQL or provider credentials.
    import ops.reliability.harness as harness
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                               env={}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    lab = Lab.__new__(Lab)
    lab.directory = tmp_path
    lab.processes = [{"process": process, "directory": tmp_path / "synthetic-child", "action": "worker"}]
    before = {"reserved_calls": 10, "counts": {}}
    lab.report = {"status": "running", "public_before": before}
    lab.public, lab.engine, lab.client = MagicMock(), MagicMock(), MagicMock()
    lab.http_samples, lab.recoveries = [], []
    lab.public_snapshot = lambda _: before
    session = MagicMock()
    session.__enter__.return_value.scalar.return_value = 10
    monkeypatch.setattr(harness, "Session", lambda _: session)
    def injected_failure():
        raise CheckFailed("Deliberate cleanup test")
    lab.start_api = injected_failure
    try:
        report = lab.execute()
        assert process.poll() is not None
        assert report["status"] == "failed" and report["all_child_processes_reaped"]
        saved = json.loads((tmp_path / "report.json").read_text())
        assert saved["failure"] == "Deliberate cleanup test"
        assert saved["public_before"] == saved["public_after"]
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)


def test_cli_records_initialization_failure_without_secret_text(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("lab_failure_cli", ROOT / "scripts/run_reliability_lab.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setenv("OWNSTACK_LAB_DATABASE_URL", "postgresql+psycopg://u:p@db/db")
    directory = tmp_path / "new-run"
    monkeypatch.setattr(sys, "argv", ["lab", "--output", str(directory)])
    def fail(*args):
        raise RuntimeError("PRIVATE-CONNECTION-DETAILS")
    monkeypatch.setattr(cli, "Lab", fail)
    assert cli.main() == 1
    saved = (directory / "initialization-failure.json").read_text()
    assert "PRIVATE-CONNECTION-DETAILS" not in saved
    assert json.loads(saved)["error_type"] == "RuntimeError"
