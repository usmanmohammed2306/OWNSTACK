"""Actual HTTP journeys for a separate, synthetic, AI-off release-assurance lab.

The operator is a separate trusted process. This client never executes candidate
code, supplies check reports, changes a requirement after approval or calls AI.
Synthetic personas/stories are authored controls, not customer validation.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx


ROOT = Path(__file__).resolve().parents[1]
TERMINAL = {'passed', 'regression', 'baseline_failed', 'blocked', 'canceled'}
PROTECTED_PORTS = {8101, 8109, 8122}


def fixture_url(value):
    """Refuse remote URLs, implicit ports and previously used primary fixtures."""
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError('Explicit isolated loopback fixture required') from error
    if (parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', '::1'}
            or parsed.username or parsed.password or not port or port < 1024
            or port in PROTECTED_PORTS or parsed.path not in {'', '/'}
            or parsed.query or parsed.fragment):
        raise ValueError('Explicit isolated loopback fixture required; primary app ports are protected')
    return value.rstrip('/')


def public_value(value):
    """Never persist authentication material returned alongside an API result."""
    if isinstance(value, dict):
        return {key: ('[redacted]' if any(word in key.lower() for word in
                ('password', 'passphrase', 'secret', 'token', 'cookie', 'authorization'))
                else public_value(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [public_value(item) for item in value]
    return value


class Journal:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, mode=0o700, exist_ok=False)
        self.directory.chmod(0o700)
        self.records = []

    def append(self, value):
        record = public_value(value)
        record['at'] = datetime.now(timezone.utc).isoformat()
        self.records.append(record)
        fd = os.open(self.directory / 'results.jsonl', os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, 'a') as stream:
            stream.write(json.dumps(record, sort_keys=True) + '\n')
            stream.flush()
            os.fsync(stream.fileno())

    def finish(self, value):
        fd = os.open(self.directory / 'report.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(public_value(value), stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())


class Actor:
    def __init__(self, base, username, password, journal, *, transport=None):
        self.username = username
        self.journal = journal
        self.client = httpx.Client(base_url=base, timeout=20, trust_env=False, transport=transport,
                                   headers={'Origin': base})
        response = self.call('POST', '/v1/session', {'username': username, 'password': password})
        self.client.headers['Authorization'] = 'Bearer ' + response['token']
        self.client.headers['X-CSRF-Token'] = response['csrf_token']

    def call(self, method, path, body=None, expected=200):
        row = {'actor': self.username, 'method': method, 'path': path,
               'expected_status': expected, 'request': body}
        try:
            response = self.client.request(method, path, json=body)
            try:
                value = response.json()
            except ValueError:
                value = {'detail': 'Non-JSON API response'}
            row.update(status=response.status_code, response=value, passed=response.status_code == expected)
            if response.status_code != expected:
                raise AssertionError(f'{method} {path}: expected {expected}, observed {response.status_code}')
            return value
        except Exception as error:
            row.update(passed=False, error_type=type(error).__name__)
            raise
        finally:
            self.journal.append(row)

    def close(self):
        self.client.close()


def wait_for_check(actor, ident, *, deadline_seconds=180, interval=.25):
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        result = actor.call('GET', '/v1/release/checks/' + ident)
        if result['state'] in TERMINAL:
            return result
        time.sleep(interval)
    raise TimeoutError('Saved release check did not reach a terminal state within the local rehearsal bound')


def campaign(base, output, accounts, spec, hashes, *, check_create_status=202):
    """Exercise the API; caller starts a real isolated operator separately."""
    base = fixture_url(base)
    output = Path(output).resolve()
    if not output.is_relative_to(ROOT / '.private'):
        raise ValueError('Choose a new private directory within this repository')
    if os.environ.get('OWNSTACK_AI_MODE') != 'off' or os.environ.get('OWNSTACK_MAX_LIVE_CALLS') != '0':
        raise ValueError('Explicit AI off and cap zero required')
    if any(os.environ.get(key) for key in ('NEBIUS_API_KEY', 'NEBIUS_MODEL_ID', 'NEBIUS_PATCH_MODEL_ID')):
        raise ValueError('Empty provider credentials required')
    journal = Journal(output)
    actors = []
    result = {'passed': False, 'synthetic': True, 'customer_validation': False,
              'inference_calls': 0, 'execution': 'HTTP to separately operated fixture',
              'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    try:
        with httpx.Client(trust_env=False, timeout=10) as client:
            probe = {'method': 'GET', 'path': '/health/ready', 'expected_status': 200}
            try:
                health = client.get(base + '/health/ready')
                probe.update(status=health.status_code, response=health.json(), passed=health.status_code == 200)
                health.raise_for_status()
            except Exception as error:
                probe.update(passed=False, error_type=type(error).__name__)
                raise
            finally:
                journal.append(probe)
            assert health.json()['ai_mode'] == 'off'
        for name in ('atlas-engineer', 'atlas-admin', 'nova-admin'):
            actors.append(Actor(base, name, accounts[name], journal))
        engineer, owner, outsider = actors
        budget_before = owner.call('GET', '/v1/inference-budget')['reserved_calls']
        draft = engineer.call('POST', '/v1/release/requirements',
                              {'project_id': 'atlas-project', 'spec': spec}, expected=201)
        ident = draft['id'];requirement_hash = draft['requirement_hash']
        engineer.call('POST', f'/v1/release/requirements/{ident}/approve',
                      {'expected_hash': requirement_hash}, expected=403)
        owner.call('POST', f'/v1/release/requirements/{ident}/approve',
                   {'expected_hash': '0' * 64}, expected=409)
        approved = owner.call('POST', f'/v1/release/requirements/{ident}/approve',
                              {'expected_hash': requirement_hash})
        assert approved['state'] == 'approved'
        outsider.call('GET', f'/v1/release/requirements/{ident}', expected=404)
        assert ident not in {item['id'] for item in outsider.call('GET', '/v1/release/requirements')}
        prefix = 'release-story-' + uuid4().hex
        def queued(baseline, candidate, suffix):
            body = {'project_id': 'atlas-project', 'baseline_sha256': baseline,
                    'candidate_sha256': candidate, 'requirement_ids': [ident],
                    'idempotency_key': prefix + suffix}
            return engineer.call('POST', '/v1/release/checks', body, expected=check_create_status), body
        bad, body = queued(hashes['baseline'], hashes['regression'], '-regression')
        duplicate = engineer.call('POST', '/v1/release/checks', body, expected=check_create_status)
        assert duplicate['id'] == bad['id']
        collision = {**body, 'candidate_sha256': hashes['corrected']}
        engineer.call('POST', '/v1/release/checks', collision, expected=409)
        outsider.call('GET', '/v1/release/checks/' + bad['id'], expected=404)
        bad_result = wait_for_check(engineer, bad['id'])
        assert bad_result['state'] == 'regression', bad_result['state']
        assert bad_result['report'] and bad_result['evidence_hash']
        assert bad_result['report']['runner'] == 'release-http-docker-v1'
        assert bad_result['report']['profile'] == 'python-http-visibility-v1'
        assessments = bad_result['report']['assessments']
        targets = {case['case_id'] for case in spec['cases'] if case['kind'] == 'target'}
        controls = {case['case_id'] for case in spec['cases'] if case['kind'] == 'control'}
        assert any(case['case_id'] in targets and case['regression'] for case in assessments)
        assert all(case['baseline_passed'] and case['candidate_passed']
                   for case in assessments if case['case_id'] in controls)
        engineer.call('POST', '/v1/release/checks/' + bad['id'] + '/decide',
                      {'expected_revision': bad_result['revision'], 'evidence_hash': bad_result['evidence_hash'],
                       'decision': 'accept_for_manual_release'}, expected=409)
        corrected, _ = queued(hashes['baseline'], hashes['corrected'], '-corrected')
        good_result = wait_for_check(engineer, corrected['id'])
        assert good_result['state'] == 'passed', good_result['state']
        assert good_result['report']['runner'] == 'release-http-docker-v1'
        assert all(case['baseline_passed'] and case['candidate_passed']
                   for case in good_result['report']['assessments'])
        decided = engineer.call('POST', '/v1/release/checks/' + corrected['id'] + '/decide',
                                {'expected_revision': good_result['revision'], 'evidence_hash': good_result['evidence_hash'],
                                 'decision': 'accept_for_manual_release'})
        assert decided['decision'] == 'accept_for_manual_release'
        invalid, _ = queued(hashes['regression'], hashes['corrected'], '-baseline-invalid')
        invalid_result = wait_for_check(engineer, invalid['id'])
        assert invalid_result['state'] == 'baseline_failed', invalid_result['state']
        replay = engineer.call('GET', '/v1/release/checks/' + corrected['id'])
        assert replay['evidence_hash'] == good_result['evidence_hash']
        assert replay['decision'] == 'accept_for_manual_release'
        budget_after = owner.call('GET', '/v1/inference-budget')['reserved_calls']
        assert budget_before == budget_after == 0
        result.update(passed=True, requirement_id=ident, requirement_hash=requirement_hash,
                      regression_id=bad['id'], corrected_id=corrected['id'], baseline_invalid_id=invalid['id'],
                      budget_before=budget_before, budget_after=budget_after,
                      states={'regression': bad_result['state'], 'corrected': good_result['state'],
                              'invalid_baseline': invalid_result['state']}, http_results=len(journal.records),
                      limits='Finite authored stories and a separately operated repository profile; not all journeys, buyers or general integrations.')
    except Exception as error:
        result.update(error_type=type(error).__name__, http_results=len(journal.records))
        raise
    finally:
        for actor in actors:
            actor.close()
        journal.finish(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--accounts-file', required=True, type=Path)
    parser.add_argument('--requirement-json', required=True, type=Path)
    parser.add_argument('--baseline-sha256', required=True)
    parser.add_argument('--regression-sha256', required=True)
    parser.add_argument('--corrected-sha256', required=True)
    parser.add_argument('--private-output', required=True, type=Path)
    args = parser.parse_args()
    from ownstack.deployment import read_account_file
    result = campaign(args.url, args.private_output, read_account_file(args.accounts_file),
                      json.loads(args.requirement_json.read_text()),
                      {'baseline': args.baseline_sha256, 'regression': args.regression_sha256, 'corrected': args.corrected_sha256})
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
