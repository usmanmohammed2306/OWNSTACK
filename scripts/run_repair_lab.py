#!/usr/bin/env python3
"""Local durable repair experiment with synthetic proposals and real Docker checks.

No inference, credentials, production records or budget resets. Retains an
isolated SQLite fixture with the exhausted count ten and cap zero. Each phase
runs in a new process, so the experiment checks saved state across process exits.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
for name, value in {"OWNSTACK_AI_MODE": "fixture", "OWNSTACK_MAX_LIVE_CALLS": "0",
                    "NEBIUS_API_KEY": "", "NEBIUS_MODEL_ID": "", "NEBIUS_PATCH_MODEL_ID": "",
                    "OWNSTACK_ENV": "local", "OWNSTACK_VERIFIER_BACKEND": "docker"}.items():
    os.environ[name] = value

from sqlalchemy import select, func
from sqlalchemy.orm import sessionmaker
from ownstack.config import Settings
from ownstack.db import Base, make_engine
from ownstack.models import ChangeRequest, EngineeringItem, Evidence, InferenceBudget, Tenant, User
from ownstack.patch_agent import fixture_patch
from ownstack.policy import Principal
from ownstack.repair import (claim_work, reap_repairs, run_repair_one, save_candidate,
                            serialize_run, start_repair, stop_repair)
from ownstack.repair_models import RepairRun, RepairAttempt
from ownstack.runner import patch_hash
from ownstack.service import utcnow

PRINCIPAL = Principal("lab-engineer", "lab", "engineer")


def bad_patch():
    patch = fixture_patch()
    patch["edits"][0]["new"] = "def export_pdf(project_name, rows):\n    return b'not pdf'\n"
    return patch


def synthetic_proposal(_text, _settings, *, repair_context):
    # Deliberately fails once so the second candidate must use durable feedback.
    retry = repair_context["feedback"].get("oracle_version") == "pdf-external-v1"
    return (fixture_patch() if retry else bad_patch()), "fixture-not-live", {
        "live": False, "latency_ms": 0, "input_tokens": None, "output_tokens": None}


def fixture(factory, label):
    with factory() as db:
        request_id, item_id = label + "-request", label + "-item"
        patch = bad_patch()
        db.add(ChangeRequest(id=request_id, tenant_id="lab", requester_id="lab-engineer",
            text="Synthetic request: PDF export", kind="feature", status="engineering", revision=1))
        db.flush()
        db.add(EngineeringItem(id=item_id, tenant_id="lab", request_id=request_id,
            status="checks_failed", patch=patch, patch_hash=patch_hash(patch)))
        db.add(Evidence(id=label + "-original-failure", tenant_id="lab", request_id=request_id,
            kind="patch_checks", subject_hash=patch_hash(patch),
            result={"passed": False, "stderr": "Synthetic starting failure"},
            limitation="Synthetic failed fixture, not model output."))
        db.commit()
    with factory() as db:
        run = start_repair(db, item_id, PRINCIPAL, label + "-key", patch_hash(patch))
        run_id = run.id
        db.commit()
    return run_id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--child", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--claim-and-exit", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        factory = sessionmaker(bind=make_engine("sqlite:///" + str(args.child.resolve())), expire_on_commit=False)
        if args.claim_and_exit:
            with factory() as db:
                claim_work(db, Settings())
                db.commit()
            os._exit(23)  # Real process termination after durable claim, before proposal.
        run_repair_one(factory, propose=synthetic_proposal)
        return 0
    if not args.output:
        parser.error("--output NEW_DIRECTORY required; previous runs are never overwritten")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    database = output / "synthetic-state.db"
    engine = make_engine("sqlite:///" + str(database))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add(Tenant(id="lab", name="Synthetic repair experiment"))
        db.flush()
        db.add(User(id="lab-engineer", tenant_id="lab", role="engineer", password_hash="not-a-login"))
        db.add(InferenceBudget(id="global", reserved_calls=10))
        db.commit()
    report = {"started_at": datetime.now(timezone.utc).isoformat(),
        "synthetic_provider": True, "live_inference_calls": 0,
        "database": "synthetic-state.db (ignored local fixture)", "budget_before": 10,
        "checks": [], "child_processes": [], "runs": [],
        "limitations": ["Local SQLite, not PostgreSQL concurrency or production recovery.",
            "Handwritten synthetic proposals, not model quality or cost measurements.",
            "Docker output oracle is bounded, not a certified hostile-code sandbox.",
            "Forced child exit models loss after commit, not hardware failure."]}
    def check(name, condition):
        report["checks"].append({"name": name, "passed": bool(condition)})
        if not condition:
            raise AssertionError(name)
    def child(label, crash=False):
        cmd = [sys.executable, str(Path(__file__).resolve()), "--child", str(database)]
        if crash:
            cmd.append("--claim-and-exit")
        process = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=100,
                                 env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
        report["child_processes"].append({"label": label, "exit_code": process.returncode,
            "stderr": process.stderr[-2000:]})
        check(label + "_exit", process.returncode == (23 if crash else 0))
    try:
        run_id = fixture(factory, "repair")
        with factory() as db:
            original = db.get(RepairRun, run_id)
            repeat = start_repair(db, original.item_id, PRINCIPAL, "repair-key", original.original_patch_hash)
            check("duplicate_saved_run", repeat.id == run_id)
            db.commit()
        child("generation_1")
        with factory() as db:
            check("candidate_durable_before_checks", serialize_run(db, db.get(RepairRun, run_id))["attempts"][0]["state"] == "candidate_ready")
        child("verification_1")
        child("generation_2")
        child("verification_2")
        with factory() as db:
            run = db.get(RepairRun, run_id)
            state = serialize_run(db, run)
            report["runs"].append(state)
            check("failure_then_pass", [a["state"] for a in state["attempts"]] == ["failed", "passed"])
            check("human_review_only", run.state == "awaiting_review" and db.get(EngineeringItem, run.item_id).human_decision is None)
            check("original_patch_not_replaced", db.get(EngineeringItem, run.item_id).patch_hash == run.original_patch_hash)
            stop_repair(db, run_id)
            db.commit()

        crash_run = fixture(factory, "crash")
        child("exit_after_claim", crash=True)
        with factory() as db:
            attempt = db.get(RepairAttempt, db.get(RepairRun, crash_run).current_attempt_id)
            check("claim_survives_process_exit", attempt.state == "generating")
            stale_id = attempt.id
            # Shorten only the lab record's local clock so the experiment is quick.
            attempt.deadline_at = utcnow() - timedelta(seconds=1)
            db.commit()
        with factory() as db:
            check("reaper_creates_second_attempt", reap_repairs(db) == 1)
            db.commit()
        with factory() as db:
            check("late_first_candidate_discarded", not save_candidate(db, stale_id, fixture_patch(), "fixture-not-live", {"live": False}, Settings()))
            check("late_payload_not_saved", db.get(RepairAttempt, stale_id).candidate is None)
            stop_repair(db, crash_run)
            db.commit()
            report["runs"].append(serialize_run(db, db.get(RepairRun, crash_run)))

        takeover_run = fixture(factory, "takeover")
        with factory() as db:
            work = claim_work(db, Settings())
            db.commit()
        with factory() as db:
            stop_repair(db, takeover_run)
            db.commit()
        with factory() as db:
            check("takeover_fences_late_candidate", not save_candidate(db, work["attempt_id"], fixture_patch(), "fixture-not-live", {}, Settings()))
            db.commit()
            report["runs"].append(serialize_run(db, db.get(RepairRun, takeover_run)))
        with factory() as db:
            report["budget_after"] = db.get(InferenceBudget, "global").reserved_calls
            check("exhausted_budget_unchanged", report["budget_after"] == 10)
            check("no_active_attempts", db.scalar(select(func.count(RepairAttempt.id)).where(RepairAttempt.state.in_(("queued", "generating", "candidate_ready", "verifying")))) == 0)
        report["passed"] = True
    except Exception as error:
        report["passed"] = False
        report["failure"] = type(error).__name__ + ": " + str(error)
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report["source_sha256"] = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in (
            "src/ownstack/repair.py", "src/ownstack/repair_models.py", "src/ownstack/repair_api.py",
            "src/ownstack/patch_agent.py", "src/ownstack/runner.py", "src/ownstack/pdf_oracle.py",
            "scripts/run_repair_lab.py")}
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"passed": report["passed"], "checks": len(report["checks"]),
                          "report": str(output / "report.json"), "live_calls": 0}))
        engine.dispose()
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
