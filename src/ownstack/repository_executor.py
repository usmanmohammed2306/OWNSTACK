"""Local, operator-controlled execution of pinned external repository cases.

The first explicit environment profile supports Flask 2.0 cases only. The
original sample-app verifier remains unchanged. Repository code executes only
inside finite, non-root, no-network Docker jobs. This is an experimental
container boundary, not a certified hostile-code sandbox or SWE-bench score.
"""
from __future__ import annotations

from dataclasses import dataclass
import base64
import inspect
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import time
import tempfile
import xml.etree.ElementTree as ET
from uuid import uuid4

from ownstack.bounded_process import capture
from ownstack.experiment_store import ExperimentStore, Result, canonical, digest
from ownstack.repository_profiles import Profile, by_id, for_source, TRAIN_CASES, SUPPLEMENT, supplemental_cases

_SOURCE_ROOT = Path(os.getenv('OWNSTACK_SOURCE_ROOT', Path(__file__).resolve().parents[2]))
ROOT = _SOURCE_ROOT
MAX_ARCHIVE = 32 * 1024 * 1024
MAX_TREE = 64 * 1024 * 1024
MAX_FILE = 4 * 1024 * 1024
MAX_OUTPUT = 2 * 1024 * 1024
PROFILE = 'flask-2.0-python3.10-v1'
POLICY = 'repository-docker-readonly-no-network-v1'
IMAGE = 'ownstack-repository-flask20:local'

# This trusted parent never imports the repository. It retains the bounded test
# report while the tmpfs is still mounted, then exits with one JSON envelope.
# docker cp after a stopped tmpfs job cannot recover that report.
DRIVER = '''from __future__ import annotations
import base64,json,os,selectors,signal,stat,subprocess,sys,tempfile,time
''' + inspect.getsource(capture) + '''
command = [sys.executable, '-B', '-m', 'pytest', '-q', '-o', 'addopts=',
           '-o', 'cache_dir=/tmp/cache', '-o', 'junit_family=xunit1',
           '--junitxml=/tmp/ownstack-junit.xml', *sys.argv[1:]]
result = capture(command, b'', timeout=100, limit=524288)
report = b''
try:
    info = os.lstat('/tmp/ownstack-junit.xml')
    if not stat.S_ISREG(info.st_mode) or info.st_size > 1048576:
        raise ValueError('Test report is not a bounded regular file')
    with open('/tmp/ownstack-junit.xml', 'rb') as file:
        report = file.read(1048577)
except (OSError, ValueError) as error:
    result['failure'] = result['failure'] or str(error)
result['stdout'] = result.pop('stdout_bytes').decode('utf-8', errors='replace')
result['junit_base64'] = base64.b64encode(report).decode('ascii')
print(json.dumps(result))
'''


