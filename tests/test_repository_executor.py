"""Fast executor policy checks; actual upstream executions have separate logs."""
from dataclasses import replace
import io
import json
from pathlib import Path
import tarfile

import pytest

import ownstack.repository_executor as executor
from ownstack.repository_executor import (
    RepositoryCase, apply_candidate, apply_test_patch, assess, docker_command,
    extract_archive, parse_junit, private_directory, safe_relative, tree_digest,
)


@pytest.fixture
def case():
    return RepositoryCase('pallets__flask-1', 'pallets/flask', 'a' * 40, 'b' * 64,
                          'test oracle', ('tests/test_a.py::test_bug',),
                          ('tests/test_a.py::test_retained',), 'c' * 64,
                          'https://github.com/pallets/flask/pull/1')


@pytest.mark.parametrize('name', ['../secret', '/etc/passwd', 'src/../../x',
                                  'src\\secret', '.git/config', 'tests/./x'])
def test_unsafe_paths_rejected(name):
    with pytest.raises(ValueError):
        safe_relative(name)


def test_bounded_source_edit_and_stale_anchor(tmp_path):
    module = tmp_path / 'src/flask/example.py'
    module.parent.mkdir(parents=True)
    module.write_text('answer = 1\n')
    patch = {'edits': [{'path': 'src/flask/example.py', 'old': 'answer = 1', 'new': 'answer = 2'}]}
    before = tree_digest(tmp_path)
    assert len(apply_candidate(tmp_path, patch)) == 64
    assert module.read_text() == 'answer = 2\n'
    assert tree_digest(tmp_path) != before
    with pytest.raises(ValueError, match='exact changed anchor'):
        apply_candidate(tmp_path, patch)


@pytest.mark.parametrize('name', ['tests/test_a.py', 'setup.py', 'src/flask/conftest.py',
                                  'src/flask/../../../outside.py'])
def test_candidate_cannot_edit_tests_installers_or_paths(tmp_path, name):
    with pytest.raises(ValueError):
        apply_candidate(tmp_path, {'edits': [{'path': name, 'old': 'old', 'new': 'new'}]})


@pytest.mark.parametrize('payload', [{'command': 'pytest'}, {'edits': []},
                                    {'edits': [], 'shell': True}])
def test_no_model_shell_or_empty_candidate(tmp_path, payload):
    with pytest.raises(ValueError):
        apply_candidate(tmp_path, payload)


def test_oracle_cannot_escape_tests(tmp_path):
    patch = 'diff --git a/src/flask/a.py b/src/flask/a.py\n--- a/src/flask/a.py\n+++ b/src/flask/a.py\n'
    with pytest.raises(ValueError):
        apply_test_patch(tmp_path, patch)


def test_oracle_applies_inside_parent_git_without_touching_parent(tmp_path):
    import subprocess
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    (tmp_path / 'tests').mkdir()
    outside = tmp_path / 'tests/example.py'; outside.write_text('outer = 1\n')
    tree = tmp_path / 'private/snapshot'; (tree / 'tests').mkdir(parents=True)
    target = tree / 'tests/example.py'; target.write_text('answer = 1\n')
    patch = ('diff --git a/tests/example.py b/tests/example.py\n'
             '--- a/tests/example.py\n+++ b/tests/example.py\n@@ -1 +1 @@\n-answer = 1\n+answer = 2\n')
    apply_test_patch(tree, patch)
    assert target.read_text() == 'answer = 2\n'
    assert outside.read_text() == 'outer = 1\n'


def test_skipped_oracle_is_rejected(tmp_path, monkeypatch):
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests/example.py').write_text('answer = 1\n')
    monkeypatch.setattr(executor.subprocess, 'run', lambda *a, **k: None)
    patch = 'diff --git a/tests/example.py b/tests/example.py\n--- a/tests/example.py\n+++ b/tests/example.py\n'
    with pytest.raises(ValueError, match='skipped'):
        apply_test_patch(tmp_path, patch)


