"""Create a private offline graph demonstration with only the exact trusted fixture.

No model call or arbitrary candidate execution. The actual PDF oracle checks the
repository's allowlisted reference fixture. Main application records are untouched.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def prepare(directory):
    directory = directory.resolve()
    if not directory.is_relative_to(ROOT / ".private"):
        raise ValueError("Choose a new directory inside .private")
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    directory.chmod(0o700)
    database = directory / "demo.db"
    database.touch(mode=0o600, exist_ok=False)
    url = "sqlite:///" + str(database)
    env = {**os.environ, "OWNSTACK_DATABASE_URL": url, "OWNSTACK_AI_MODE": "off",
        "OWNSTACK_MAX_LIVE_CALLS": "0", "NEBIUS_API_KEY": "", "NEBIUS_MODEL_ID": "",
        "NEBIUS_PATCH_MODEL_ID": "", "OWNSTACK_ENV": "local", "OWNSTACK_REQUIRE_BACKGROUND": "false",
        "LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false", "LANGSMITH_API_KEY": "",
        "OWNSTACK_DEMO_PASSWORD": "demo-only-pass"}
    for command in ([sys.executable, "-m", "alembic", "upgrade", "head"],
                    [sys.executable, "-m", "ownstack.seed"]):
        subprocess.run(command, cwd=ROOT, env=env, capture_output=True, check=True, timeout=30)
    from sqlalchemy.orm import sessionmaker
    from ownstack.config import Settings
    from ownstack.db import make_engine
    from ownstack.models import ChangeRequest, EngineeringItem, Evidence, InferenceBudget
    from ownstack.patch_agent import fixture_patch
    from ownstack.policy import Principal
    from ownstack.repair import run_repair_one, serialize_run, start_repair
    from ownstack.runner import patch_hash, trusted_local_verification
    engine = make_engine(url)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(ai_mode="fixture", max_live_calls=0, nebius_key="", nebius_model="",
                        nebius_patch_model="", environment="local")
    try:
        original = fixture_patch()
        original["edits"][0]["new"] = "def export_pdf(project_name, rows):\n    return b'bad'\n"
        with factory() as db:
            # This demo starts exhausted, never with another allowance.
            db.get(InferenceBudget, "global").reserved_calls = 10
            db.add(ChangeRequest(id="graph-demo-request", tenant_id="atlas", requester_id="atlas-engineer",
                text="Offline LangGraph demonstration: PDF export for Atlas", kind="feature",
                project_id="atlas-project", status="engineering", revision=1))
            db.flush()
            db.add(EngineeringItem(id="graph-demo-item", tenant_id="atlas", request_id="graph-demo-request",
                patch=original, patch_hash=patch_hash(original), status="checks_failed"))
            db.add(Evidence(id="graph-demo-start", tenant_id="atlas", request_id="graph-demo-request",
                kind="patch_checks", subject_hash=patch_hash(original), result={"passed": False,
                "stderr": "Synthetic initial failure record, not a model response or executed check."},
                limitation="Constructed offline starting condition. Final trusted fixture checks are actual."))
            db.commit()
        with factory() as db:
            run = start_repair(db, "graph-demo-item", Principal("atlas-engineer", "atlas", "engineer"),
                               "graph-demo", patch_hash(original), settings=settings)
            db.commit()
            run_id = run.id
        def known_fixture(*_args, **_kwargs):
            return fixture_patch(), "fixture-not-live", {"live": False, "latency_ms": 0}
        run_repair_one(factory, settings, propose=known_fixture)
        run_repair_one(factory, settings, verify=trusted_local_verification)
        from ownstack.repair_models import RepairRun
        with factory() as db:
            saved = serialize_run(db, db.get(RepairRun, run_id))
            assert saved["state"] == "awaiting_review"
            assert db.get(InferenceBudget, "global").reserved_calls == 10
        report = {"private_database": str(database), "run_id": run_id,
            "engineering_item": "graph-demo-item", "mode": "synthetic-offline-generator",
            "checks": saved["attempts"][0]["checks"]["checks_completed"],
            "runner": saved["attempts"][0]["checks"]["runner"], "state": saved["state"],
            "human_adopted": False, "release_state": "not_deployed", "budget": 10, "model_calls": 0,
            "limit": "Exact repository fixture runs locally; this is not model generation or hostile-code isolation"}
        (directory / "demo.json").write_text(json.dumps(report, indent=2) + "\n")
        return report
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = prepare(args.private_output)
    except Exception as error:
        print(json.dumps({"passed": False, "error_type": type(error).__name__, "model_calls": 0}))
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