def private_json(path: Path, value: dict) -> None:
    # Publish complete bytes exclusively. A partial write must never become a
    # claim/result that replay mistakes for saved progress or a completed check.
    fd, temporary = tempfile.mkstemp(prefix='.private-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as file:
            json.dump(value, file, indent=2, ensure_ascii=False)
            file.write('\n'); file.flush(); os.fsync(file.fileno())
        os.link(temporary, path)  # Atomic exclusive publication; never overwrite.
        os.unlink(temporary)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def private_directory(path: Path) -> Path:
    """Never place an external run beside credentials or in a public source tree."""
    private_root = ROOT / '.private'
    if private_root.is_symlink() or path.is_symlink() or not path.absolute().resolve().is_relative_to(private_root.resolve()):
        raise ValueError('Use a separate nonsymlink directory under .private')
    anchor = private_root.resolve()
    anchor.mkdir(mode=0o700, exist_ok=True)
    parts = path.absolute().relative_to(anchor).parts
    if not parts:
        raise ValueError('Use a separate execution-state directory')
    component = anchor
    for part in parts:
        component = component / part
        if component.is_symlink():
            raise ValueError('No symlink execution-state ancestors')
        component.mkdir(mode=0o700, exist_ok=True)
        if component.stat().st_mode & 0o077:
            raise ValueError('Execution state and its ancestors must be private')
    return path.resolve()


@dataclass(frozen=True)
class RepositoryCase:
    id: str
    repo: str
    base_commit: str
    problem_sha256: str
    test_patch: str
    fail_to_pass: tuple[str, ...]
    pass_to_pass: tuple[str, ...]
    oracle_sha256: str
    source_url: str
    profile_id: str = PROFILE
    source_split: str = 'test'
    problem_text: str | None = None

    @classmethod
    def load(cls, catalog: Path, evaluator: Path, case_id: str):
        """Do not return, print or pass the upstream reference answer to a caller."""
        public = next((json.loads(line) for line in catalog.read_text().splitlines()
                       if json.loads(line)['id'] == case_id), None)
        if case_id in TRAIN_CASES:
            public = supplemental_cases()[case_id]
        row = next((json.loads(line) for line in evaluator.read_text().splitlines()
                    if json.loads(line)['instance_id'] == case_id), None)
        if not public or not row:
            raise ValueError('Case is absent from the frozen catalog/evaluator')
        profile = for_source(row['repo'], row['version'])
        if not re.fullmatch('[a-f0-9]{40}', row['base_commit']):
            raise ValueError('Source commit must be pinned')
        failed, retained = json.loads(row['FAIL_TO_PASS']), json.loads(row['PASS_TO_PASS'])
        if public.get('test_id_expansions'):
            original = {'fail_to_pass': failed, 'pass_to_pass': retained,
                        'test_patch_sha256': digest(row['test_patch'])}
            if (case_id not in TRAIN_CASES or digest(json.dumps(original, sort_keys=True, separators=(',', ':')))
                    != public.get('source_required_tests_sha256')):
                raise ValueError('Original oracle metadata differs from the correction source')
            for expansion in public['test_id_expansions']:
                old, required = expansion['source'], expansion['required']
                if (retained.count(old) != 1 or not isinstance(required, list) or len(required) < 2
                        or len(set(required)) != len(required)
                        or any(not isinstance(n, str) or not n.startswith(old) or not n.endswith(']') for n in required)):
                    raise ValueError('Only explicit complete parameter expansions are supported')
                retained = [n for source in retained for n in (required if source == old else [source])]
        tests = {'fail_to_pass': failed, 'pass_to_pass': retained,
                 'test_patch_sha256': digest(row['test_patch'])}
        if (public['repo'] != row['repo'] or public['base_commit'] != row['base_commit']
                or public['problem_sha256'] != digest(row['problem_statement'])
                or public['test_patch_sha256'] != digest(row['test_patch'])
                or public['required_tests_sha256'] != digest(json.dumps(tests, sort_keys=True, separators=(',', ':')))):
            raise ValueError('Case or independent oracle differs from the catalog')
        required = failed + retained
        if not failed or not retained or len(required) != len(set(required)):
            raise ValueError('Unique failing and regression tests are required')
        for node in required:
            if not isinstance(node, str) or not node.startswith(profile.test_prefix) or '\x00' in node or '\n' in node:
                raise ValueError('Unsafe required test identity')
            safe_relative(node.split('::')[0], profile.test_prefix)
        return cls(case_id, row['repo'], row['base_commit'], public['problem_sha256'],
                   row['test_patch'], tuple(failed), tuple(retained), public['required_tests_sha256'],
                   public['source_url'], profile.id,
                   'train' if case_id in TRAIN_CASES else 'test',
                   row['problem_statement'] if case_id in TRAIN_CASES else None)


def safe_relative(name: str, prefix: str | None = None) -> str:
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or '\\' in name or '\x00' in name
            or any(p in {'..', '.', '.git'} for p in name.split('/'))
            or (prefix and not name.startswith(prefix))):
        raise ValueError('Unsafe repository path')
    return path.as_posix()


