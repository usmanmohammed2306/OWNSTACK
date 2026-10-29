from ownstack import demo
from ownstack.models import InferenceBudget
from conftest import login


def test_demo_is_authenticated_historical_and_zero_inference(client, fixture_db, monkeypatch):
    monkeypatch.setenv("OWNSTACK_AI_MODE", "off")
    assert client.get("/v1/demo-evidence").status_code == 401
    for identity in ("atlas-admin", "nova-admin", "atlas-contractor", "platform-owner"):
        headers = login(client, identity)
        response = client.get("/v1/demo-evidence", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["historical"] and data["synthetic_tenants"]
        assert data["inference_calls_this_read"] == 0
        assert data["access"]["state"] == "accepted"
        assert data["access"]["nova"] == "observed_denied"
        assert data["access"]["latency_ms"] == 1357
        assert data["patch"]["passed"] is False
        assert data["patch"]["release_state"] == "not_deployed"
        assert "SyntaxError" in data["patch"]["stderr"]
        assert data["recovery"]["passed"] is True
        assert data["recovery"]["not_live_model_success"] is True
        assert data["recovery"]["ai_call"] is False
        assert data["comparison"]["baseline"]["correct"] == 1
        assert len(data["artifacts"]) == 5
        assert all(len(a["sha256"]) == 64 for a in data["artifacts"])
        assert "atlas secret" not in response.text
    with fixture_db() as db:
        assert db.get(InferenceBudget, "global").reserved_calls == 0


def test_missing_demo_evidence_does_not_fabricate_success(client, monkeypatch, tmp_path):
    headers = login(client, "atlas-admin")
    monkeypatch.setattr(demo, "EVIDENCE_DIR", tmp_path)
    assert client.get("/v1/demo-evidence", headers=headers).status_code == 503
    (tmp_path / demo.ARTIFACTS[0]).write_text("not json")
    assert client.get("/v1/demo-evidence", headers=headers).status_code == 503
