"""Profile boundaries and malformed upstream metadata, not source-fix claims."""
from dataclasses import replace
import io
import json
from pathlib import Path
import tarfile
import pytest
from ownstack.experiment_store import digest
from ownstack.repository_profiles import for_source
from ownstack.repository_executor import (
    RepositoryCase, apply_candidate, docker_command, execution_fingerprint,
    extract_archive, parse_junit,
)


@pytest.mark.parametrize("repo,version,prefix", [
    ("pytest-dev/pytest", "7.2", "testing/"),
    ("sphinx-doc/sphinx", "3.1", "tests/"),
    ("pallets/jinja", "3.0", "tests/"),
])
def test_profile_load_checks_exact_oracle_and_does_not_return_gold(tmp_path, repo, version, prefix):
    profile = for_source(repo, version)
    row = {"instance_id": "test-1", "repo": repo, "version": version,
           "base_commit": "a" * 40, "problem_statement": "Observed problem", "test_patch": "oracle",
           "FAIL_TO_PASS": json.dumps([prefix + "test_a.py::test_bug"]),
           "PASS_TO_PASS": json.dumps([prefix + "test_a.py::test_regression"]),
           "patch": "reference-must-stay-private"}
    tests = {"fail_to_pass": json.loads(row["FAIL_TO_PASS"]),
             "pass_to_pass": json.loads(row["PASS_TO_PASS"]), "test_patch_sha256": digest("oracle")}
    public = {"id": row["instance_id"], "repo": repo, "base_commit": row["base_commit"],
              "problem_sha256": digest(row["problem_statement"]), "test_patch_sha256": digest("oracle"),
              "required_tests_sha256": digest(json.dumps(tests, sort_keys=True, separators=(",", ":"))),
              "source_url": "https://github.com/" + repo + "/pull/1",
              "source_split": "train"}  # Cannot retag the published test loader.
    catalog, evaluator = tmp_path / "catalog", tmp_path / "evaluator"
    catalog.write_text(json.dumps(public) + "\n")
    evaluator.write_text(json.dumps(row) + "\n")
    case = RepositoryCase.load(catalog, evaluator, "test-1")
    assert case.profile_id == profile.id and case.source_split == "test"
    assert "reference-must-stay-private" not in repr(case)
    row["PASS_TO_PASS"] = '["[100%]"]'
    tests["pass_to_pass"] = ["[100%]"]
    public["required_tests_sha256"] = digest(json.dumps(tests, sort_keys=True, separators=(",", ":")))
    catalog.write_text(json.dumps(public) + "\n"); evaluator.write_text(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="Unsafe required test"):
        RepositoryCase.load(catalog, evaluator, "test-1")


@pytest.mark.parametrize("repo,version", [("pytest-dev/pytest", "8.0"),
    ("sphinx-doc/sphinx", "7.2"), ("unknown/repo", "3.1")])
def test_other_versions_never_inherit_a_nearby_environment(repo, version):
    with pytest.raises(ValueError, match="No reviewed"):
        for_source(repo, version)


@pytest.mark.parametrize("repo,version,path", [
    ("pytest-dev/pytest", "7.2", "src/_pytest/python_api.py"),
    ("sphinx-doc/sphinx", "3.1", "sphinx/util/inspect.py"),
    ("pallets/jinja", "3.0", "src/jinja2/nativetypes.py"),
])
def test_source_edit_and_junit_namespace_are_specific_to_profile(tmp_path, repo, version, path):
    profile = for_source(repo, version)
    module = tmp_path / path; module.parent.mkdir(parents=True); module.write_text("answer = 1\n")
    apply_candidate(tmp_path, {"edits": [{"path": path, "old": "answer = 1", "new": "answer = 2"}]}, profile.id)
    assert module.read_text() == "answer = 2\n"
    test_file = profile.test_prefix + "test_a.py"
    classname = test_file[:-3].replace("/", ".")
    raw = f'<testsuites><testcase file="{test_file}" classname="{classname}" name="test_bug"/></testsuites>'.encode()
    assert parse_junit(raw, profile.id) == {test_file + "::test_bug": "passed"}
    with pytest.raises(ValueError):
        parse_junit(raw.replace(classname.encode(), b"unrelated.namespace"), profile.id)


@pytest.mark.parametrize("repo,version,path", [
    ("pytest-dev/pytest", "7.2", "src/flask/api.py"),
    ("pytest-dev/pytest", "7.2", "src/_pytest/_version.py"),
    ("pytest-dev/pytest", "7.2", "testing/test_a.py"),
    ("sphinx-doc/sphinx", "3.1", "sphinx/testing/fixtures.py"),
    ("sphinx-doc/sphinx", "3.1", "tests/test_a.py"),
    ("pallets/jinja", "3.0", "src/flask/example.py"),
    ("pallets/jinja", "3.0", "tests/test_nativetypes.py"),
])
def test_cross_profile_test_and_trusted_bootstrap_edits_rejected(tmp_path, repo, version, path):
    module = tmp_path / path; module.parent.mkdir(parents=True); module.write_text("old")
    with pytest.raises(ValueError):
        apply_candidate(tmp_path, {"edits": [{"path": path, "old": "old", "new": "new"}]}, for_source(repo, version).id)
    assert module.read_text() == "old"


