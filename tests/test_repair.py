"""Synthetic providers only. No remote inference and no production budget reset."""
from datetime import timedelta
import pytest
from sqlalchemy import select, func
from ownstack.config import Settings
from ownstack.models import ChangeRequest, EngineeringItem, Evidence, InferenceBudget
from ownstack.patch_agent import fixture_patch
from ownstack.pdf_oracle import CASE_IDS
from ownstack.policy import Principal
from ownstack.repair import (adopt_candidate, claim_work, finish_checks, reap_repairs,
    run_repair_one, save_candidate, serialize_run, start_repair, stop_repair)
from ownstack.repair_models import RepairRun, RepairAttempt
from ownstack.runner import current_provenance, patch_hash
from ownstack.service import utcnow
from conftest import login

ENGINEER = Principal("atlas-engineer", "atlas", "engineer")


def failed_item(factory):
    broken = fixture_patch()
    broken["edits"][0]["new"] = "def export_pdf(project_name, rows):\n    return b'not pdf'\n"
    with factory() as db:
        db.add(ChangeRequest(id="repair-request", tenant_id="atlas", requester_id="atlas-engineer",
            text="Add PDF export for Atlas", kind="feature", status="engineering", revision=1))
        db.flush()
        item = EngineeringItem(id="repair-item", tenant_id="atlas", request_id="repair-request",
            patch=broken, patch_hash=patch_hash(broken), status="checks_failed")
        db.add(item)
        db.add(Evidence(id="repair-failure", tenant_id="atlas", request_id="repair-request",
            kind="patch_checks", subject_hash=item.patch_hash,
            result={"passed": False, "stderr": "Synthetic initial PDF failure"},
            limitation="Synthetic unit fixture, not a live candidate."))
        db.commit()
        return item.patch_hash


def start(factory, *, max_attempts=2):
    expected_hash = failed_item(factory)
    with factory() as db:
        run = start_repair(db, "repair-item", ENGINEER, "repair-key", expected_hash, max_attempts)
        db.commit()
        return run.id


def proposal(_text, _settings, *, repair_context):
    assert repair_context["candidate"] and "feedback" in repair_context
    return fixture_patch(), "fixture-not-live", {"live": False, "latency_ms": 0}


def oracle(patch, passed=True):
    return {"passed": passed, "patch_hash": patch_hash(patch), "oracle_version": "pdf-external-v1",
            "checks_completed": 7, "checks_expected": 7,
            "cases": [{"id": case, "passed": passed, "pdf_sha256": "0" * 64} for case in sorted(CASE_IDS)], "runner": "injected-synthetic-oracle",
            "stderr": "" if passed else "Synthetic PDF mismatch", **current_provenance()}


def test_duplicate_start_and_refresh_read_saved_state(client, fixture_db):
    expected_hash = failed_item(fixture_db)
    headers = {**login(client, "atlas-engineer"), "Idempotency-Key": "repair-key"}
    url = "/v1/engineering/repair-item/repairs"
    first = client.post(url, headers=headers, json={"patch_hash": expected_hash})
    assert first.status_code == 200, first.text
    duplicate = client.post(url, headers=headers, json={"patch_hash": expected_hash})
    assert duplicate.json() == first.json()
    run_repair_one(fixture_db, propose=proposal)
    saved = client.post(url, headers=headers, json={"patch_hash": expected_hash})
    assert saved.json()["attempts"][0]["state"] == "candidate_ready"
    assert client.get("/v1/repairs/" + first.json()["id"], headers=headers).json() == saved.json()
    conflict = client.post(url, headers=headers, json={"patch_hash": expected_hash, "max_attempts": 1})
    assert conflict.status_code == 409
    with fixture_db() as db:
        assert db.scalar(select(func.count(RepairRun.id))) == 1
        assert db.scalar(select(func.count(RepairAttempt.id))) == 1
        assert db.get(InferenceBudget, "global").reserved_calls == 0


def test_different_key_returns_existing_run(fixture_db):
    run_id = start(fixture_db)
    with fixture_db() as db:
        item = db.get(EngineeringItem, "repair-item")
        duplicate = start_repair(db, item.id, ENGINEER, "other-key", item.patch_hash)
        assert duplicate.id == run_id
        db.commit()