def test_docker_policy_has_no_socket_keys_or_writable_host(tmp_path):
    argv = docker_command('ownstack-repo-test', 'sha256:' + 'a' * 64, tmp_path, ['tests/test_a.py'])
    assert argv[argv.index('--network') + 1] == 'none'
    assert argv[argv.index('--user') + 1] == '65534:65534'
    assert argv[argv.index('--pull') + 1] == 'never'
    assert '--read-only' in argv and '--cap-drop' in argv and '--pids-limit' in argv
    assert argv[argv.index('--mount') + 1].endswith('dst=/repo,readonly')
    assert '--privileged' not in argv and 'docker.sock' not in ' '.join(argv)
    assert not any('KEY' in v or 'TOKEN' in v for v in argv)
    with pytest.raises(ValueError):
        docker_command('ownstack-repo-test', 'mutable:latest', tmp_path, ['tests/test_a.py'])
    with pytest.raises(ValueError):
        docker_command('ownstack-repo-test', 'sha256:' + 'a'*64, tmp_path / 'bad,src=/etc', ['tests/test_a.py'])


@pytest.mark.parametrize('timeout', [0, -1, 181, True, float('nan')])
def test_wall_deadline_cannot_be_disabled(tmp_path, case, timeout):
    with pytest.raises(ValueError):
        executor.run_stage(tmp_path, case, tmp_path / 'unused', 'sha256:' + 'a'*64, timeout=timeout)


def test_private_nested_creation_and_symlink_ancestor(tmp_path, monkeypatch):
    monkeypatch.setattr(executor, 'ROOT', tmp_path)
    (tmp_path / '.private').mkdir()
    leaf = private_directory(tmp_path / '.private/campaign/nested')
    assert leaf.stat().st_mode & 0o077 == 0
    assert leaf.parent.stat().st_mode & 0o077 == 0
    link = tmp_path / '.private/alias'; link.symlink_to(leaf.parent)
    with pytest.raises(ValueError):
        private_directory(link / 'new')


def junit(body):
    return ('<testsuites><testsuite>' + body + '</testsuite></testsuites>').encode()


def test_junit_nested_classes_and_failures():
    raw = junit('<testcase file="tests/test_a.py" classname="tests.test_a.Suite" name="test_bug"><failure/></testcase>'
                '<testcase file="tests/test_a.py" classname="tests.test_a" name="test_retained"/>')
    assert parse_junit(raw) == {'tests/test_a.py::Suite::test_bug': 'failed',
                                'tests/test_a.py::test_retained': 'passed'}


@pytest.mark.parametrize('raw', [b'', b'<!DOCTYPE x><testsuites/>', b'<testsuites/>',
    junit('<testcase file="../private" classname="x" name="a"/>'),
    junit('<testcase file="tests/test_a.py" classname="wrong" name="a"/>'),
    junit('<testcase file="tests/test_a.py" classname="tests.test_a" name="a"/>' * 2)])
def test_missing_unsafe_or_duplicate_test_results_cannot_pass(raw):
    with pytest.raises(ValueError):
        parse_junit(raw)


def test_exit_zero_missing_tests_skip_and_infra_are_not_resolution(case):
    bug, retained = case.fail_to_pass[0], case.pass_to_pass[0]
    baseline = {'states': {bug: 'failed', retained: 'passed'}, 'exit_code': 1, 'failure': ''}
    patched = {'states': {bug: 'passed', retained: 'passed'}, 'exit_code': 0, 'failure': ''}
    assert assess(case, baseline, patched)['passed']
    # Optional skips are reported, never counted as a required-test pass.
    optional = dict(patched, states={**patched['states'], 'tests/test_a.py::optional': 'skipped'})
    assert assess(case, baseline, optional)['passed']
    for changed in [dict(patched, states={retained: 'passed'}),
                    dict(patched, states={bug: 'skipped', retained: 'passed'}),
                    dict(patched, exit_code=1), dict(patched, failure='deadline')]:
        assert not assess(case, baseline, changed)['passed']
    for broken in [dict(baseline, exit_code=2), dict(baseline, failure='collection failed'),
                   dict(baseline, states={bug: 'failed', retained: 'failed'}),
                   dict(baseline, states={**baseline['states'], 'tests/test_a.py::unrelated': 'failed'}), patched]:
        assert not assess(case, broken, patched)['passed']


