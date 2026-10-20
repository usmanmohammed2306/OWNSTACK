"""Read-only presentation of allowlisted, public historical lab evidence.

Never queries tenant state, invokes a model, executes an artifact, or presents an
old result as a new observation. Missing evidence fails closed rather than making
up a successful demonstration.
"""
import hashlib
import json
from pathlib import Path

from ownstack.runner import ROOT

EVIDENCE_DIR = ROOT / "docs" / "evidence"
ARTIFACTS = ("live-workflow.json", "live-patch-super.json", "manual-recovery.json",
             "live-model-comparison.json", "expiry-and-cap.json")


def historical_demo():
    records, inventory = {}, []
    for name in ARTIFACTS:
        raw = (EVIDENCE_DIR / name).read_bytes()
        records[name] = json.loads(raw)
        inventory.append({"path": "docs/evidence/" + name,
                          "sha256": hashlib.sha256(raw).hexdigest()})
    access = records["live-workflow.json"]
    patch = records["live-patch-super.json"]
    recovery = records["manual-recovery.json"]
    comparison = records["live-model-comparison.json"]
    attempt = access["access_attempts"][0]
    models = []
    for model_id in dict.fromkeys(row["model_id"] for row in comparison["rows"]):
        rows = [row for row in comparison["rows"] if row["model_id"] == model_id]
        models.append({"model_id": model_id, "correct": sum(row["correct"] for row in rows),
                       "total": len(rows), "mean_latency_ms": sum(row["latency_ms"] for row in rows) / len(rows),
                       "estimated_usd": sum(row["estimated_usd"] for row in rows)})
    return {
        "historical": True, "synthetic_tenants": True, "inference_calls_this_read": 0,
        "observed_at": access["observed_at"],
        "notice": "Saved October 7 lab evidence, not a fresh inference or current tenant state. Source hashes are not signatures.",
        "access": {"model_id": attempt["model_id"], "latency_ms": attempt["latency_ms"],
                   "state": attempt["state"], "outcome": access["access"], "nova": access["nova"],
                   "preview_checks": access["preview"]["counterfactual"]["checks"],
                   "preview_unexpected": access["preview"]["counterfactual"]["unexpected_delta_count"],
                   "saved_status": access["saved_after_refresh"]["status"]},
        "patch": {"model_id": patch["draft"]["model_id"],
                  "patch_hash": patch["draft"]["patch_hash"], "passed": patch["checks"]["passed"],
                  "stderr": patch["checks"]["stderr"], "release_state": patch["release_state"]},
        "recovery": {"author": recovery["author"], "not_live_model_success": recovery["not_live_model_success"],
                     "patch_hash": recovery["checks"]["patch_hash"], "passed": recovery["checks"]["passed"],
                     "stderr": recovery["checks"]["stderr"], "ai_call": recovery["correction"]["ai_call"]},
        "comparison": {"models": models, "baseline": comparison["baseline"],
                       "limitation": "Two synthetic cases per model; no quality ranking, latency distribution or reconciled billing claim."},
        "artifacts": inventory,
    }
