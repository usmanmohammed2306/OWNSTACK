from copy import deepcopy
from conftest import login
from test_api import create_and_propose
from ownstack.proof import verify_envelope


def test_proof_binds_exact_approval_observation_and_source_without_credentials(client, fixture_db):
    admin, request_id, proposal_id, proposal_hash = create_and_propose(client, fixture_db)
    approved = client.post(f"/v1/proposals/{proposal_id}/approve",
                           headers={**admin, "Idempotency-Key": "proof-approval"}, json={"proposal_hash": proposal_hash})
    assert approved.status_code == 200
    contractor = login(client, "atlas-contractor")
    assert client.get("/v1/host/projects/atlas-project/documents/atlas-doc", headers=contractor).status_code == 200
    result = client.get(f"/v1/requests/{request_id}/proof", headers=admin)
    assert result.status_code == 200, result.text
    assert result.headers["content-disposition"].startswith("attachment;")
    envelope = result.json()
    assert verify_envelope(envelope)
    proof = envelope["payload"]
    assert proof["approvals"][0]["proposal_hash"] == proposal_hash
    assert proof["observations"][0]["variation_id"] == approved.json()["variation_id"]
    assert proof["attempts"][0]["model_id"] == "fixture"
    assert "src/ownstack/policy.py" in proof["source_hashes_at_export"]
    assert proof["contracts"][0]["version"] == 1
    for forbidden in ("password_hash", "csrf_hash", "token_hash", "NEBIUS_API_KEY", "atlas secret", "nova secret"):
        assert forbidden not in result.text
    changed = deepcopy(envelope)
    changed["payload"]["observations"][0]["allowed"] = False
    assert not verify_envelope(changed)
    assert not verify_envelope({})


def test_proof_access_never_crosses_tenant_or_role(client, fixture_db):
    admin, request_id, _, _ = create_and_propose(client, fixture_db)
    url = f"/v1/requests/{request_id}/proof"
    client.cookies.clear()
    assert client.get(url).status_code == 401
    assert client.get(url, headers=login(client, "nova-admin")).status_code == 404
    assert client.get(url, headers=login(client, "atlas-contractor")).status_code == 403
    assert client.get(url, headers=login(client, "platform-owner")).status_code == 403
    assert client.get(url, headers=login(client, "atlas-engineer")).status_code == 200
