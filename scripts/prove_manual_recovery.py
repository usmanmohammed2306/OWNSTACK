"""Correct the inspected synthetic failed draft through the AI-off engineer path.

The correction is authored by the coding assistant, not the provider or user.
No model call, human acceptance, deployment or arbitrary host execution occurs.
"""
import argparse
from datetime import datetime, timezone
import difflib
import json
from pathlib import Path
from smoke_full_stack import call, login


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("item_id")
    args = parser.parse_args()
    destination = Path("docs/evidence/manual-recovery.json")
    if destination.exists():
        parser.error("Preserve the existing recovery artifact")
    engineer = login("atlas-engineer")
    before = call("GET", "/v1/inference-budget", engineer)
    original = call("GET", f"/v1/engineering/{args.item_id}", engineer)
    assert original["status"] == "checks_failed" and original["patch"]
    source = call("GET", "/v1/engineering-source", engineer)
    replacement = Path("docs/evidence/pdf-agent-manual-correction.py").read_text()
    patch = {"edits": [{"path": source["path"], "old": source["source"], "new": replacement}]}
    report = {"observed_at": datetime.now(timezone.utc).isoformat(), "author": "coding-assistant-manual-path",
              "not_live_model_success": True, "original_failed_item": original,
              "release_state": "not_deployed", "budget_before": before}
    try:
        report["correction"] = call("POST", f"/v1/engineering/{args.item_id}/manual-patch", engineer, {"patch": patch})
        report["diff"] = "".join(difflib.unified_diff(source["source"].splitlines(True), replacement.splitlines(True),
                                                     fromfile="a/" + source["path"], tofile="b/" + source["path"]))
        report["checks"] = call("POST", f"/v1/engineering/{args.item_id}/verify", engineer)
        assert report["checks"]["passed"]
        assert report["checks"]["patch_hash"] == report["correction"]["patch_hash"]
        report["final_item"] = call("GET", f"/v1/engineering/{args.item_id}", engineer)
        assert report["final_item"]["human_decision"] is None
    finally:
        report["budget_after"] = call("GET", "/v1/inference-budget", engineer)
        report["reserved_this_run"] = report["budget_after"]["reserved_calls"] - before["reserved_calls"]
        destination.write_text(json.dumps(report, indent=2) + "\n")
        call("POST", "/v1/session/logout", engineer)
        print(f"Saved manual recovery evidence; new model reservations: {report['reserved_this_run']}")


if __name__ == "__main__":
    main()