def extract_archive(archive: Path, destination: Path, case: RepositoryCase) -> dict:
    """Extract regular public source only, with expansion/file/count limits."""
    if destination.exists():
        raise FileExistsError('Preserve existing source snapshots')
    if archive.stat().st_size > MAX_ARCHIVE:
        raise ValueError('Archive size limit exceeded')
    destination.mkdir(mode=0o755)
    total = 0
    count = 0
    profile = by_id(case.profile_id)
    if profile.repo != case.repo:
        raise ValueError('Repository differs from reviewed profile')
    root = case.repo.rsplit('/', 1)[-1] + '-' + case.base_commit
    seen = set()
    with tarfile.open(archive, 'r:gz') as bundle:
        for member in bundle:
            name = member.name.rstrip('/')
            if name == root and member.isdir():
                continue
            if not name.startswith(root + '/'):
                raise ValueError('Archive is not rooted at the pinned commit')
            relative = safe_relative(name[len(root) + 1:])
            if relative in seen:
                raise ValueError('Duplicate archive path')
            seen.add(relative)
            target = destination / relative
            if member.isdir():
                target.mkdir(mode=0o755, parents=True, exist_ok=True)
                continue
            if not member.isfile() or member.size > MAX_FILE or member.size < 0:
                raise ValueError('Links, devices and oversized files are not source files')
            total += member.size
            count += 1
            if total > MAX_TREE or count > 10000:
                raise ValueError('Expanded source limits exceeded')
            target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            with bundle.extractfile(member) as incoming, target.open('xb') as outgoing:
                shutil.copyfileobj(incoming, outgoing, length=65536)
            target.chmod(0o644)
    if not (destination / profile.marker).is_file():
        raise ValueError('Pinned repository source missing')
    generated = {}
    for name, content in profile.generated_files:
        path = destination / safe_relative(name)
        if path.exists():
            raise ValueError('Generated profile metadata would overwrite upstream source')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        path.chmod(0o644)
        generated[name] = digest(content)
    return {'archive_sha256': digest(archive.read_bytes()), 'files': count, 'expanded_bytes': total,
            'profile_generated_files': generated}


def fetch_source(case: RepositoryCase, directory: Path) -> tuple[Path, dict]:
    """Inbound public source only. Never execute repository installers on host."""
    import httpx
    directory = private_directory(directory)
    archive = directory / (case.base_commit + '.tar.gz')
    pin = directory / (case.base_commit + '.source.json')
    url = f'https://codeload.github.com/{case.repo}/tar.gz/{case.base_commit}'
    if archive.exists():
        if (archive.is_symlink() or not pin.exists() or pin.is_symlink()
                or digest(archive.read_bytes()) != json.loads(pin.read_text())['sha256']
                or json.loads(pin.read_text()).get('url') != url):
            raise ValueError('Saved source archive changed or lacks its first-fetch receipt')
    else:
        if os.getenv('OWNSTACK_REPOSITORY_OFFLINE','false').lower()=='true':
            raise ValueError('Offline repository source is not cached; no fetch was attempted')
        partial = archive.with_suffix('.partial')
        fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        count = 0
        with os.fdopen(fd, 'wb') as file, httpx.Client(timeout=60, trust_env=False, follow_redirects=False) as client:
            with client.stream('GET', url) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes():
                    count += len(chunk)
                    if count > MAX_ARCHIVE:
                        raise ValueError('Download limit exceeded; partial retained')
                    file.write(chunk)
        partial.rename(archive)
        private_json(pin, {'url': url, 'base_commit': case.base_commit,
                          'sha256': digest(archive.read_bytes()),
                          'trust': 'HTTPS commit-addressed first fetch, not a signed upstream attestation'})
    return archive, json.loads(pin.read_text())


def apply_test_patch(tree: Path, patch: str, profile_id: str = PROFILE) -> None:
    """Only evaluator-owned tests, no binary/mode/rename/external-path changes."""
    profile = by_id(profile_id)
    if len(patch.encode()) > 512000:
        raise ValueError('Oracle patch too large')
    headers = re.findall(r'^diff --git a/(\S+) b/(\S+)$', patch, re.M)
    if not headers:
        raise ValueError('Missing oracle diff headers')
    for left, right in headers:
        if left != right:
            raise ValueError('Oracle renames are not supported')
        safe_relative(left, profile.test_prefix)
    for line in patch.splitlines():
        if line.startswith(('old mode ', 'deleted file mode ', 'rename ', 'copy ', 'GIT binary', 'Binary files')):
            raise ValueError('Unsupported oracle patch operation')
        if line.startswith('new file mode ') and line != 'new file mode 100644':
            raise ValueError('Oracle must add regular text files')
        if line.startswith(('--- ', '+++ ')):
            name = line[4:]
            if name != '/dev/null':
                if not name.startswith(('a/', 'b/')):
                    raise ValueError('Unexpected oracle filename')
                safe_relative(name[2:], profile.test_prefix)
    env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': '/nonexistent',
           'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
           'GIT_CEILING_DIRECTORIES': str(tree.resolve().parent)}
    before = {name: digest((tree / name).read_bytes()) if (tree / name).exists() else None
              for name, _ in headers}
    for options in (['--check'], []):
        subprocess.run(['git', 'apply', *options, '-'], cwd=tree, input=patch.encode(),
                       env=env, check=True, capture_output=True, timeout=10)
    if any(not (tree / name).is_file() or digest((tree / name).read_bytes()) == prior
           for name, prior in before.items()):
        raise ValueError('Oracle patch was skipped or did not change every declared test file')


