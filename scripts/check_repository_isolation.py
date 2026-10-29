"""Finite real-container controls for the local repository executor.

These are synthetic boundary probes, not additional published issue resolutions
or certification against arbitrary hostile code. The network-denial probe cannot
reach its test destination; no provider or cloud service is used.
"""
import argparse
import json
import subprocess
from pathlib import Path
from ownstack.repository_executor import (
    IMAGE, RepositoryCase, private_directory, private_json, run_stage,
)
from ownstack.experiment_store import ExperimentStore, Result
from ownstack.repository_profiles import PROFILES, by_id

PROBE = '''import os,socket,errno
from pathlib import Path
import pytest

def test_nonroot_and_no_new_privileges():
    assert os.geteuid() == 65534
    status = Path('/proc/self/status').read_text()
    assert 'NoNewPrivs:\\t1' in status
    assert 'CapEff:\\t0000000000000000' in status
    assert 'Seccomp:\\t2' in status

def test_source_is_read_only():
    with pytest.raises(OSError) as error:
        Path('/repo/forbidden-write').write_text('no')
    assert error.value.errno in (errno.EROFS, errno.EACCES)

def test_external_network_is_unreachable():
    with socket.socket() as client:
        client.settimeout(.5)
        with pytest.raises(OSError):
            client.connect(('192.0.2.1',443))

def test_no_host_application_or_docker_socket():
    for name in ['/var/run/docker.sock','/srv/jobs','/app/.env','/repo/.private','/root/.ssh']:
        try:
            assert not Path(name).exists()
        except PermissionError:
            # Non-root cannot even stat /root/.ssh. Inaccessibility is the
            # required boundary; asserting physical absence would be false.
            assert name == '/root/.ssh'

def test_temporary_state_is_fresh_and_writable():
    sentinel = Path('/tmp/ownstack-isolation-sentinel')
    assert not sentinel.exists()
    sentinel.write_text('temporary state')
    assert sentinel.read_text() == 'temporary state'
'''

def run(output: Path, profile_id='flask-2.0-python3.10-v1'):
    profile = by_id(profile_id)
    output = private_directory(output)
    if any(output.iterdir()):
        raise FileExistsError('Keep previous boundary probes')
    store = ExperimentStore(output / 'results')
    image_id = subprocess.run(['docker', 'image', 'inspect', profile.image, '--format', '{{.Id}}'],
                              capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    tree = output / 'source'; (tree / profile.test_prefix).mkdir(parents=True)
    (tree / (profile.test_prefix + 'test_boundary.py')).write_text(PROBE)
    case = RepositoryCase('synthetic-container-boundary', profile.repo, 'a'*40,
                          'b'*64, '', (profile.test_prefix + 'test_boundary.py::test_nonroot_and_no_new_privileges',),
                          (profile.test_prefix + 'test_boundary.py::test_source_is_read_only',), 'c'*64,
                          'https://github.com/usmanmohammed2306/OWNSTACK', profile.id)
    checks = []
    for name in ('fresh-one', 'fresh-two'):
        report = run_stage(tree, case, output / name, image_id)
        passed = report['exit_code'] == 0 and not report['failure'] and len(report['states']) == 5 and all(v == 'passed' for v in report['states'].values())
        check = {'name': name + '-all-five-boundaries', 'passed': passed}; checks.append(check)
        store.append(Result(case_id=name, scope='control', source_group='ownstack-container-probes',
                            source_split='test', status='passed' if passed else 'failed', checks=[check]))
    timeout_tree = output / 'timeout-source'; (timeout_tree / profile.test_prefix).mkdir(parents=True)
    (timeout_tree / (profile.test_prefix + 'test_boundary.py')).write_text('def test_nonroot_and_no_new_privileges():\n    while True: pass\n')
    timed = run_stage(timeout_tree, case, output / 'deadline', image_id, timeout=3)
    invocation = json.loads((output / 'deadline/invocation.json').read_text())
    inspected = subprocess.run(['docker', 'container', 'inspect', invocation['container']],
                               capture_output=True, timeout=10, check=False)
    check = {'name': 'deadline-recorded-and-exact-container-removed',
             'passed': bool(timed['failure']) and 'deadline' in timed['failure'].lower() and inspected.returncode != 0}
    checks.append(check)
    store.append(Result(case_id='timeout', scope='control', source_group='ownstack-container-probes',
                        source_split='test', status='passed' if check['passed'] else 'failed', checks=[check],
                        reason='Intentional infinite-loop test stopped locally and owned container removal verified.'))
    report = {'passed': all(c['passed'] for c in checks), 'checks': checks,
              'profile': profile.id, 'image_id': image_id,
              'boundary_test_executions': 10, 'timeout_probes': 1,
              'published_issues_resolved': 0, 'provider_calls': 0,
              'limitation': 'Finite Docker boundary controls, not a certified hostile-code sandbox.'}
    private_json(output / 'summary.json', report)
    return report

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--profile', choices=sorted(PROFILES), default='flask-2.0-python3.10-v1')
    args = parser.parse_args()
    report = run(args.output, args.profile)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report['passed'] else 1)
