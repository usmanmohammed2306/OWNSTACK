import time
import json
from sqlalchemy import text
from ownstack.api import SCHEMA_REVISION
from ownstack.service import mark_pulse
from ownstack.runner import current_provenance
from ownstack.candidate_sandbox import POLICY_ID


def test_unmigrated_readiness_is_503_not_server_error(client):
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert client.get("/health/live").status_code == 200


def test_readiness_requires_worker_and_verifier_pulses(client, fixture_db, tmp_path, monkeypatch):
    monkeypatch.setenv("OWNSTACK_REQUIRE_BACKGROUND", "true")
    monkeypatch.setenv("OWNSTACK_VERIFIER_JOBS_DIR", str(tmp_path))
    with fixture_db() as db:
        db.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
        db.execute(text("INSERT INTO alembic_version VALUES (:revision)"), {"revision": SCHEMA_REVISION})
        db.commit()
    assert client.get("/health/ready").status_code == 503
    with fixture_db() as db:
        mark_pulse(db, "worker")
        db.commit()
    assert client.get("/health/ready").status_code == 503
    (tmp_path / "heartbeat").write_text(str(time.time()))
    assert client.get('/health/ready').status_code == 503
    (tmp_path/'sandbox-policy.json').write_text(json.dumps({'policy':POLICY_ID,
        'landlock_abi':3,'checked_at':time.time(),
        'execution_policy_hash':current_provenance()['execution_policy_hash']}))
    assert client.get("/health/ready").status_code == 200
    (tmp_path / "heartbeat").write_text(str(time.time() - 60))
    assert client.get("/health/ready").status_code == 503
