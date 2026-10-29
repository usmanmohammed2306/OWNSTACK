#!/usr/bin/env python3
"""Real PostgreSQL concurrent repair claims, committed process death and fencing.

No provider or candidate execution occurs. A retained uniquely named schema holds
synthetic data with the existing exhausted budget copied, empty keys and cap zero.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for name, value in {"OWNSTACK_AI_MODE": "fixture", "OWNSTACK_MAX_LIVE_CALLS": "0",
                   "OWNSTACK_AI_TIMEOUT_SECONDS": "10", "NEBIUS_API_KEY": "",
                   "NEBIUS_MODEL_ID": "", "NEBIUS_PATCH_MODEL_ID": "", "OWNSTACK_ENV": "local"}.items():
    os.environ[name] = value

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from ops.reliability.harness import child_environment, local_url, Lab
from ownstack.config import Settings
from ownstack.db import Base
from ownstack.models import EngineeringItem, InferenceBudget, Tenant, User
from ownstack.patch_agent import fixture_patch
from ownstack.repair import claim_work, reap_repairs, save_candidate, serialize_run, stop_repair
from ownstack.repair_models import RepairAttempt, RepairRun
from ownstack.service import utcnow
from scripts.run_repair_lab import fixture


def child(args):
    from ops.reliability.child import validate_lab_environment
    validate_lab_environment()
    directory = args.directory.resolve()
    directory.mkdir(exist_ok=True)
    def emit(event, **values):
        with (directory / "trace.jsonl").open("a") as stream:
            stream.write(json.dumps({"event": event, "pid": os.getpid(), **values}) + "\n")
    engine = create_engine(Settings().database_url)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        assert db.scalar(text("SELECT current_schema()")) == os.environ["OWNSTACK_LAB_SCHEMA"]
        assert db.get(InferenceBudget, "global").reserved_calls == 10
    if args.action == "claim":
        emit("ready")
        deadline = time.monotonic() + 30
        while not (directory.parent / "release-claims").exists():
            if time.monotonic() > deadline:
                raise RuntimeError("Barrier timed out")
            time.sleep(.01)
        with factory() as db:
            work = claim_work(db, Settings())
            db.commit()
        emit("claimed", attempt_id=work["attempt_id"] if work else None)
        if work and args.hold:
            emit("holding_after_commit")
            while time.monotonic() < deadline:
                time.sleep(.02)
            raise RuntimeError("Expected parent kill after committed claim")
    elif args.action == "reap":
        with factory() as db:
            count = reap_repairs(db)
            db.commit()
        emit("reaped", count=count)
    elif args.action == "late":
        with factory() as db:
            saved = save_candidate(db, args.attempt_id, fixture_patch(), "fixture-not-live", {"live": False}, Settings())
            db.commit()
        emit("late_result", accepted=saved)
    engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--directory", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--action", choices=["claim", "reap", "late"], help=argparse.SUPPRESS)
    parser.add_argument("--attempt-id", help=argparse.SUPPRESS)
    parser.add_argument("--hold", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.action:
        try:
            child(args)
            return 0
        except Exception as error:
            # DB exceptions may include credentials. Only disclose the class.
            print(json.dumps({"error_type": type(error).__name__}))
            return 1
    if not args.output or not os.environ.get("OWNSTACK_LAB_DATABASE_URL"):
        parser.error("--output NEW_DIRECTORY and explicit local OWNSTACK_LAB_DATABASE_URL required")
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "checks": [], "children": [],
              "live_inference_calls": 0, "provider_calls": 0, "schema_retained": True,
              "limits": ["Synthetic records and shortened lab deadlines, not production recovery.",
                         "No generation, candidate execution, HTTP or remote cancellation in this experiment.",
                         "Metadata fixture, not migration, backup or independent security certification."]}
    processes, public, engine = [], None, None
    def check(name, passed):
        report["checks"].append({"name": name, "passed": bool(passed)})
        if not passed:
            raise AssertionError(name)
    def traces(handle):
        path = handle["directory"] / "trace.jsonl"
        if not path.exists():
            return []
        rows = []
        for line in path.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return rows
    def wait_for(handle, event):
        until = time.monotonic() + 15
        while time.monotonic() < until:
            rows = [row for row in traces(handle) if row["event"] == event]
            if rows:
                return rows[-1]
            if handle["process"].poll() is not None:
                raise RuntimeError("Child ended before checkpoint")
            time.sleep(.01)
        raise RuntimeError("Child checkpoint timed out")
    def spawn(action, **options):
        child_dir = directory / ("child-" + str(len(processes)) + "-" + action)
        child_dir.mkdir()
        command = [sys.executable, str(Path(__file__).resolve()), "--action", action, "--directory", str(child_dir)]
        for key, value in options.items():
            command.append("--" + key.replace("_", "-"))
            if value is not True:
                command.append(str(value))
        with (child_dir / "process.log").open("wb") as stream:
            process = subprocess.Popen(command, cwd=child_dir, env=env, stdout=stream, stderr=subprocess.STDOUT)
        handle = {"process": process, "directory": child_dir, "action": action}
        processes.append(handle)
        return handle
    try:
        url = local_url(os.environ["OWNSTACK_LAB_DATABASE_URL"])
        public = create_engine(url)
        schema = "ownstack_lab_" + uuid4().hex
        report["schema"] = schema
        with public.begin() as db:
            report["main_before"] = Lab.public_snapshot(db)
            check("existing_budget_exhausted", report["main_before"]["reserved_calls"] == 10)
            db.execute(text(f'CREATE SCHEMA "{schema}"'))
        scoped = url.update_query_dict({"options": f"-csearch_path={schema},pg_catalog -cstatement_timeout=5000 -clock_timeout=2000"})
        env = child_environment(scoped, schema, uuid4().hex + uuid4().hex)
        engine = create_engine(scoped)
        with engine.begin() as db:
            check("isolated_schema", db.scalar(text("SELECT current_schema()")) == schema)
            Base.metadata.create_all(db)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        with factory() as db:
            db.add(Tenant(id="lab", name="Synthetic PostgreSQL repair lab"))
            db.flush()
            db.add(User(id="lab-engineer", tenant_id="lab", role="engineer", password_hash="not-a-login"))
            db.add(InferenceBudget(id="global", reserved_calls=report["main_before"]["reserved_calls"]))
            db.commit()
        run_id = fixture(factory, "postgres-repair")
        contenders = [spawn("claim", hold=True), spawn("claim", hold=True)]
        for contender in contenders:
            wait_for(contender, "ready")
        (directory / "release-claims").touch(exist_ok=False)
        results = [wait_for(contender, "claimed") for contender in contenders]
        winners = [i for i, result in enumerate(results) if result["attempt_id"]]
        check("one_of_two_concurrent_claims", len(winners) == 1)
        winner = contenders[winners[0]]
        stale_id = results[winners[0]]["attempt_id"]
        wait_for(winner, "holding_after_commit")
        winner["process"].kill()
        check("committed_worker_killed", winner["process"].wait(timeout=5) == -9)
        loser = contenders[1 - winners[0]]
        check("other_worker_exits_without_claim", loser["process"].wait(timeout=5) == 0)
        with factory() as db:
            check("claim_survives_sigkill", db.get(RepairAttempt, stale_id).state == "generating")
            db.get(RepairAttempt, stale_id).deadline_at = utcnow() - timedelta(seconds=1)
            db.commit()
        reaper = spawn("reap")
        check("new_reaper_process", reaper["process"].wait(timeout=15) == 0)
        check("reaper_advances_once", traces(reaper)[-1]["count"] == 1)
        with factory() as db:
            current_id = db.get(RepairRun, run_id).current_attempt_id
            check("attempt_two_is_current", current_id != stale_id and db.get(RepairAttempt, current_id).number == 2)
        late = spawn("late", attempt_id=stale_id)
        check("late_process_exits", late["process"].wait(timeout=15) == 0)
        check("old_result_discarded", traces(late)[-1]["accepted"] is False)
        restarted = spawn("claim")
        check("restarted_worker_exits", restarted["process"].wait(timeout=15) == 0)
        check("restarted_worker_claims_second", traces(restarted)[-1]["attempt_id"] == current_id)
        with factory() as db:
            check("late_payload_not_saved", db.get(RepairAttempt, stale_id).candidate is None)
            stop_repair(db, run_id)
            db.commit()
            state = serialize_run(db, db.get(RepairRun, run_id))
            report["run"] = state
            check("no_active_attempts", all(a["state"] not in {"queued", "generating", "candidate_ready", "verifying"} for a in state["attempts"]))
            check("fixture_budget_unchanged", db.get(InferenceBudget, "global").reserved_calls == 10)
        report["passed"] = True
    except Exception as error:
        report["passed"] = False
        report["error_type"] = type(error).__name__
    finally:
        for handle in processes:
            process = handle["process"]
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            report["children"].append({"action": handle["action"], "exit_code": process.returncode,
                                       "trace": traces(handle)})
        report["all_children_reaped"] = all(h["process"].poll() is not None for h in processes)
        if public:
            try:
                with public.connect() as db:
                    report["main_after"] = Lab.public_snapshot(db)
                unchanged = report.get("main_before") == report["main_after"]
                report["checks"].append({"name": "main_counts_and_budget_unchanged", "passed": unchanged})
                report["passed"] = report.get("passed", False) and unchanged
            except Exception as error:
                report["passed"], report["finalization_error_type"] = False, type(error).__name__
            public.dispose()
        if engine:
            engine.dispose()
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report["source_sha256"] = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in (
            "src/ownstack/repair.py", "src/ownstack/repair_models.py", "src/ownstack/patch_agent.py",
            "scripts/run_repair_postgres_lab.py", "scripts/run_repair_lab.py")}
        (directory / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"passed": report.get("passed", False), "checks": len(report["checks"]),
                          "report": str(directory / "report.json"), "live_calls": 0}))
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
