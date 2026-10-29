"""Run a zero-inference graph contract experiment and retain its result."""
import argparse
import json
from pathlib import Path
from ownstack.trajectory_eval import evaluate_file


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=root / "evals/investigation_v1/cases.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate_file(args.cases)
    # Exclusive creation preserves failed and earlier runs rather than overwriting.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as handle:
        handle.write(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": report["passed"], "total": report["total"],
        "live_calls": 0, "report": str(args.output)}))
    raise SystemExit(0 if report["passed"] == report["total"] else 1)


if __name__ == "__main__":
    main()
