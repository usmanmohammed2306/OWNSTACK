"""Explicit one-call patch retry after a recorded failure, with no silent release."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from smoke_full_stack import call, login


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("item_id")
    parser.add_argument("--output", type=Path, default=Path("docs/evidence/live-patch-retry.json"))
    args = parser.parse_args()
    destination = args.output
    if destination.exists():
        parser.error("Evidence already exists; preserve it and choose a new explicit proof run")
    destination.parent.mkdir(parents=True, exist_ok=True)
    engineer = login("atlas-engineer")
    before = call("GET", "/v1/inference-budget", engineer)
    assert before["mode"] == "nebius" and before["remaining_calls"] >= 1
    item = next(row for row in call("GET", "/v1/engineering", engineer) if row["id"] == args.item_id)
    assert item["status"] == "draft_failed", item
    report = {"observed_at": datetime.now(timezone.utc).isoformat(), "item_id": item["id"],
              "budget_before": before, "release_state": "not_deployed", "live_patch_checked": False}
    try:
        draft = call("POST", f"/v1/engineering/{item['id']}/draft", engineer)
        report["draft"] = draft
        checks = call("POST", f"/v1/engineering/{item['id']}/verify", engineer)
        report["checks"] = checks
        assert checks["passed"] and checks["patch_hash"] == draft["patch_hash"], checks
        report["live_patch_checked"] = True
    except Exception as error:
        report["failure_type"] = type(error).__name__
        raise
    finally:
        report["evidence"] = call("GET", f"/v1/evidence/{item['request_id']}", engineer)
        report["events"] = call("GET", f"/v1/events?request_id={item['request_id']}", engineer)
        report["budget_after"] = call("GET", "/v1/inference-budget", engineer)
        report["reserved_this_run"] = report["budget_after"]["reserved_calls"] - before["reserved_calls"]
        destination.write_text(json.dumps(report, indent=2) + "\n")
        call("POST", "/v1/session/logout", engineer)
        print(f"Redacted evidence saved to {destination}; reserved calls: {report['reserved_this_run']}")


if __name__ == "__main__":
    main()