def test_restart_between_generation_and_verification_and_explicit_adoption(fixture_db):
    run_id = start(fixture_db)
    run_repair_one(fixture_db, propose=proposal)
    # New sessions stand in for independently restarted workers. Candidate saved.
    calls = []
    def unexpected(*args, **kwargs):
        calls.append(1)
        raise AssertionError("A saved candidate must not be regenerated")
    run_repair_one(fixture_db, propose=unexpected, verify=oracle)
    assert calls == []
    with fixture_db() as db:
        run = db.get(RepairRun, run_id)
        item = db.get(EngineeringItem, "repair-item")
        assert run.state == "awaiting_review" and item.patch_hash == run.original_patch_hash
        assert item.human_decision is None
        adopt_candidate(db, run_id, patch_hash(fixture_patch()))
        db.commit()
        assert item.status == "checks_passed" and item.human_decision is None
        assert db.scalar(select(Evidence).where(Evidence.kind == "superseded_patch")).subject_hash == run.original_patch_hash
        assert db.get(Evidence, "repair-failure") is not None
        assert serialize_run(db, run)["release_state"] == "not_deployed"


def test_two_failed_candidates_end_in_manual_handoff(fixture_db):
    run_id = start(fixture_db)
    for _ in range(2):
        assert run_repair_one(fixture_db, propose=proposal)
        assert run_repair_one(fixture_db, verify=lambda patch: oracle(patch, False))
    assert run_repair_one(fixture_db, propose=proposal) is False
    with fixture_db() as db:
        run = db.get(RepairRun, run_id)
        attempts = db.scalars(select(RepairAttempt).where(RepairAttempt.run_id == run_id)).all()
        assert run.state == "manual_handoff" and len(attempts) == 2
        assert all(a.candidate and a.checks and a.state == "failed" for a in attempts)
        assert db.get(EngineeringItem, "repair-item").patch_hash == run.original_patch_hash


def test_first_failure_then_second_pass_preserves_both(fixture_db):
    run_id = start(fixture_db)
    run_repair_one(fixture_db, propose=proposal)
    run_repair_one(fixture_db, verify=lambda patch: oracle(patch, False))
    run_repair_one(fixture_db, propose=proposal)
    run_repair_one(fixture_db, verify=oracle)
    with fixture_db() as db:
        state = serialize_run(db, db.get(RepairRun, run_id))
        assert state["state"] == "awaiting_review"
        assert [a["state"] for a in state["attempts"]] == ["failed", "passed"]


@pytest.mark.parametrize("phase", ["generating", "verifying"])
def test_timeout_then_second_attempt_discards_late_first(fixture_db, phase):
    run_id = start(fixture_db)
    if phase == "verifying":
        run_repair_one(fixture_db, propose=proposal)
    with fixture_db() as db:
        work = claim_work(db, Settings())
        attempt = db.get(RepairAttempt, work["attempt_id"])
        assert attempt.state == phase
        attempt.deadline_at = utcnow() - timedelta(seconds=1)
        db.commit()
    with fixture_db() as db:
        assert reap_repairs(db) == 1
        db.commit()
    with fixture_db() as db:
        late = (save_candidate(db, work["attempt_id"], fixture_patch(), "fixture-not-live", {}, Settings())
                if phase == "generating" else finish_checks(db, work["attempt_id"], oracle(fixture_patch())))
        assert late is False
        db.commit()
        run = db.get(RepairRun, run_id)
        assert run.current_attempt_id != work["attempt_id"]
        assert db.get(RepairAttempt, work["attempt_id"]).state == "timed_out"


def test_deadline_rejected_even_without_reaper(fixture_db):
    start(fixture_db)
    with fixture_db() as db:
        work = claim_work(db, Settings())
        db.get(RepairAttempt, work["attempt_id"]).deadline_at = utcnow() - timedelta(seconds=1)
        db.commit()
    with fixture_db() as db:
        assert not save_candidate(db, work["attempt_id"], fixture_patch(), "fixture-not-live", {}, Settings())
        db.commit()
        assert db.get(RepairAttempt, work["attempt_id"]).candidate is None