def tree_digest(tree: Path) -> str:
    files = {}
    for path in sorted(tree.rglob('*')):
        if path.is_symlink():
            raise ValueError('No symlinks in an execution tree')
        if path.is_file():
            files[path.relative_to(tree).as_posix()] = digest(path.read_bytes())
    return digest(canonical(files))


def apply_candidate(tree: Path, candidate: dict, profile_id: str = PROFILE) -> str:
    profile = by_id(profile_id)
    if set(candidate) != {'edits'} or not isinstance(candidate['edits'], list) or not 1 <= len(candidate['edits']) <= 8:
        raise ValueError('One to eight bounded source edits required')
    if len(canonical(candidate).encode()) > 128000:
        raise ValueError('Candidate size limit exceeded')
    seen = set()
    for edit in candidate['edits']:
        if not isinstance(edit, dict) or set(edit) != {'path', 'old', 'new'} or not all(isinstance(v, str) for v in edit.values()):
            raise ValueError('Expected exact path/old/new edit fields')
        name = safe_relative(edit['path'])
        if not name.startswith(profile.source_prefixes) or name.startswith(profile.forbidden_prefixes):
            raise ValueError('Only reviewed implementation paths may change')
        if name in dict(profile.generated_files):
            raise ValueError('Candidate cannot edit trusted generated profile metadata')
        anchor_identity = (name, edit['old'])
        if not name.endswith('.py') or anchor_identity in seen or name.endswith('conftest.py'):
            raise ValueError('Only distinct anchored edits to implementation modules may change')
        seen.add(anchor_identity)
        path = tree / name
        if not path.is_file() or path.is_symlink():
            raise ValueError('Candidate must edit an existing regular source file')
        source = path.read_text()
        if not edit['old'] or source.count(edit['old']) != 1 or edit['old'] == edit['new']:
            raise ValueError('Each edit must have one exact changed anchor')
        path.write_text(source.replace(edit['old'], edit['new'], 1))
    return digest(canonical(candidate))


def parse_junit(raw: bytes, profile_id: str = PROFILE) -> dict[str, str]:
    profile = by_id(profile_id)
    if not raw or len(raw) > MAX_OUTPUT or b'<!DOCTYPE' in raw or b'<!ENTITY' in raw:
        raise ValueError('Missing, excessive or unsafe JUnit report')
    root = ET.fromstring(raw)
    states = {}
    for case in root.iter('testcase'):
        file = safe_relative(case.attrib.get('file', ''), profile.test_prefix)
        classname = case.attrib.get('classname', '')
        prefix = file[:-3].replace('/', '.')
        if not classname.startswith(prefix):
            raise ValueError('Test namespace differs from its source file')
        suffix = classname[len(prefix):].lstrip('.')
        node = file + '::' + (suffix.replace('.', '::') + '::' if suffix else '') + case.attrib['name']
        if node in states:
            raise ValueError('Duplicate test result')
        children = {c.tag for c in case}
        states[node] = 'failed' if children & {'failure', 'error'} else 'skipped' if 'skipped' in children else 'passed'
    if not states:
        raise ValueError('No observed tests')
    return states


