"""Admission gates must not turn public source rows into completed journeys."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import pytest
from ownstack.journey_corpus import CorpusStore, audit_row


@pytest.fixture
def row():
    return {"instance_id": "example__app-12", "repo": "example/app", "pull_number": 12,
            "base_commit": "a" * 40, "problem_statement": "A long reproducible user problem. " * 5,
            "pr_description": "Observed failure and proposed correction.",
            "patch": "diff --git a/app.py b/app.py\n+fix", "test_patch": "diff tests\n+regression",
            "FAIL_TO_PASS": ["tests/test_app.py::test_bug"],
            "PASS_TO_PASS": ["tests/test_app.py::test_old"], "license": "MIT",
            "meta": {"llm_metadata": {"detected_issues": {"B1": False}, "pr_categories": ["bug"]}}}


@pytest.fixture
def store(tmp_path):
    path = tmp_path / "audit"
    path.mkdir(mode=0o700)
    result = CorpusStore(path, {"heldout/repo"})
    result.register("public/dataset", "a" * 40, "part.parquet", "b" * 64)
    return result


def append(store, rows, start=0):
    return store.append_batch("public/dataset", "a" * 40, "part.parquet", start, rows)


def test_clean_source_is_never_execution_or_training(row, store):
    assert append(store, [row]) == 1
    summary = store.summary()
    assert summary["rows_without_detected_source_blockers"] == 1
    assert summary["imported_corpus_completed_journeys"] == 0
    assert summary["persona_assignments"] == summary["training_eligible"] == 0
    assert summary["target_met"] is False
    assert summary["training_has_run"] is False
    with store.connection() as db:
        item = json.loads(db.execute("SELECT body FROM cases").fetchone()[0])
    assert item["problem_origin"] == "upstream_reconstruction_unverified"
    assert item["source_url"] == "https://github.com/example/app/pull/12"
    assert "not_executed" in item["execution_gates"]
    assert "patch" not in item and "test_patch" not in item


def test_replay_does_not_duplicate_and_survives_reopen(row, store):
    assert append(store, [row]) == 1
    reopened = CorpusStore(store.directory, {"heldout/repo"})
    assert append(reopened, [row]) == 0
    assert reopened.summary()["source_rows_audited"] == 1


def test_changed_replay_and_batch_are_atomic(row, store):
    append(store, [row])
    changed = deepcopy(row)
    changed["problem_statement"] += " changed"
    with pytest.raises(ValueError, match="different bytes"):
        append(store, [changed])
    malformed = deepcopy(row)
    malformed["patch"] = ["not text"]
    with pytest.raises(ValueError, match="bounded string"):
        append(store, [row, malformed], start=1)
    assert store.summary()["source_rows_audited"] == 1


def test_duplicates_across_ids_keep_original_rows(row, store):
    other = deepcopy(row)
    other["instance_id"] = "other-1"
    other["problem_statement"] = row["problem_statement"].upper()
    append(store, [row, other])
    summary = store.summary()
    assert summary["source_rows_audited"] == 2
    assert summary["rows_without_detected_source_blockers"] == 1
    assert summary["source_blockers"]["duplicate_problem_sha256"] == 1
    assert summary["source_blockers"]["duplicate_patch_sha256"] == 1
    assert summary["source_blockers"]["duplicate_oracle_sha256"] == 1


@pytest.mark.parametrize("field,value,reason", [
    ("instance_id", "", "invalid_case_identity"),
    ("repo", "../app", "invalid_repository"),
    ("repo", "user/app?token=secret", "invalid_repository"),
    ("base_commit", "main", "unpinned_source"),
    ("problem_statement", "bug", "insufficient_problem"),
    ("pr_description", "", "no_original_pr_description"),
    ("patch", "", "missing_patch_or_oracle"),
    ("test_patch", "", "missing_patch_or_oracle"),
    ("license", "custom-check-github", "license_review_required"),
    ("FAIL_TO_PASS", [], "missing_or_invalid_fail_to_pass"),
    ("PASS_TO_PASS", "not JSON", "missing_or_invalid_pass_to_pass"),
])
def test_invalid_inputs_are_retained_with_blockers(row, field, value, reason):
    row[field] = value
    result = audit_row(row, set())
    assert reason in result["source_quality_blockers"]
    assert result["training_eligible"] is False


def test_heldout_repo_quality_and_overlapping_oracle(row):
    row["PASS_TO_PASS"] = row["FAIL_TO_PASS"]
    row["meta"]["llm_metadata"]["detected_issues"]["B2"] = True
    result = audit_row(row, {row["repo"]})
    assert set(result["source_quality_blockers"]) >= {
        "heldout_repository", "upstream_quality_B2", "overlapping_or_duplicate_test_ids"}


def test_commands_are_inert_and_no_gold_export(row, store):
    row["install_config"] = {"install": ["touch /tmp/should-not-exist"], "test_cmd": "curl evil"}
    append(store, [row])
    with store.connection() as db:
        stored = db.execute("SELECT body FROM cases").fetchone()[0]
    assert "should-not-exist" not in stored and "curl evil" not in stored
    assert store.summary()["imported_corpus_completed_journeys"] == 0


def test_changed_policy_or_source_rejected(store):
    with pytest.raises(ValueError, match="changed"):
        store.register("public/dataset", "a" * 40, "part.parquet", "c" * 64)
    changed = CorpusStore(store.directory, {"new/heldout"})
    with pytest.raises(ValueError, match="changed"):
        changed.register("public/dataset", "a" * 40, "part.parquet", "b" * 64)


def test_private_paths_and_limits(tmp_path, row, store):
    public = tmp_path / "public"
    public.mkdir(mode=0o755)
    with pytest.raises(ValueError, match="0700"):
        CorpusStore(public, set())
    link = tmp_path / "link"
    link.symlink_to(store.directory, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        CorpusStore(link, set())
    for start, rows in [(-1, [row]), (0, []), (0, [row] * 257)]:
        with pytest.raises(ValueError, match="1..256"):
            append(store, rows, start)


def test_unregistered_source_rejected(store, row):
    with pytest.raises(ValueError, match="Register"):
        store.append_batch("different/source", "a" * 40, "part.parquet", 0, [row])