@pytest.mark.parametrize("change", ["takeover", "revision", "patch", "source"])
def test_human_or_version_change_discards_inflight_candidate(fixture_db, monkeypatch, change):
    run_id = start(fixture_db)
    with fixture_db() as db:
        work = claim_work(db, Settings())
        db.commit()
    with fixture_db() as db:
        item = db.get(EngineeringItem, "repair-item")
        if change == "takeover":
            item.human_decision, item.operation_id = "take_over", None
        elif change == "revision":
            db.get(ChangeRequest, "repair-request").revision += 1
        elif change == "patch":
            item.patch, item.patch_hash = fixture_patch(), patch_hash(fixture_patch())
        else:
            monkeypatch.setattr("ownstack.repair.current_provenance", lambda: {"source_hash": "changed"})
        db.commit()
    with fixture_db() as db:
        assert not save_candidate(db, work["attempt_id"], fixture_patch(), "fixture-not-live", {}, Settings())
        db.commit()
        assert db.get(RepairRun, run_id).state == "taken_over"
        assert db.get(RepairAttempt, work["attempt_id"]).candidate is None


def test_ai_off_blocks_new_start_but_returns_saved_run(client, fixture_db, monkeypatch):
    run_id = start(fixture_db)
    monkeypatch.setenv("OWNSTACK_AI_MODE", "off")
    headers = {**login(client, "atlas-engineer"), "Idempotency-Key": "repair-key"}
    with fixture_db() as db:
        expected = db.get(RepairRun, run_id).original_patch_hash
    assert client.post("/v1/engineering/repair-item/repairs", headers=headers,
                       json={"patch_hash": expected}).json()["id"] == run_id
    called = []
    run_repair_one(fixture_db, propose=lambda *a, **kw: called.append(1))
    assert called == []
    with fixture_db() as db:
        assert db.get(RepairRun, run_id).error_code == "AI_OFF"
    assert client.post("/v1/engineering/repair-item/repairs",
        headers={**headers, "Idempotency-Key": "new"}, json={"patch_hash": expected}).status_code == 409


def test_worker_cannot_turn_fixture_into_live_call(fixture_db):
    run_id = start(fixture_db)
    settings = Settings(ai_mode="nebius", nebius_key="synthetic-not-used", nebius_model="nvidia/test-Nemotron", max_live_calls=10)
    run_repair_one(fixture_db, settings, propose=lambda *a, **kw: pytest.fail("No inference permitted"))
    with fixture_db() as db:
        assert db.get(RepairRun, run_id).error_code == "MODEL_CONFIGURATION_CHANGED"
        assert db.get(InferenceBudget, "global").reserved_calls == 0


def test_exhausted_budget_blocks_dispatch_without_new_reservation(fixture_db):
    expected = failed_item(fixture_db)
    settings = Settings(ai_mode="nebius", nebius_key="synthetic-not-used", nebius_model="nvidia/test-Nemotron", max_live_calls=10)
    with fixture_db() as db:
        db.get(InferenceBudget, "global").reserved_calls = 10
        run = start_repair(db, "repair-item", ENGINEER, "capped", expected, settings=settings)
        run_id = run.id
        db.commit()
    run_repair_one(fixture_db, settings, propose=lambda *a, **kw: pytest.fail("No inference permitted"))
    with fixture_db() as db:
        assert db.get(RepairRun, run_id).error_code == "BUDGET_OR_CONFIGURATION_BLOCKED"
        assert db.get(InferenceBudget, "global").reserved_calls == 10


@pytest.mark.parametrize("mutation", ["exit_only", "hash", "source", "incomplete", "oracle"])
def test_untrusted_or_incomplete_verifier_cannot_pass(fixture_db, mutation):
    run_id = start(fixture_db)
    run_repair_one(fixture_db, propose=proposal)
    def bad(patch):
        result = oracle(patch)
        if mutation == "exit_only":
            return {"passed": True, "exit_code": 0, "patch_hash": patch_hash(patch)}
        result[{"hash": "patch_hash", "source": "source_hash", "incomplete": "checks_completed", "oracle": "oracle_version"}[mutation]] = 0
        return result
    run_repair_one(fixture_db, verify=bad)
    with fixture_db() as db:
        assert db.get(RepairRun, run_id).state == "manual_handoff"
        assert db.get(EngineeringItem, "repair-item").status == "checks_failed"