def archive(path, case, members):
    with tarfile.open(path, 'w:gz') as file:
        for name, content, kind in members:
            member = tarfile.TarInfo('flask-' + case.base_commit + '/' + name)
            member.type = kind
            if kind == tarfile.REGTYPE:
                raw = content.encode(); member.size = len(raw)
                file.addfile(member, io.BytesIO(raw))
            else:
                member.linkname = '/etc/passwd'; file.addfile(member)


def test_archive_regular_files_only_and_exact_root(tmp_path, case):
    source = tmp_path / 'source.tar.gz'
    archive(source, case, [('src/flask/__init__.py', '# source', tarfile.REGTYPE)])
    report = extract_archive(source, tmp_path / 'good', case)
    assert report['files'] == 1
    with pytest.raises(FileExistsError):
        extract_archive(source, tmp_path / 'good', case)
    with pytest.raises(ValueError):
        extract_archive(source, tmp_path / 'wrong', replace(case, base_commit='d' * 40))
    archive(source, case, [('src/flask/__init__.py', '', tarfile.SYMTYPE)])
    with pytest.raises(ValueError):
        extract_archive(source, tmp_path / 'link', case)
    archive(source, case, [('../outside', 'secret', tarfile.REGTYPE)])
    with pytest.raises(ValueError):
        extract_archive(source, tmp_path / 'traversal', case)


def test_private_output_refuses_public_and_symlink(tmp_path, monkeypatch):
    monkeypatch.setattr(executor, 'ROOT', tmp_path)
    (tmp_path / '.private').mkdir(mode=0o700)
    with pytest.raises(ValueError):
        private_directory(tmp_path / 'public')
    target = private_directory(tmp_path / '.private/run')
    assert target.stat().st_mode & 0o077 == 0
    link = tmp_path / '.private/link'; link.symlink_to(target)
    with pytest.raises(ValueError):
        private_directory(link)


def test_invalid_driver_envelope_fails_and_cleans_owned_container(tmp_path, case, monkeypatch):
    tree = tmp_path / 'source'; tree.mkdir()
    (tree / 'public.py').write_text('pass')
    calls = []
    def fake_run(argv, **kwargs):
        calls.append(argv)
        return type('Done', (), {'returncode': 0})()
    monkeypatch.setattr(executor.subprocess, 'run', fake_run)
    monkeypatch.setattr(executor, 'capture', lambda *a, **k: {
        'stdout_bytes': b'', 'stderr': '', 'exit_code': 0, 'failure': ''})
    report = executor.run_stage(tree, case, tmp_path / 'stage', 'sha256:' + 'a' * 64)
    assert report['failure']
    assert report['states'] == {}
    assert calls[-1][1:3] == ['rm', '--force']


def test_test_hash_uses_catalog_unicode_format(tmp_path):
    from ownstack.experiment_store import digest
    failed = ['tests/test_a.py::test_bug']; retained = ['tests/test_a.py::test_☃']
    row = dict(instance_id='pallets__flask-1', repo='pallets/flask', version='2.0',
               base_commit='a' * 40, problem_statement='A published bug', test_patch='oracle',
               FAIL_TO_PASS=json.dumps(failed), PASS_TO_PASS=json.dumps(retained), patch='gold-do-not-return')
    oracle = {'fail_to_pass': failed, 'pass_to_pass': retained, 'test_patch_sha256': digest('oracle')}
    public = dict(id=row['instance_id'], repo=row['repo'], base_commit=row['base_commit'],
                  problem_sha256=digest(row['problem_statement']), test_patch_sha256=digest('oracle'),
                  required_tests_sha256=digest(json.dumps(oracle, sort_keys=True, separators=(',', ':'))),
                  source_url='https://github.com/pallets/flask/pull/1')
    catalog = tmp_path / 'catalog'; catalog.write_text(json.dumps(public) + '\n')
    evaluator = tmp_path / 'evaluator'; evaluator.write_text(json.dumps(row) + '\n')
    loaded = RepositoryCase.load(catalog, evaluator, row['instance_id'])
    assert loaded.pass_to_pass == tuple(retained)
    assert 'gold-do-not-return' not in repr(loaded)


