"""Offline experiment protocol regressions. Synthetic fixtures are not live results."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import shutil

import pytest

from ownstack.change_benchmark import (
    DATASET, ROOT, SOURCE_FILES, deterministic_parser, digest_bytes, digest_json,
    evaluate_rows, import_results, load_dataset, rate, read_json, request_message,
    run_offline, save_report, source_provenance, unsafe_proposal,
)


@pytest.fixture
def dataset():
    return load_dataset()


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n")
    return path


def rehash(path):
    manifest = json.loads((path / "manifest.json").read_text())
    for name in manifest["files"]:
        manifest["files"][name] = digest_bytes((path / name).read_bytes())
    write_json(path / "manifest.json", manifest)


def saved_model_artifact(dataset):
    provenance = source_provenance()
    rows = []
    for case in dataset["cases"]["held_out"]:
        proposal = deepcopy(case["expected"])
        messages = [{"role": "system", "content": (DATASET / "prompt.txt").read_text()},
                    {"role": "user", "content": request_message(case)}]
        rows.append({"case_id": case["id"], "raw_proposal": proposal,
                     "attempts": [{"number": 1, "raw_proposal": proposal, "messages": messages,
                                   "messages_sha256": digest_json(messages)}],
                     "latency_ms": None, "input_tokens": None, "output_tokens": None, "cost_usd": None})
    return {"schema_version": 1, "split": "held_out", "dataset_sha256": dataset["dataset_sha256"],
            "run_id": "synthetic-test-only-not-provider-evidence", "producer": {
                "kind": "model", "model_id": "test-synthetic", "prompt_sha256": dataset["prompt_sha256"],
                "source_files": provenance["files"], "code_sha256": provenance["code_sha256"],
                "settings": {"temperature": 0, "max_output_tokens": 512, "total_token_budget_per_case": 2048},
                "strategy": "one_shot", "max_attempts": 1}, "results": rows}


def test_frozen_balanced_family_disjoint_dataset(dataset):
    assert len(dataset["cases"]["dev"]) == 20
    assert len(dataset["cases"]["held_out"]) == 40
    assert not set(dataset["manifest"]["families"]["dev"]) & set(dataset["manifest"]["families"]["held_out"])
    for split, each in (("dev", 5), ("held_out", 10)):
        for route in ("configure", "engineering", "refuse", "clarify"):
            assert sum(case["expected"]["route"] == route for case in dataset["cases"][split]) == each


def test_hash_mismatch_rejected(tmp_path):
    copy = tmp_path / "dataset"
    shutil.copytree(DATASET, copy)
    with (copy / "dev.json").open("a") as stream:
        stream.write(" ")
    with pytest.raises(ValueError, match="DATASET_HASH_MISMATCH"):
        load_dataset(copy)


def test_family_leakage_rejected_even_after_rehash(tmp_path):
    copy = tmp_path / "dataset"
    shutil.copytree(DATASET, copy)
    held = json.loads((copy / "held_out.json").read_text())
    held[0]["family"] = "explicit_hour_template"
    write_json(copy / "held_out.json", held)
    manifest = json.loads((copy / "manifest.json").read_text())
    manifest["families"]["held_out"] = sorted({case["family"] for case in held})
    write_json(copy / "manifest.json", manifest)
    rehash(copy)
    with pytest.raises(ValueError, match="FAMILY_SPLIT_LEAKAGE"):
        load_dataset(copy)


def test_duplicate_request_rejected(tmp_path):
    copy = tmp_path / "dataset"
    shutil.copytree(DATASET, copy)
    cases = json.loads((copy / "held_out.json").read_text())
    cases[1]["text"] = cases[0]["text"].upper()
    write_json(copy / "held_out.json", cases)
    rehash(copy)
    with pytest.raises(ValueError, match="DUPLICATE_REQUEST_TEXT"):
        load_dataset(copy)


def test_parser_has_no_gold_label_input(dataset):
    case = dataset["cases"]["dev"][0]
    restricted = {key: case[key] for key in ("text", "kind", "context")}
    assert deterministic_parser(restricted) == case["expected"]
    changed_label = dict(case, expected={"route": "refuse"}, id="other", family="other")
    assert deterministic_parser(case) == deterministic_parser(changed_label)


@pytest.mark.parametrize("mutation,match", [
    (lambda data: data.update(dataset_sha256="0" * 64), "IMPORT_DATASET_HASH"),
    (lambda data: data["producer"].update(code_sha256="0" * 64), "IMPORT_CODE_PROVENANCE"),
    (lambda data: data["producer"].update(source_files={}), "IMPORT_CODE_PROVENANCE"),
    (lambda data: data["producer"].update(prompt_sha256="0" * 64), "IMPORT_PROMPT_HASH"),
    (lambda data: data["producer"].update(model_id=""), "IMPORT_MODEL_ID"),
    (lambda data: data["producer"].update(max_attempts=4), "IMPORT_ATTEMPT_BOUND"),
    (lambda data: data["producer"].update(settings={}), "IMPORT_MODEL_SETTINGS"),
    (lambda data: data["results"].pop(), "MISSING_OR_UNKNOWN_RESULTS"),
    (lambda data: data["results"].append(data["results"][0]), "DUPLICATE_RESULT"),
    (lambda data: data["results"][0].update(latency_ms=-1), "IMPORT_MEASUREMENT"),
    (lambda data: data["results"][0].update(input_tokens=True), "IMPORT_MEASUREMENT"),
    (lambda data: data["results"][0].update(input_tokens=2.5), "IMPORT_MEASUREMENT"),
    (lambda data: data["results"][0].update(input_tokens=2048, output_tokens=1), "IMPORT_EXCEEDED_TOKEN_BUDGET"),
    (lambda data: data["results"][0].update(attempts=[]), "IMPORT_ATTEMPTS"),
    (lambda data: data["results"][0]["attempts"][0].update(messages_sha256="0" * 64), "IMPORT_MESSAGES_PROVENANCE"),
])
def test_import_rejects_bad_provenance_or_missing_evidence(dataset, tmp_path, mutation, match):
    artifact = saved_model_artifact(dataset)
    mutation(artifact)
    path = write_json(tmp_path / "run.json", artifact)
    with pytest.raises(ValueError, match=match):
        import_results(path, dataset, "held_out", source_provenance())


def test_host_correction_never_earns_model_credit(dataset, tmp_path):
    artifact = saved_model_artifact(dataset)
    row = artifact["results"][0]
    row["host_proposal"] = row["raw_proposal"]
    row["raw_proposal"] = {"route": "configure", "scope": {**row["host_proposal"]["scope"], "tenant": "nova"}}
    row["attempts"][0]["raw_proposal"] = row["raw_proposal"]
    result = import_results(write_json(tmp_path / "run.json", artifact), dataset, "held_out", source_provenance())
    metrics = result["evaluation"]["metrics"]
    assert metrics["exact_correct"]["numerator"] == 39
    assert metrics["host_corrected_to_gold"]["numerator"] == 1
    assert metrics["unsafe_proposal"]["numerator"] == 1
    assert result["evaluation"]["failures"][0]["case_id"] == row["case_id"]


def test_bounded_repair_keeps_first_attempt_and_unsafe_history(dataset, tmp_path):
    artifact = saved_model_artifact(dataset)
    artifact["producer"].update(strategy="bounded_repair", max_attempts=3)
    row = artifact["results"][0]
    first = row["attempts"][0]
    first["raw_proposal"] = {"route": "configure"}
    repaired = {**first, "number": 2, "raw_proposal": row["raw_proposal"],
                "messages": first["messages"] + [{"role": "assistant", "content": '{"route":"configure"}'},
                                                 {"role": "user", "content": "Schema validation failed: scope required."}]}
    repaired["messages_sha256"] = digest_json(repaired["messages"])
    row["attempts"].append(repaired)
    result = import_results(write_json(tmp_path / "run.json", artifact), dataset, "held_out", source_provenance())["evaluation"]
    assert result["metrics"]["exact_correct"]["numerator"] == 40
    assert result["metrics"]["first_attempt_exact_correct"]["numerator"] == 39
    assert result["metrics"]["unsafe_proposal"]["numerator"] == 0
    assert result["metrics"]["any_attempt_unsafe"]["numerator"] == 1
    assert result["attempts"] == 41


def test_import_binds_actual_case_message(dataset, tmp_path):
    artifact = saved_model_artifact(dataset)
    attempt = artifact["results"][0]["attempts"][0]
    attempt["messages"][1]["content"] = "Other request"
    attempt["messages_sha256"] = digest_json(attempt["messages"])
    with pytest.raises(ValueError, match="IMPORT_CASE_MESSAGE"):
        import_results(write_json(tmp_path / "run.json", artifact), dataset, "held_out", source_provenance())


def test_unknown_cost_stays_unknown_and_zero_denominator_is_null(dataset):
    empty = evaluate_rows([], [])
    assert empty["metrics"]["exact_correct"]["value"] is None
    assert empty["per_class"]["configure"]["precision"]["wilson_95"] is None
    rows = [{"case_id": case["id"], "raw_proposal": case["expected"]} for case in dataset["cases"]["dev"]]
    scored = evaluate_rows(dataset["cases"]["dev"], rows)
    assert scored["measurements"]["cost_usd"]["complete_total"] is None
    assert scored["measurements"]["cost_usd"]["per_exact_completion"] is None
    rows[0]["cost_usd"] = 0.02
    partial = evaluate_rows(dataset["cases"]["dev"], rows)
    assert partial["measurements"]["cost_usd"]["observed_sum"] == .02
    assert partial["measurements"]["cost_usd"]["complete_total"] is None


def test_complete_cost_and_false_refusal(dataset):
    cases = dataset["cases"]["dev"][:5]
    rows = [{"case_id": case["id"], "raw_proposal": case["expected"], "cost_usd": .01, "latency_ms": 100} for case in cases]
    rows[0]["raw_proposal"] = {"route": "refuse", "reason_code": "unsupported_permission"}
    result = evaluate_rows(cases, rows)
    assert result["false_refusal"]["numerator"] == 1
    assert result["false_refusal"]["denominator"] == 5
    assert result["measurements"]["cost_usd"]["per_exact_completion"] == .05 / 4
    assert result["measurements"]["latency_ms"]["p95"] == 100


def test_wilson_not_zero_uncertainty_on_perfect_small_set():
    interval = rate(2, 2)["wilson_95"]
    assert 0 < interval[0] < .5
    assert interval[1] == pytest.approx(1)


def test_unknown_route_is_counted_as_invalid_not_dropped(dataset):
    case = dataset["cases"]["dev"][0]
    result = evaluate_rows([case], [{"case_id": case["id"], "raw_proposal": {"route": "deploy"}}])
    assert result["confusion"]["configure"]["invalid"] == 1
    assert result["metrics"]["abstained"]["numerator"] == 1
    assert len(result["failures"]) == 1


def test_malformed_proposal_fields_are_scored_not_executed_or_crashed(dataset):
    case = dataset["cases"]["dev"][5]
    result = evaluate_rows([case], [{"case_id": case["id"], "raw_proposal": {"route": "engineering", "release": {"run": "anything"}}}])
    assert result["metrics"]["unsafe_proposal"]["numerator"] == 1
    assert result["decisions"][0]["schema_errors"]
    result = evaluate_rows([case], [{"case_id": case["id"], "raw_proposal": {"route": []}}])
    assert result["confusion"]["engineering"]["invalid"] == 1


def test_unsafe_scope_and_shorter_grant_are_separate_from_exactness(dataset):
    gold = dataset["cases"]["dev"][1]["expected"]
    shorter = deepcopy(gold)
    shorter["scope"]["duration_hours"] -= 1
    assert not unsafe_proposal(shorter, gold)
    longer = deepcopy(gold)
    longer["scope"]["duration_hours"] += 1
    assert unsafe_proposal(longer, gold)


def test_json_duplicate_keys_and_nonfinite_rejected(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text('{"a":1,"a":2}')
    with pytest.raises(ValueError, match="DUPLICATE_JSON_KEY"):
        read_json(path)
    path.write_text('{"a":NaN}')
    with pytest.raises(ValueError, match="NONFINITE_JSON"):
        read_json(path)


def test_offline_entrypoint_uses_no_provider_db_or_network_imports():
    allowed = {"__future__", "collections", "datetime", "hashlib", "json", "math", "pathlib", "re", "typing", "argparse", "ownstack.change_benchmark"}
    for filename in SOURCE_FILES:
        tree = ast.parse((ROOT / filename).read_text())
        imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        assert set(imports) <= allowed


def test_report_preserves_failures_and_refuses_overwrite(tmp_path):
    report = run_offline()
    assert report["network_calls"] == 0
    assert report["live_nebius_evaluated"] is False
    assert report["imported_run"] is None
    assert report["baselines"]["kind_only"]["failures"]
    directory = tmp_path / "new-run"
    saved = save_report(report, directory)
    before = saved.read_bytes()
    with pytest.raises(FileExistsError):
        save_report(report, directory)
    assert saved.read_bytes() == before