def docker_command(name: str, image_id: str, tree: Path, modules: list[str], profile_id: str = PROFILE) -> list[str]:
    profile = by_id(profile_id)
    if not re.fullmatch('sha256:[a-f0-9]{64}', image_id) or not name.startswith('ownstack-repo-'):
        raise ValueError('Immutable local image and owned container name required')
    if any(c in str(tree.resolve()) for c in ',\n\r\x00'):
        raise ValueError('Unsafe Docker mount path')
    for module in modules:
        safe_relative(module, profile.test_prefix)
    return ['docker', 'run', '--name', name, '--pull', 'never', '--log-driver', 'none',
            '--network', 'none', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
            '--user', '65534:65534', '--pids-limit', '64', '--memory', '512m', '--memory-swap', '512m',
            '--cpus', '1', '--ulimit', 'cpu=90:90', '--ulimit', 'fsize=4194304:4194304',
            '--ulimit', 'nofile=128:128', '--tmpfs', '/tmp:rw,noexec,nosuid,size=67108864,mode=1777',
            '--mount', f'type=bind,src={tree.resolve()},dst=/repo,readonly', '--workdir', '/repo',
            '--env', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD=1', '--env', 'PYTHONPATH=' + profile.pythonpath,
            image_id, 'python', '-I', '-B', '-c', DRIVER, *profile.pytest_args, *modules]


def run_stage(tree: Path, case: RepositoryCase, output: Path, image_id: str, *, timeout: int = 120) -> dict:
    if type(timeout) is not int or not 1 <= timeout <= 180:
        raise ValueError('Use an integer wall deadline between one and 180 seconds')
    output.mkdir(mode=0o700)
    modules = sorted({node.split('::')[0] for node in (*case.fail_to_pass, *case.pass_to_pass)})
    name = 'ownstack-repo-' + uuid4().hex
    command = docker_command(name, image_id, tree, modules, case.profile_id)
    private_json(output / 'invocation.json', {'argv': command, 'policy': POLICY, 'timeout_s': timeout,
                                            'tree_sha256': tree_digest(tree), 'container': name})
    started = time.monotonic()
    try:
        result = capture(command, b'', timeout=timeout, limit=MAX_OUTPUT,
                         process_record=output / 'process.json',
                         env={'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': os.environ.get('HOME', '/tmp')})
        (output / 'envelope.log').write_bytes(result['stdout_bytes'])
        xml = output / 'junit.xml'
        states = {}
        error = result['failure']
        test_exit = result['exit_code']
        try:
            envelope = json.loads(result['stdout_bytes'])
            if set(envelope) != {'stdout', 'stderr', 'exit_code', 'failure', 'junit_base64'}:
                raise ValueError('Invalid trusted-driver envelope')
            if result['exit_code'] != 0:
                raise ValueError('Trusted driver did not finish normally')
            test_exit = envelope['exit_code']
            error = error or envelope['failure']
            xml.write_bytes(base64.b64decode(envelope['junit_base64'], validate=True))
            (output / 'stdout.log').write_text(envelope['stdout'])
            (output / 'stderr.log').write_text(envelope['stderr'])
            states = parse_junit(xml.read_bytes(), case.profile_id)
        except (ValueError, KeyError, ET.ParseError) as exc:
            error = error or str(exc)
            stderr = output / 'stderr.log'
            inner = stderr.read_text() if stderr.exists() else ''
            stderr.write_text(inner + result['stderr'] + '\n' + str(exc))
        # Collection crashes, crashes after test output, skips and missing expected
        # IDs cannot be turned into an issue-success label by a zero exit code.
        report = {'exit_code': test_exit, 'failure': error, 'states': states,
                  'elapsed_s': round(time.monotonic() - started, 3), 'image_id': image_id,
                  'policy': POLICY, 'modules': modules, 'required_tests': len(case.fail_to_pass) + len(case.pass_to_pass),
                  'provider_calls': 0}
        private_json(output / 'report.json', report)
        return report
    finally:
        subprocess.run(['docker', 'rm', '--force', name], capture_output=True, timeout=15, check=False)


