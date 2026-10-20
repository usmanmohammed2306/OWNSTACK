"""Run at most three budget-reserved calls through the real application, never a mock.

Requires prior user authorization, verified balance/prices, configured live stack.
Stops on failure rather than consuming credits with automatic retries.
"""
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import time
from smoke_full_stack import call, login


def interpret(client, request_id):
    first = call("POST", f"/v1/requests/{request_id}/interpret", client, expected=202)
    repeated = call("POST", f"/v1/requests/{request_id}/interpret", client, expected=202)
    assert repeated["attempt_id"] == first["attempt_id"]
    deadline = time.monotonic() + 125
    while time.monotonic() < deadline:
        row = call("GET", f"/v1/requests/{request_id}", client)
        if row["status"] not in {"new", "interpreting"}:
            break
        time.sleep(1)
    attempts = call("GET", f"/v1/requests/{request_id}/attempts", client)
    assert len(attempts) == 1 and attempts[0]["state"] == "accepted", attempts
    assert attempts[0]["model_id"].startswith("nvidia/")
    return call("GET", f"/v1/proposals/{row['accepted_proposal_id']}", client), attempts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("docs/evidence/live-workflow.json"))
    args = parser.parse_args()
    report = {"observed_at": datetime.now(timezone.utc).isoformat(), "live": False}
    destination = args.output
    if destination.exists():
        parser.error("Preserve existing evidence; choose a new --output path before another authorized run")
    destination.parent.mkdir(parents=True, exist_ok=True)
    admin, engineer, contractor, nova = [login(user) for user in
        ("atlas-admin", "atlas-engineer", "atlas-contractor", "nova-admin")]
    before = call("GET", "/v1/inference-budget", admin)
    assert before["mode"] == "nebius" and before["remaining_calls"] >= 3, before
    report["budget_before"] = before
    try:
        created = call("POST", "/v1/requests", admin, {
            "text": "Give atlas-contractor read-only access to Project Atlas until Friday",
            "kind": "access", "project_id": "atlas-project", "viewer_id": "atlas-contractor",
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()}, expected=201)
        proposal, attempts = interpret(admin, created["id"])
        report["access_attempts"] = attempts
        assert proposal["route"] == "configure", proposal
        preview = call("POST", f"/v1/proposals/{proposal['id']}/preview", admin)
        assert preview["matches_saved_proposal"]
        activated = call("POST", f"/v1/proposals/{proposal['id']}/approve", admin,
                         {"proposal_hash": proposal["proposal_hash"]})
        document = "/v1/host/projects/atlas-project/documents/atlas-roadmap"
        try:
            call("GET", document, contractor)
            call("GET", document, nova, expected=404)
        finally:
            call("POST", f"/v1/variations/{activated['variation_id']}/revoke", admin)
        call("GET", document, contractor, expected=403)
        saved = call("GET", f"/v1/requests/{created['id']}", admin)
        report.update(live=True, access="observed_enforced_then_revoked", nova="observed_denied",
                      access_request_id=created["id"], preview=preview,
                      saved_after_refresh=saved, access_evidence=call("GET", f"/v1/evidence/{created['id']}", admin))
        feature = call("POST", "/v1/requests", engineer, {
            "text": "Add PDF export for Project Atlas", "kind": "feature", "project_id": "atlas-project"}, expected=201)
        proposal, attempts = interpret(engineer, feature["id"])
        report["feature_attempts"] = attempts
        assert proposal["route"] == "engineering", proposal
        item = next(row for row in call("GET", "/v1/engineering", engineer) if row["request_id"] == feature["id"])
        draft = call("POST", f"/v1/engineering/{item['id']}/draft", engineer)
        checks = call("POST", f"/v1/engineering/{item['id']}/verify", engineer)
        report.update(engineering_item=item["id"], draft=draft, checks=checks,
                      release_state="not_deployed", feature_evidence=call("GET", f"/v1/evidence/{feature['id']}", engineer))
        assert checks["passed"] and checks["patch_hash"] == draft["patch_hash"], checks
        # Independent human review remains required. This script does not accept or release code.
    except Exception as error:
        report["failure_type"] = type(error).__name__
        raise
    finally:
        report["budget_after"] = call("GET", "/v1/inference-budget", admin)
        report["reserved_this_run"] = report["budget_after"]["reserved_calls"] - before["reserved_calls"]
        destination.write_text(json.dumps(report, indent=2) + "\n")
        for identity in (admin, engineer, contractor, nova):
            call("POST", "/v1/session/logout", identity)
        print(f"Redacted evidence saved to {destination}; reserved calls: {report['reserved_this_run']}")


if __name__ == "__main__":
    main()