def test_verifier_exception_stops_without_spending_second_attempt(fixture_db):
    run_id = start(fixture_db)
    run_repair_one(fixture_db, propose=proposal)
    def unavailable(_patch):
        raise RuntimeError("Synthetic infrastructure failure")
    run_repair_one(fixture_db, verify=unavailable)
    with fixture_db() as db:
        assert db.get(RepairRun, run_id).error_code == "VERIFIER_ERROR"
        assert db.scalar(select(func.count(RepairAttempt.id))) == 1


def test_takeover_route_restores_manual_patch_and_is_tenant_scoped(client, fixture_db):
    run_id = start(fixture_db)
    engineer = login(client, "atlas-engineer")
    admin = login(client, "atlas-admin")
    nova = login(client, "nova-admin")
    assert client.get(f"/v1/repairs/{run_id}", headers=nova).status_code == 404
    assert client.post(f"/v1/repairs/{run_id}/take-over", headers=admin).status_code == 403
    assert client.post(f"/v1/repairs/{run_id}/take-over", headers=engineer).json()["state"] == "taken_over"
    response = client.post("/v1/engineering/repair-item/manual-patch", headers=engineer, json={"patch": fixture_patch()})
    assert response.status_code == 200


def test_repair_requires_failed_evidence_and_exact_hash(client, fixture_db):
    failed_item(fixture_db)
    headers = {**login(client, "atlas-engineer"), "Idempotency-Key": "bad"}
    assert client.post("/v1/engineering/repair-item/repairs", headers=headers,
        json={"patch_hash": "0" * 64}).status_code == 409
    with fixture_db() as db:
        expected = db.get(EngineeringItem, "repair-item").patch_hash
        db.delete(db.get(Evidence, "repair-failure"))
        db.commit()
    assert client.post("/v1/engineering/repair-item/repairs", headers=headers,
        json={"patch_hash": expected}).status_code == 409


def test_duplicate_result_does_not_overwrite_saved_candidate(fixture_db):
    start(fixture_db)
    with fixture_db() as db:
        work = claim_work(db, Settings())
        db.commit()
    with fixture_db() as db:
        assert save_candidate(db, work["attempt_id"], fixture_patch(), "fixture-not-live", {}, Settings())
        db.commit()
    with fixture_db() as db:
        assert not save_candidate(db, work["attempt_id"], {"edits": []}, "fixture-not-live", {}, Settings())
        db.commit()
        assert db.get(RepairAttempt, work["attempt_id"]).candidate == fixture_patch()


def test_every_dispatched_live_mode_attempt_reserves_even_after_failure(fixture_db):
    """Injected provider uses no network. This tests reservation semantics only."""
    expected = failed_item(fixture_db)
    settings = Settings(ai_mode="nebius", nebius_key="synthetic-not-used", nebius_model="nvidia/test-Nemotron", max_live_calls=10)
    with fixture_db() as db:
        run = start_repair(db, "repair-item", ENGINEER, "bounded-budget", expected, settings=settings)
        run_id = run.id
        db.commit()
    calls = []
    def fake_remote(*args, **kwargs):
        calls.append("synthetic-call")
        raise RuntimeError("Synthetic remote failure, not a real model call")
    run_repair_one(fixture_db, settings, propose=fake_remote)
    run_repair_one(fixture_db, settings, propose=fake_remote)
    run_repair_one(fixture_db, settings, propose=fake_remote)
    with fixture_db() as db:
        assert db.get(InferenceBudget, "global").reserved_calls == 2
        assert db.get(RepairRun, run_id).state == "manual_handoff"
        assert len(calls) == 2


def test_invalid_model_and_source_after_checks_never_adopt(fixture_db, monkeypatch):
    run_id = start(fixture_db)
    run_repair_one(fixture_db, propose=proposal)
    run_repair_one(fixture_db, verify=oracle)
    with fixture_db() as db:
        monkeypatch.setattr("ownstack.repair.current_provenance", lambda: {"source_hash": "new-build"})
        with pytest.raises(Exception) as error:
            adopt_candidate(db, run_id, patch_hash(fixture_patch()))
        assert error.value.status_code == 409
        assert db.get(EngineeringItem, "repair-item").patch_hash == db.get(RepairRun, run_id).original_patch_hash