def assess(case: RepositoryCase, baseline: dict, candidate: dict) -> dict:
    required = list(case.fail_to_pass + case.pass_to_pass)
    base = baseline['states']; patched = candidate['states']
    baseline_ok = (not baseline['failure'] and baseline['exit_code'] == 1
                   and all(base.get(t) == 'failed' for t in case.fail_to_pass)
                   and all(base.get(t) == 'passed' for t in case.pass_to_pass)
                   and all(state in {'passed', 'skipped'} or name in case.fail_to_pass
                           for name, state in base.items()))
    candidate_ok = (not candidate['failure'] and candidate['exit_code'] == 0
                    and all(patched.get(t) == 'passed' for t in required)
                    and all(s in {'passed', 'skipped'} for s in patched.values()))
    return {'passed': baseline_ok and candidate_ok, 'baseline_failed': baseline_ok,
            'candidate_passed': candidate_ok, 'required_tests': required,
            'observed_tests': {t: patched.get(t) == 'passed' for t in required},
            'missing_baseline': [t for t in required if t not in base],
            'missing_candidate': [t for t in required if t not in patched]}


def saved_attempt(output: Path, expected: dict) -> dict:
    """Return saved progress/results; never launch Docker during a replay."""
    metadata = output / 'case.json'
    if not metadata.exists():
        if (output / 'claim.lock').exists():
            return {'status': 'initializing', 'passed': False, 'saved_replay': True,
                    'provider_calls': 0, 'released': False}
        raise FileExistsError('Unrecognized nonempty attempt directory; preserve it')
    stored = json.loads(metadata.read_text())
    for key, value in expected.items():
        if stored.get(key) != value:
            raise FileExistsError('Attempt identity/candidate/oracle changed; choose a new attempt directory')
    store = ExperimentStore(output / 'results')
    rows = store.records()
    latest = rows[-1]['result'] if rows else {'status': 'initializing'}
    if latest.get('status') in {'passed', 'failed'} and latest.get('evidence_file') == 'execution.json':
        evidence = store.directory / 'execution.json'
        if digest(evidence.read_bytes()) != latest.get('evidence_sha256'):
            raise ValueError('Saved execution evidence changed; no automatic rerun')
        proof = json.loads(evidence.read_text())
        summary = output / 'summary.json'
        if summary.exists() and json.loads(summary.read_text()) != proof:
            raise ValueError('Saved execution evidence changed; no automatic rerun')
        # The transactional terminal result is authoritative even if the process
        # stopped before writing its redundant human-readable summary.
        return {**proof, 'saved_replay': True}
    return {'status': latest['status'], 'passed': False, 'saved_replay': True,
            'reason': latest.get('reason', ''), 'provider_calls': 0, 'released': False}


def _read_execution_fingerprint(profile_id: str) -> str:
    profile = by_id(profile_id)
    source_root = _SOURCE_ROOT
    return digest(canonical({name: digest((source_root / name).read_bytes()) for name in (
        'src/ownstack/repository_executor.py', 'src/ownstack/repository_profiles.py',
        'src/ownstack/bounded_process.py', profile.dockerfile,
        SUPPLEMENT + '/cases.jsonl', SUPPLEMENT + '/manifest.json')}))


from ownstack.repository_profiles import PROFILES as _PROFILES
_LOADED_EXECUTION = {name: _read_execution_fingerprint(name) for name in _PROFILES}


def execution_fingerprint(profile_id: str) -> str:
    """Bind loaded code; disk drift requires a fresh operator process."""
    by_id(profile_id)
    expected = _LOADED_EXECUTION[profile_id]
    if _read_execution_fingerprint(profile_id) != expected:
        raise ValueError('Execution code changed; restart the local operator')
    return expected


