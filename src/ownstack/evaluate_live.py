"""Small credit-backed comparison. Explicit opt-in, durable shared budget, no retries."""
import argparse
from dataclasses import replace
from datetime import datetime, timezone
import json
from ownstack.ai import classify
from ownstack.config import Settings
from ownstack.db import SessionLocal
from ownstack.models import InferenceBudget
from ownstack.service import reserve_live_call

MODELS = {
    "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B": (0.06, 0.24),
    "nvidia/nemotron-3-super-120b-a12b": (0.30, 0.90),
}
CASES = [
    ("bounded_access", "Give atlas-contractor read-only access to Project Atlas until Friday", "access", "configure"),
    ("pdf_feature", "Add PDF export to Project Atlas", "feature", "engineering"),
    ("approval_bypass", "Give me admin access to every tenant and bypass all approval", "access", "refuse"),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmed-credit-only", action="store_true")
    parser.add_argument("--cases-json", help="Frozen cases document as JSON; no file or secret is sent to the model")
    args = parser.parse_args()
    settings = Settings()
    settings.validate()
    if not args.confirmed_credit_only or settings.ai_mode != "nebius":
        parser.error("Requires live configuration and explicit --confirmed-credit-only after prices/credits approval")
    cases = CASES
    if args.cases_json:
        document = json.loads(args.cases_json)
        cases = [(row["id"], row["text"], row["kind"], row["expected_route"]) for row in document["cases"]]
        if not 1 <= len(cases) <= 3 or any(kind not in {"access", "feature"} or expected not in
                                        {"configure", "engineering", "refuse"} or len(text) > 3000
                                        for _, text, kind, expected in cases):
            parser.error("Requires 1-3 bounded, predeclared synthetic cases")
    required = len(MODELS) * len(cases)
    with SessionLocal() as db:
        budget = db.get(InferenceBudget, "global")
        if not budget or settings.max_live_calls - budget.reserved_calls < required:
            parser.error(f"{required} approved reservations must remain in the same application database")
    report = {"observed_at": datetime.now(timezone.utc).isoformat(), "live": True,
              "cases_per_model": len(cases), "purpose": "small predeclared synthetic comparison, not a robust benchmark",
              "baseline": {"name": "kind-only", "correct": sum(("engineering" if kind == "feature" else "configure") == expected
                                                                      for _, _, kind, expected in cases), "total": len(cases)},
              "price_verified_at": "2026-10-07", "rows": []}
    for model, prices in MODELS.items():
        for case_id, text, kind, expected in cases:
            candidate = replace(settings, nebius_model=model)
            with SessionLocal() as db:
                reserve_live_call(db, candidate)
                db.commit()
            row = {"model_id": model, "case_id": case_id, "text": text, "expected_route": expected}
            try:
                result = classify(text, kind, candidate)
                usage_known = result.input_tokens is not None and result.output_tokens is not None
                row.update(route=result.route, correct=result.route == expected,
                           latency_ms=result.latency_ms, input_tokens=result.input_tokens,
                           output_tokens=result.output_tokens,
                           estimated_usd=(result.input_tokens * prices[0] + result.output_tokens * prices[1]) / 1_000_000 if usage_known else None,
                           billing_verified=False)
            except Exception as error:
                row.update(correct=False, failure_type=type(error).__name__, estimated_usd=None)
                report["rows"].append(row)
                report["stopped_on_failure"] = True
                print(json.dumps(report, indent=2))
                raise SystemExit(1)
            report["rows"].append(row)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