def test_pytest_bootstrap_is_recorded_and_cannot_overwrite_upstream(tmp_path):
    profile = for_source("pytest-dev/pytest", "7.2")
    case = RepositoryCase("one", profile.repo, "a" * 40, "b" * 64, "", (), (), "c" * 64,
                          "https://github.com/pytest-dev/pytest/pull/1", profile.id)
    archive = tmp_path / "source.tar.gz"
    def build(extra=False):
        with tarfile.open(archive, "w:gz") as file:
            for name in [profile.marker] + ([profile.generated_files[0][0]] if extra else []):
                raw = b"# original\n"
                member = tarfile.TarInfo("pytest-" + case.base_commit + "/" + name)
                member.size = len(raw); file.addfile(member, io.BytesIO(raw))
    build()
    result = extract_archive(archive, tmp_path / "source", case)
    name, content = profile.generated_files[0]
    assert result["profile_generated_files"] == {name: digest(content)}
    assert (tmp_path / "source" / name).read_text() == content
    with pytest.raises(ValueError, match="differs"):
        extract_archive(archive, tmp_path / "wrong-repo", replace(case, repo="pallets/flask"))
    build(extra=True)
    with pytest.raises(ValueError, match="overwrite upstream"):
        extract_archive(archive, tmp_path / "conflict", case)


def test_pytest_fixed_plugin_and_kernel_limits_remain_explicit(tmp_path):
    profile = for_source("pytest-dev/pytest", "7.2")
    command = docker_command("ownstack-repo-probe", "sha256:" + "a" * 64, tmp_path,
                             ["testing/python/approx.py"], profile.id)
    assert command[-3:] == ["-p", "pytester", "testing/python/approx.py"]
    assert command[command.index("--network") + 1] == "none"
    assert command[command.index("--user") + 1] == "65534:65534"
    assert "--read-only" in command and "--pull" in command
    assert "PYTHONPATH=/repo/src" in command
    assert execution_fingerprint(profile.id) != execution_fingerprint(for_source("pallets/flask", "2.0").id)


def test_loaded_runner_refuses_changed_disk_policy(monkeypatch):
    import ownstack.repository_executor as executor
    monkeypatch.setattr(executor, '_read_execution_fingerprint', lambda _: '0' * 64)
    with pytest.raises(ValueError, match='restart'):
        executor.execution_fingerprint(for_source('pytest-dev/pytest', '7.2').id)


@pytest.mark.parametrize('invalid', [None, 'one_parameter_only', 'unrelated_test', 'bad_source_hash'])
def test_explicit_train_oracle_expansion_never_drops_regressions(tmp_path, monkeypatch, invalid):
    import ownstack.repository_executor as executor
    # Synthetic metadata tests the correction boundary. No real source fix or
    # human data-review claim follows from this fake evaluator.
    old = 'tests/test_demo.py::test_flags[x'
    expanded = [old + '-a]', old + '-b]']
    failed = ['tests/test_demo.py::test_bug']
    row = {'instance_id': 'pallets__jinja-1537', 'repo': 'pallets/jinja', 'version': '3.0',
           'base_commit': 'a' * 40, 'problem_statement': 'Synthetic bounded problem',
           'test_patch': 'synthetic-oracle', 'FAIL_TO_PASS': json.dumps(failed),
           'PASS_TO_PASS': json.dumps([old]), 'patch': 'gold-not-returned'}
    def checksum(retained):
        return digest(json.dumps({'fail_to_pass': failed, 'pass_to_pass': retained,
            'test_patch_sha256': digest(row['test_patch'])}, sort_keys=True, separators=(',', ':')))
    public = {'id': row['instance_id'], 'repo': row['repo'], 'base_commit': row['base_commit'],
              'problem_sha256': digest(row['problem_statement']), 'test_patch_sha256': digest(row['test_patch']),
              'source_required_tests_sha256': checksum([old]), 'required_tests_sha256': checksum(expanded),
              'test_id_expansions': [{'source': old, 'required': expanded}],
              'source_url': 'https://github.com/pallets/jinja/pull/1537'}
    if invalid == 'one_parameter_only': public['test_id_expansions'][0]['required'] = expanded[:1]
    if invalid == 'unrelated_test': public['test_id_expansions'][0]['required'] = [expanded[0], 'tests/unrelated.py::x]']
    if invalid == 'bad_source_hash': public['source_required_tests_sha256'] = '0' * 64
    monkeypatch.setattr(executor, 'supplemental_cases', lambda: {row['instance_id']: public})
    catalog = tmp_path / 'catalog'; catalog.write_text('')
    evaluator = tmp_path / 'evaluator'; evaluator.write_text(json.dumps(row) + '\n')
    if invalid:
        with pytest.raises(ValueError): RepositoryCase.load(catalog, evaluator, row['instance_id'])
    else:
        case = RepositoryCase.load(catalog, evaluator, row['instance_id'])
        assert case.fail_to_pass == tuple(failed) and case.pass_to_pass == tuple(expanded)
        assert case.source_split == 'train' and case.problem_text == row['problem_statement']
        assert 'gold-not-returned' not in repr(case)