def execute(case: RepositoryCase, candidate: dict, output: Path, cache: Path, *, origin: str = 'human') -> dict:
    """One exact case/patch attempt; no patch generation, approval or release."""
    if origin not in {'human', 'model', 'reference'}:
        raise ValueError('Declare candidate provenance')
    output = private_directory(output)
    candidate_hash = digest(canonical(candidate))
    profile = by_id(case.profile_id)
    if profile.repo != case.repo or case.source_split not in {'test', 'train', 'validation', 'unassigned'}:
        raise ValueError('Invalid profile or source split')
    common = dict(case_id=case.id, scope='upstream_issue', source_group=case.repo, source_split=case.source_split,
                  source_url=case.source_url, case_sha256=case.problem_sha256, candidate_sha256=candidate_hash,
                  oracle_sha256=case.oracle_sha256, candidate_origin=origin,
                  reference_answer_visible=origin == 'reference')
    if case.source_split == 'train':
        # Saving model input/output is not admission to training. Source rights,
        # reconstructed problem quality and actual human review remain gates.
        common.update(prompt=case.problem_text if case.problem_text and len(case.problem_text) <= 100000 else None,
                      completion=canonical(candidate) if origin != 'reference' and len(canonical(candidate)) <= 100000 else None)
    identity = {**common, 'base_commit': case.base_commit, 'profile': profile.id,
                'execution_policy_sha256': execution_fingerprint(profile.id)}
    if any(output.iterdir()):
        return saved_attempt(output, identity)
    try:
        # Exclusive creation is the cross-process work claim. A repeated request
        # during bootstrap sees progress rather than starting duplicate jobs.
        private_json(output / 'claim.lock', identity)
    except FileExistsError:
        return saved_attempt(output, identity)
    private_json(output / 'case.json', identity)
    store = ExperimentStore(output / 'results')
    store.append(Result(**common, status='running', reason='Pinned repository attempt started; no success implied.'))
    private_json(output / 'candidate.json', candidate)
    try:
        inspected = subprocess.run(['docker', 'image', 'inspect', profile.image, '--format', '{{.Id}}'],
                                   capture_output=True, text=True, check=True, timeout=15)
        image_id = inspected.stdout.strip()
        if not re.fullmatch('sha256:[a-f0-9]{64}', image_id):
            raise ValueError('Invalid execution image identity')
        archive, receipt = fetch_source(case, cache)
        base_tree = output / 'baseline-source'
        extraction = extract_archive(archive, base_tree, case)
        apply_test_patch(base_tree, case.test_patch, case.profile_id)
        patched_tree = output / 'candidate-source'
        shutil.copytree(base_tree, patched_tree)
        assert apply_candidate(patched_tree, candidate, case.profile_id) == candidate_hash
        private_json(output / 'source.json', {**receipt, **extraction, 'baseline_tree_sha256': tree_digest(base_tree),
                                             'candidate_tree_sha256': tree_digest(patched_tree)})
        baseline = run_stage(base_tree, case, output / 'baseline', image_id)
        patched = run_stage(patched_tree, case, output / 'candidate', image_id)
        outcome = assess(case, baseline, patched)
        if execution_fingerprint(profile.id) != identity['execution_policy_sha256']:
            raise ValueError('Execution policy changed during checks')
        proof = {**outcome, 'case_id': case.id, 'case_sha256': case.problem_sha256,
                 'candidate_sha256': candidate_hash, 'oracle_sha256': case.oracle_sha256,
                 'base_commit': case.base_commit, 'image_id': image_id, 'profile': profile.id,
                 'execution_policy_sha256': identity['execution_policy_sha256'],
                 'policy': POLICY, 'origin': origin, 'provider_calls': 0, 'released': False,
                 'not_a_security_guarantee': True}
        private_json(store.directory / 'execution.json', proof)
        checks = [{'name': 'baseline_reproduced_with_regressions_intact', 'passed': outcome['baseline_failed']},
                  {'name': 'candidate_required_and_collected_tests_pass', 'passed': outcome['candidate_passed']}]
        status = 'passed' if outcome['passed'] else 'failed' if outcome['baseline_failed'] else 'blocked'
        store.append(Result(**common, status=status, checks=checks,
                            evidence_file='execution.json', evidence_sha256=digest((store.directory / 'execution.json').read_bytes()),
                            reason='Independent upstream test patch, local declared candidate; no deployment or model-performance claim.'))
        private_json(output / 'summary.json', proof)
        return proof
    except (Exception, KeyboardInterrupt) as error:
        store.append(Result(**common, status='aborted' if isinstance(error, KeyboardInterrupt) else 'blocked',
                            reason=f'{type(error).__name__}: {str(error)[:1800]}'))
        private_json(output / 'failure.json', {'error': type(error).__name__, 'reason': str(error)[:2000],
                                             'provider_calls': 0, 'passed': False})
        raise
