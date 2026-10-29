"""Offline interpretation scorecard. Never makes a live inference call."""
import json
from pathlib import Path
from ownstack.ai import classify
from ownstack.config import Settings

CASES = Path(__file__).resolve().parents[2] / "evals" / "interpretation_cases.json"


def simple_baseline(kind: str) -> str:
    return "engineering" if kind == "feature" else "configure"


def evaluate() -> dict:
    cases = json.loads(CASES.read_text())
    rows = []
    for case in cases:
        baseline = simple_baseline(case["kind"])
        fixture = classify(case["text"], case["kind"], Settings(ai_mode="fixture")).route
        rows.append({"id": case["id"], "expected": case["expected"],
                     "simple_baseline": baseline, "synthetic_fixture": fixture,
                     "baseline_correct": baseline == case["expected"],
                     "fixture_correct": fixture == case["expected"]})
    return {"cases": len(rows), "baseline_correct": sum(row["baseline_correct"] for row in rows),
            "fixture_correct": sum(row["fixture_correct"] for row in rows),
            "live_nebius_evaluated": False,
            "warning": "Synthetic fixture route quality is not live model evidence. Host policy still enforces the contract.",
            "rows": rows}


if __name__ == "__main__":
    print(json.dumps(evaluate(), indent=2))