def test_duplicate_start_returns_saved_progress_without_docker(tmp_path, monkeypatch, case):
    from ownstack.experiment_store import canonical, digest
    monkeypatch.setattr(executor, 'ROOT', tmp_path)
    (tmp_path / '.private').mkdir()
    output = private_directory(tmp_path / '.private/attempt')
    (output / 'claim.lock').write_text('{}')
    monkeypatch.setattr(executor.subprocess, 'run', lambda *a, **k: pytest.fail('Duplicate must not dispatch'))
    patch = {'edits': []}
    result = executor.execute(case, patch, output, tmp_path / '.private/cache')
    assert result['status'] == 'initializing' and result['saved_replay']
    expected = dict(case_id=case.id, scope='upstream_issue', source_group=case.repo, source_split='test',
                    source_url=case.source_url, case_sha256=case.problem_sha256,
                    candidate_sha256=digest(canonical(patch)), oracle_sha256=case.oracle_sha256,
                    candidate_origin='human', reference_answer_visible=False)
    identity = {**expected, 'base_commit': case.base_commit, 'profile': case.profile_id,
                'execution_policy_sha256': executor.execution_fingerprint(case.profile_id)}
    (output / 'case.json').write_text(json.dumps(identity))
    result = executor.execute(case, patch, output, tmp_path / '.private/cache')
    assert result['status'] == 'initializing'
    with pytest.raises(FileExistsError):
        executor.execute(case, {'edits': ['different']}, output, tmp_path / '.private/cache')


def test_completed_replay_rechecks_exact_evidence_without_dispatch(tmp_path, monkeypatch, case):
    from ownstack.experiment_store import ExperimentStore, Result, canonical, digest
    monkeypatch.setattr(executor, 'ROOT', tmp_path)
    (tmp_path / '.private').mkdir()
    output = private_directory(tmp_path / '.private/replay')
    patch = {'edits': []}
    expected = dict(case_id=case.id, scope='upstream_issue', source_group=case.repo, source_split='test',
                    source_url=case.source_url, case_sha256=case.problem_sha256,
                    candidate_sha256=digest(canonical(patch)), oracle_sha256=case.oracle_sha256,
                    candidate_origin='human', reference_answer_visible=False)
    identity = {**expected, 'base_commit': case.base_commit, 'profile': case.profile_id,
                'execution_policy_sha256': executor.execution_fingerprint(case.profile_id)}
    (output / 'case.json').write_text(json.dumps(identity))
    store = ExperimentStore(output / 'results')
    proof = {'passed': False, 'released': False}
    (store.directory / 'execution.json').write_text(json.dumps(proof))
    store.append(Result(**expected, status='failed', evidence_file='execution.json',
                        evidence_sha256=digest((store.directory / 'execution.json').read_bytes())))
    (output / 'summary.json').write_text(json.dumps(proof))
    monkeypatch.setattr(executor.subprocess, 'run', lambda *a, **k: pytest.fail('Saved replay dispatched'))
    assert executor.execute(case, patch, output, tmp_path / '.private/cache')['saved_replay']
    (output / 'summary.json').unlink()
    assert executor.execute(case, patch, output, tmp_path / '.private/cache')['saved_replay']
    (store.directory / 'execution.json').write_text('{"passed":true}')
    with pytest.raises(ValueError, match='evidence changed'):
        executor.execute(case, patch, output, tmp_path / '.private/cache')
