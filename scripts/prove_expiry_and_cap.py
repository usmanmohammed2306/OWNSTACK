"""Zero-inference HTTP proof of read-time expiry and exhausted-budget refusal."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time
from smoke_full_stack import call, login


def main():
    destination = Path("docs/evidence/expiry-and-cap.json")
    if destination.exists():
        raise SystemExit("Preserve existing evidence")
    admin, engineer, contractor = [login(name) for name in ("atlas-admin", "atlas-engineer", "atlas-contractor")]
    budget = call("GET", "/v1/inference-budget", admin)
    assert budget["mode"] == "nebius" and budget["remaining_calls"] == 0
    report = {"observed_at": datetime.now(timezone.utc).isoformat(), "budget_before": budget,
              "proposal_source": "manual-engineer-handoff", "ai_calls": 0}
    variation = None
    try:
        blocked = call("POST", "/v1/requests", admin, {"text": "Add PDF export for Project Atlas",
                        "kind": "feature", "project_id": "atlas-project"}, expected=201)
        report["cap_response"] = call("POST", f"/v1/requests/{blocked['id']}/interpret", admin, expected=429)
        assert call("GET", f"/v1/requests/{blocked['id']}/attempts", admin) == []
        expiry = datetime.now(timezone.utc) + timedelta(seconds=8)
        created = call("POST", "/v1/requests", admin, {
            "text": "Give atlas-contractor read-only access to Project Atlas for eight seconds",
            "kind": "access", "project_id": "atlas-project", "viewer_id": "atlas-contractor",
            "expires_at": expiry.isoformat()}, expected=201)
        handoff = call("POST", f"/v1/requests/{created['id']}/manual-handoff", engineer)
        proposal = call("GET", f"/v1/proposals/{handoff['proposal_id']}", admin)
        report["preview"] = call("POST", f"/v1/proposals/{proposal['id']}/preview", admin)
        variation = call("POST", f"/v1/proposals/{proposal['id']}/approve", admin,
                         {"proposal_hash": proposal["proposal_hash"]})["variation_id"]
        document = "/v1/host/projects/atlas-project/documents/atlas-roadmap"
        call("GET", document, contractor)
        time.sleep(max(0, (expiry - datetime.now(timezone.utc)).total_seconds()) + 0.25)
        report["after_expiry"] = call("GET", document, contractor, expected=403)
        report["expiry"] = "observed_denied_before_revoke"
        report["request_id"] = created["id"]
    finally:
        if variation:
            call("POST", f"/v1/variations/{variation}/revoke", admin)
        report["budget_after"] = call("GET", "/v1/inference-budget", admin)
        report["reserved_this_run"] = report["budget_after"]["reserved_calls"] - budget["reserved_calls"]
        destination.write_text(json.dumps(report, indent=2) + "\n")
        for identity in (admin, engineer, contractor):
            call("POST", "/v1/session/logout", identity)
        print(f"Saved expiry/cap evidence; new model reservations: {report['reserved_this_run']}")


if __name__ == "__main__":
    main()