def test_candidate_syntax_failure_is_repairable_without_claiming_checks_completed(fixture_db):
    run_id = start(fixture_db)
    run_repair_one(fixture_db, propose=proposal)
    def syntax_failure(patch):
        result = oracle(patch, False)
        return {**result, "checks_completed": 0, "cases": [], "stderr": "Synthetic SyntaxError"}
    run_repair_one(fixture_db, verify=syntax_failure)
    with fixture_db() as db:
        state = serialize_run(db, db.get(RepairRun, run_id))
        assert state["state"] == "running"
        assert [a["state"] for a in state["attempts"]] == ["failed", "queued"]
        assert state["attempts"][0]["checks"]["checks_completed"] == 0


def test_exact_patch_hash_required_for_human_adoption(client, fixture_db):
    run_id = start(fixture_db)
    run_repair_one(fixture_db, propose=proposal)
    run_repair_one(fixture_db, verify=oracle)
    engineer = login(client, "atlas-engineer")
    assert client.post(f"/v1/repairs/{run_id}/adopt", headers=engineer,
                       json={"patch_hash": "0" * 64}).status_code == 409
    accepted = client.post(f"/v1/repairs/{run_id}/adopt", headers=engineer,
                          json={"patch_hash": patch_hash(fixture_patch())})
    assert accepted.status_code == 200 and accepted.json()["release_state"] == "not_deployed"
    assert client.post(f"/v1/repairs/{run_id}/adopt", headers=engineer,
                       json={"patch_hash": patch_hash(fixture_patch())}).status_code == 409
    with fixture_db() as db:
        assert db.scalar(select(func.count(Evidence.id)).where(Evidence.kind == "superseded_patch")) == 1


def test_crashed_live_claim_is_not_dispatched_twice(fixture_db):
    expected = failed_item(fixture_db)
    settings = Settings(ai_mode="nebius", nebius_key="synthetic-not-used", nebius_model="nvidia/test-Nemotron", max_live_calls=10)
    with fixture_db() as db:
        run = start_repair(db, "repair-item", ENGINEER, "crash-budget", expected, settings=settings)
        db.commit()
    with fixture_db() as db:
        work = claim_work(db, settings)
        db.commit()
    with fixture_db() as db:
        assert claim_work(db, settings) is None
        assert db.get(InferenceBudget, "global").reserved_calls == 1
        db.get(RepairAttempt, work["attempt_id"]).deadline_at = utcnow() - timedelta(seconds=1)
        db.commit()
    with fixture_db() as db:
        assert reap_repairs(db) == 1
        second = claim_work(db, settings)
        db.commit()
        assert second["attempt_id"] != work["attempt_id"]
        assert db.get(InferenceBudget, "global").reserved_calls == 2


def test_worker_services_both_queues_under_sustained_interpretation(monkeypatch):
    from ownstack import worker
    seen = []
    monkeypatch.setattr(worker, "run_one", lambda: seen.append("interpret") or True)
    monkeypatch.setattr(worker, "run_repair_one", lambda: seen.append("repair") or False)
    assert worker.run_cycle()
    assert seen == ["interpret", "repair"]


def test_generator_change_fences_queued_work(fixture_db, monkeypatch):
    run_id = start(fixture_db)
    monkeypatch.setattr("ownstack.repair.generation_configuration", lambda: {"generator_hash": "changed"})
    calls = []
    run_repair_one(fixture_db, propose=lambda *args, **kw: calls.append(1))
    assert calls == []
    with fixture_db() as db:
        assert db.get(RepairRun, run_id).error_code == "MODEL_CONFIGURATION_CHANGED"


def test_model_timeout_is_specific_and_does_not_claim_remote_cancellation(fixture_db):
    import httpx
    run_id = start(fixture_db, max_attempts=1)
    def timeout(*args, **kwargs):
        raise httpx.ReadTimeout("Synthetic timeout")
    run_repair_one(fixture_db, propose=timeout)
    with fixture_db() as db:
        state = serialize_run(db, db.get(RepairRun, run_id))
        assert state["error_code"] == "MODEL_TIMEOUT"
        assert state["remote_cancellation_verified"] is False
