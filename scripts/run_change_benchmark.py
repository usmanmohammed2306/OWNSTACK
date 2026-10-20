#!/usr/bin/env python3
"""Offline baseline evaluation and optional saved-output scoring. Never runs AI."""
import argparse
import json
from pathlib import Path

from ownstack.change_benchmark import DATASET, run_offline, save_report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--split", choices=("dev", "held_out"), default="held_out")
    parser.add_argument("--import-results", type=Path, help="Saved provider artifact only. No network.")
    parser.add_argument("--output-dir", required=True, type=Path, help="New directory, refuses overwrite")
    args = parser.parse_args()
    report = run_offline(args.dataset, args.split, args.import_results)
    path = save_report(report, args.output_dir)
    print(json.dumps({"report": str(path), "network_calls": 0, "independent_review": "pending",
                      "cases": {key: value["cases"] for key, value in report["baselines"].items()},
                      "route_correct": {key: value["metrics"]["route_correct"]["numerator"] for key, value in report["baselines"].items()},
                      "exact_correct": {key: value["metrics"]["exact_correct"]["numerator"] for key, value in report["baselines"].items()}}, indent=2))


if __name__ == "__main__":
    main()
