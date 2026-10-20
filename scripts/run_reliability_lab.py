"""Run the isolated, zero-inference PostgreSQL fault lab. Existing outputs survive."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ops.reliability.harness import Lab


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 10:
        parser.error("Use 1..10 repetitions; freeze the workload before comparing")
    value = os.environ.get("OWNSTACK_LAB_DATABASE_URL")
    if not value:
        parser.error("Set OWNSTACK_LAB_DATABASE_URL explicitly to the existing local PostgreSQL database")
    if args.output.exists():
        parser.error("Choose a new output directory; failed runs are never overwritten")
    # Parent also loads no live credentials from the workspace .env.
    for key in ("NEBIUS_API_KEY", "NEBIUS_MODEL_ID", "NEBIUS_PATCH_MODEL_ID"):
        os.environ[key] = ""
    os.environ.update(OWNSTACK_AI_MODE="off", OWNSTACK_MAX_LIVE_CALLS="0")
    try:
        lab = Lab(value, args.output.resolve(), args.repeats)
    except Exception as error:
        # Connection errors can contain credentials; persist the type, never repr.
        args.output.mkdir(parents=True, exist_ok=True)
        failed = {"status": "failed", "stage": "initialization", "error_type": type(error).__name__,
                  "live_calls": 0, "schema_cleanup_attempted": False}
        with (args.output / "initialization-failure.json").open("x") as stream:
            json.dump(failed, stream, indent=2)
        print(json.dumps(failed))
        return 1
    report = lab.execute()
    print(json.dumps({"status": report["status"], "report": str(args.output / "report.json"),
        "checks_passed": sum(row["passed"] for row in report["checks"]), "mutants_detected": len(report["mutants"]),
        "live_calls": 0, "all_children_reaped": report["all_child_processes_reaped"]}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
