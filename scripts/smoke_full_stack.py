"""Exercise the local HTTP stack, including PostgreSQL and the verifier sidecar.

This script uses only synthetic demo users and never invokes a model.
"""
import json
import os
from http.cookiejar import CookieJar
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener
from uuid import uuid4

from ownstack.patch_agent import fixture_patch
from ownstack.proof import verify_envelope
from ownstack.pdf_oracle import is_external_pass


BASE = os.getenv("OWNSTACK_SMOKE_URL", "http://127.0.0.1:8080").rstrip("/")
PASSWORD = os.getenv("OWNSTACK_DEMO_PASSWORD", "demo-only-pass")


class DemoClient:
    def __init__(self):
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))
        self.csrf = ""


def call(method: str, path: str, token: DemoClient | None = None, body: dict | None = None,
         expected: int = 200) -> dict | list:
    headers = {"Content-Type": "application/json"}
    if token and token.csrf:
        headers["X-CSRF-Token"] = token.csrf
    if method == "POST":
        headers["Idempotency-Key"] = uuid4().hex
        headers["Origin"] = BASE
    data = json.dumps(body).encode() if body is not None else None
    request = Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with (token.opener if token else build_opener()).open(request, timeout=75) as response:
            status, payload = response.status, json.load(response)
    except HTTPError as error:
        status, raw = error.code, error.read().decode()
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {"detail": raw[:300]}
    assert status == expected, f"{method} {path}: expected {expected}, got {status}: {payload}"
    return payload


def login(username: str) -> DemoClient:
    client = DemoClient()
    result = call("POST", "/v1/session", client, body={"username": username, "password": PASSWORD})
    client.csrf = result["csrf_token"]
    return client


def main() -> None:
    assert call("GET", "/health/ready")["status"] == "ready"
    admin, engineer, contractor, nova = [login(user) for user in
                                          ("atlas-admin", "atlas-engineer", "atlas-contractor", "nova-admin")]
    budget_before = call("GET", "/v1/inference-budget", admin)
    document = "/v1/host/projects/atlas-project/documents/atlas-roadmap"
    call("GET", document, contractor, expected=403)
    request = call("POST", "/v1/requests", admin,
                   {"text": "Give atlas-contractor read-only access to Project Atlas until Friday",
                    "kind": "access", "project_id": "atlas-project", "viewer_id": "atlas-contractor",
                    "expires_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()}, expected=201)
    handoff = call("POST", f"/v1/requests/{request['id']}/manual-handoff", engineer)
    assert handoff["ai_call"] is False
    proposal_id = handoff["proposal_id"]
    proposal = call("GET", f"/v1/proposals/{proposal_id}", admin)
    assert call("POST", f"/v1/proposals/{proposal_id}/preview", admin)["matches_saved_proposal"]
    approved = call("POST", f"/v1/proposals/{proposal_id}/approve", admin,
                    {"proposal_hash": proposal["proposal_hash"]})
    call("GET", document, contractor)
    call("GET", document, nova, expected=404)
    usage = call("GET", f"/v1/host-observations?variation_id={approved['variation_id']}", admin)
    assert len(usage) == 1 and usage[0]["basis"] == "variation" and usage[0]["allowed"]
    call("GET", f"/v1/host-observations?variation_id={approved['variation_id']}", nova, expected=404)
    call("POST", f"/v1/variations/{approved['variation_id']}/revoke", admin)
    call("GET", document, contractor, expected=403)

    feature = call("POST", "/v1/requests", engineer,
                   {"text": "Add PDF export for Project Atlas", "kind": "feature",
                    "project_id": "atlas-project"}, expected=201)
    call("POST", f"/v1/requests/{feature['id']}/manual-handoff", engineer)
    items = call("GET", "/v1/engineering", engineer)
    item_id = next(item["id"] for item in items if item["request_id"] == feature["id"])
    patch = call("POST", f"/v1/engineering/{item_id}/manual-patch", engineer,
                 {"patch": fixture_patch()})
    checked = call("POST", f"/v1/engineering/{item_id}/verify", engineer)
    assert is_external_pass(checked) and checked["patch_hash"] == patch["patch_hash"]
    decision = call("POST", f"/v1/engineering/{item_id}/decide", engineer,
                    {"decision": "accept_for_manual_release", "patch_hash": patch["patch_hash"]})
    assert decision["release_state"] == "not_deployed"
    artifact = call("GET", f"/v1/engineering/{item_id}/artifact", engineer)
    assert artifact["patch_hash"] == patch["patch_hash"] and "+++ b/sample_app/report.py" in artifact["diff"]
    access_proof = call("GET", f"/v1/requests/{request['id']}/proof", admin)
    engineering_proof = call("GET", f"/v1/requests/{feature['id']}/proof", engineer)
    assert verify_envelope(access_proof) and verify_envelope(engineering_proof)
    assert access_proof["payload"]["observations"][0]["variation_id"] == approved["variation_id"]
    assert engineering_proof["payload"]["engineering"][0]["human_decision"] == "accept_for_manual_release"
    signal = next(row for row in call("GET", "/v1/convergence", admin) if row["need_key"] == "temporary-project-view")
    assert signal["observed_granted_reads"] >= 1 and signal["affected_tenant_count"] is None
    budget_after = call("GET", "/v1/inference-budget", admin)
    assert budget_before["reserved_calls"] == budget_after["reserved_calls"]
    for identity in (admin, engineer, contractor, nova):
        call("POST", "/v1/session/logout", identity)
    print(json.dumps({"access": "enforced_then_revoked", "nova": "isolated",
                      "engineering": "checked_not_deployed", "runner": checked["runner"],
                      "oracle_version": checked["oracle_version"], "checks_completed": checked["checks_completed"],
                      "observed_granted_reads_for_variation": len(usage), "proof_digests": "verified",
                      "access_request_id": request["id"], "engineering_request_id": feature["id"],
                      "reserved_calls_before": budget_before["reserved_calls"],
                      "reserved_calls_after": budget_after["reserved_calls"], "ai_calls": 0}))


if __name__ == "__main__":
    main()
