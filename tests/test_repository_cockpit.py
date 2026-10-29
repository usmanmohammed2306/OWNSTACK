"""Authenticated workflow/fencing tests. Executor results here are explicit fakes.

Actual TCP/browser/Docker request journeys are retained separately in .private.
"""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select, func

from conftest import login
from ownstack.models import ChangeRequest, EngineeringItem, Evidence, InferenceBudget, User
from ownstack.policy import digest
from ownstack.repository_cockpit import catalog, context_hash, matching
from ownstack.repository_executor import ROOT, PROFILE, canonical, digest as byte_digest, execution_fingerprint
from ownstack.repository_worker import work_once
from ownstack.service import utcnow


@pytest.fixture
def local_repo(monkeypatch, tmp_path):
    monkeypatch.setenv('OWNSTACK_REPOSITORY_COCKPIT', 'true')
    monkeypatch.setenv('OWNSTACK_AI_MODE', 'off')
    monkeypatch.setenv('NEBIUS_API_KEY', '')
    monkeypatch.setattr('ownstack.repository_executor.ROOT', tmp_path)
    # The private-directory boundary uses its own root. Case policy/catalog still
    # use the real source; no external code executes under this temporary root.
    (tmp_path / '.private').mkdir()
    return tmp_path / '.private/jobs'


def item(client, case='pallets__flask-4160'):
    headers = login(client, 'atlas-engineer')
    result = client.post('/v1/requests', headers={**headers, 'Idempotency-Key': __import__('uuid').uuid4().hex},
        json={'text': 'Correct the customer serialization behavior in the pinned repository.',
              'kind': 'feature', 'project_id': 'atlas-project'})
    assert result.status_code == 201, result.text
    request_id = result.json()['id']
    result = client.post(f'/v1/requests/{request_id}/manual-handoff', headers={**headers, 'Idempotency-Key': 'handoff-' + request_id})
    assert result.status_code == 200, result.text
    work = next(w for w in client.get('/v1/engineering', headers=headers).json() if w['request_id'] == request_id)
    iid = work['id']
    result = client.post(f'/v1/engineering/{iid}/repository', headers=headers, json={'case_id': case})
    assert result.status_code == 200, result.text
    candidate = client.get(f'/v1/repository-cases/{case}/example', headers=headers).json()['patch']
    result = client.post(f'/v1/engineering/{iid}/manual-patch', headers=headers,
                         json={'patch': candidate, 'candidate_origin': 'model'})
    assert result.status_code == 200, result.text
    return iid, request_id, headers, candidate


def fake_executor(monkeypatch, *, passed=True, baseline=True, during=None):
    """Independent fake proving control behavior, never a real resolution claim."""
    def load(*args):
        public = catalog()[args[-1]]
        return SimpleNamespace(id=public['id'], base_commit=public['base_commit'],
            problem_sha256=public['problem_sha256'], oracle_sha256=public['required_tests_sha256'],
            public=public)
    def execute(case, patch, output, cache, origin):
        if during:
            during()
        names = [f'tests/synthetic.py::test_{n}' for n in range(case.public['fail_to_pass_count'] + case.public['pass_to_pass_count'])]
        for path in {e['path'] for e in patch['edits']}:
            for stage, field in [('baseline-source', 'old'), ('candidate-source', 'new')]:
                target = output / stage / path; target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(''.join(e[field] for e in patch['edits'] if e['path'] == path))
        return {'passed': passed, 'baseline_failed': baseline, 'candidate_passed': passed,
                'case_id': case.id, 'origin': origin,
                'case_sha256': case.problem_sha256, 'candidate_sha256': byte_digest(canonical(patch)),
                'oracle_sha256': case.oracle_sha256, 'base_commit': case.base_commit, 'profile': case.public['profile'],
                'execution_policy_sha256': execution_fingerprint(case.public['profile']),
                'required_tests': names, 'observed_tests': {n: passed for n in names}, 'released': False}
    monkeypatch.setattr('ownstack.repository_worker.RepositoryCase.load', load)
    monkeypatch.setattr('ownstack.repository_worker.execute', execute)


def work(factory, directory):
    # Evaluator path is validated as private but never read by the explicit fake.
    return work_once(factory, directory, ROOT / '.private/evaluator-unit-placeholder.jsonl', directory / 'cache')


def test_nonreproducing_baseline_is_blocked_not_a_candidate_failure(client, fixture_db, local_repo, monkeypatch):
    iid, rid, headers, patch = item(client)
    assert client.post(f'/v1/engineering/{iid}/verify', headers=headers).status_code == 202
    fake_executor(monkeypatch, passed=False, baseline=False)
    assert work(fixture_db, local_repo)
    detail = client.get(f'/v1/engineering/{iid}', headers=headers).json()
    current = detail['repository']['checks'][-1]
    assert current['state'] == 'blocked' and current['error_code'] == 'BASELINE_NOT_REPRODUCED'
    assert not detail['current_checks_usable']
    assert client.post(f'/v1/engineering/{iid}/decide', headers=headers,
                       json={'decision': 'accept_for_manual_release', 'patch_hash': detail['patch_hash']}).status_code == 409
    assert client.post(f'/v1/engineering/{iid}/decide', headers=headers,
                       json={'decision': 'take_over', 'patch_hash': detail['patch_hash']}).status_code == 200
    assert client.get(f'/v1/engineering/{iid}/artifact', headers=headers).status_code == 409


@pytest.mark.parametrize('case_id', ['pytest-dev__pytest-10624', 'sphinx-doc__sphinx-7738', 'sphinx-doc__sphinx-7757', 'pallets__jinja-1537'])
def test_new_profile_exact_review_with_explicit_fake_control(client, fixture_db, local_repo, monkeypatch, case_id):
    iid, rid, headers, patch = item(client, case_id)
    wrong = {'edits': [{'path': 'src/flask/json/__init__.py', 'old': 'x', 'new': 'y'}]}
    assert client.post(f'/v1/engineering/{iid}/manual-patch', headers=headers,
                       json={'patch': wrong, 'candidate_origin': 'model'}).status_code == 422
    assert client.post(f'/v1/engineering/{iid}/verify', headers=headers).status_code == 202
    fake_executor(monkeypatch)
    assert work(fixture_db, local_repo)
    detail = client.get(f'/v1/engineering/{iid}', headers=headers).json()
    assert detail['current_checks_usable']
    repo = detail['repository']
    exact = {'decision': 'accept_for_manual_release', 'patch_hash': detail['patch_hash'],
             'verification_id': repo['verification_id'], 'context_hash': repo['context_hash']}
    assert client.post(f'/v1/engineering/{iid}/decide', headers=headers, json=exact).status_code == 200
    assert client.get(f'/v1/engineering/{iid}/artifact', headers=headers).json()['release_state'] == 'not_deployed'


def test_request_to_exact_review_and_artifact(client, fixture_db, local_repo, monkeypatch):
    iid, rid, headers, patch = item(client)
    first = client.post(f'/v1/engineering/{iid}/verify', headers=headers)
    assert first.status_code == 202
    assert client.post(f'/v1/engineering/{iid}/verify', headers=headers).json()['id'] == first.json()['id']
    fake_executor(monkeypatch)
    assert work(fixture_db, local_repo)
    detail = client.get(f'/v1/engineering/{iid}', headers=headers).json()
    assert detail['current_checks_usable'] and detail['status'] == 'checks_passed'
    review = detail['repository']
    body = {'decision': 'accept_for_manual_release', 'patch_hash': detail['patch_hash'],
            'verification_id': review['verification_id'], 'context_hash': review['context_hash']}
    for field in ['patch_hash', 'verification_id', 'context_hash']:
        assert client.post(f'/v1/engineering/{iid}/decide', headers=headers, json={**body, field: 'wrong'}).status_code == 409
    assert client.get(f'/v1/engineering/{iid}/artifact', headers=headers).status_code == 409
    result = client.post(f'/v1/engineering/{iid}/decide', headers=headers, json=body)
    assert result.json()['release_state'] == 'not_deployed'
    artifact = client.get(f'/v1/engineering/{iid}/artifact', headers=headers).json()
    assert artifact['patch'] == patch and artifact['verification_id'] == review['verification_id']
    assert '--- a/src/flask/json/__init__.py' in artifact['diff']
    assert client.post(f'/v1/engineering/{iid}/decide', headers=headers, json=body).status_code == 409
    with fixture_db() as db:
        assert db.get(InferenceBudget, 'global').reserved_calls == 0
        assert db.scalar(select(func.count()).select_from(Evidence).where(Evidence.kind == 'repository_checks')) == 1


def test_failure_retry_and_saved_refresh_do_not_launch_work(client, fixture_db, local_repo, monkeypatch):
    iid, _, headers, _ = item(client)
    first = client.post(f'/v1/engineering/{iid}/verify', headers=headers).json()
    fake_executor(monkeypatch, passed=False); assert work(fixture_db, local_repo)
    for _ in range(3):
        assert client.get(f'/v1/engineering/{iid}', headers=headers).json()['status'] == 'checks_failed'
        assert client.post(f'/v1/engineering/{iid}/verify', headers=headers).json()['id'] == first['id']
    assert client.post(f'/v1/engineering/{iid}/repository/retry', headers=headers, json={'verification_id': 'wrong'}).status_code == 409
    second = client.post(f'/v1/engineering/{iid}/repository/retry', headers=headers, json={'verification_id': first['id']}).json()
    assert second['id'] != first['id']
    fake_executor(monkeypatch); assert work(fixture_db, local_repo)
    history = client.get(f'/v1/engineering/{iid}', headers=headers).json()['repository']['checks']
    assert [h['state'] for h in history] == ['failed', 'passed']


def test_canceled_late_attempt_cannot_override_new_checks(client, fixture_db, local_repo, monkeypatch):
    iid, _, headers, _ = item(client)
    first = client.post(f'/v1/engineering/{iid}/verify', headers=headers).json()
    second = []
    def during():
        repeated = client.post(f'/v1/engineering/{iid}/verify', headers=headers)
        assert repeated.status_code == 202 and repeated.json()['id'] == first['id']
        stopped = client.post(f'/v1/engineering/{iid}/repository/cancel', headers=headers, json={'verification_id': first['id']})
        assert stopped.json()['state'] == 'canceled'
        second.append(client.post(f'/v1/engineering/{iid}/repository/retry', headers=headers, json={'verification_id': first['id']}).json())
    fake_executor(monkeypatch, during=during); assert work(fixture_db, local_repo)
    state = client.get(f'/v1/engineering/{iid}', headers=headers).json()
    assert state['status'] == 'checking' and not state['current_checks_usable']
    assert state['repository']['verification_id'] == second[0]['id']
    fake_executor(monkeypatch); assert work(fixture_db, local_repo)
    state = client.get(f'/v1/engineering/{iid}', headers=headers).json()
    assert state['current_checks_usable']
    assert [c['state'] for c in state['repository']['checks']] == ['canceled', 'passed']


@pytest.mark.parametrize('field', ['text', 'revision'])
def test_request_change_invalidates_binding_before_dispatch(client, fixture_db, local_repo, monkeypatch, field):
    iid, rid, headers, _ = item(client)
    client.post(f'/v1/engineering/{iid}/verify', headers=headers)
    with fixture_db() as db:
        request = db.get(ChangeRequest, rid)
        setattr(request, field, request.revision + 1 if field == 'revision' else request.text + ' changed')
        db.commit()
    monkeypatch.setattr('ownstack.repository_worker.execute', lambda *a, **k: pytest.fail('Stale work dispatched'))
    assert work(fixture_db, local_repo)
    assert not client.get(f'/v1/engineering/{iid}', headers=headers).json()['current_checks_usable']


def test_expired_queued_check_survives_refresh_and_explicit_retry(client, fixture_db, local_repo):
    iid, _, headers, _ = item(client)
    first = client.post(f'/v1/engineering/{iid}/verify', headers=headers).json()
    with fixture_db() as db:
        db.get(EngineeringItem, iid).operation_deadline = utcnow() - timedelta(seconds=1); db.commit()
    detail = client.get(f'/v1/engineering/{iid}', headers=headers).json()
    assert detail['repository']['checks'][0]['state'] == 'timed_out'
    assert client.post(f'/v1/engineering/{iid}/repository/retry', headers=headers, json={'verification_id': first['id']}).status_code == 200


def test_actor_revocation_discards_result(client, fixture_db, local_repo, monkeypatch):
    iid, _, headers, _ = item(client)
    client.post(f'/v1/engineering/{iid}/verify', headers=headers)
    def revoke():
        with fixture_db() as db:
            db.get(User, 'atlas-engineer').enabled = False; db.commit()
    fake_executor(monkeypatch, during=revoke); assert work(fixture_db, local_repo)
    with fixture_db() as db:
        record = db.get(EngineeringItem, iid)
        assert record.status == 'checks_failed'
        assert not matching(db, record)


@pytest.mark.parametrize('when',['before_dispatch','during_execution'])
def test_team_revocation_blocks_repository_claim_or_discards_late_result(client,fixture_db,local_repo,monkeypatch,when):
    """Control test with an explicit executor double, not an execution proof."""
    from ownstack.models import TeamMembership
    iid,rid,headers,_=item(client)
    assert client.post(f'/v1/engineering/{iid}/verify',headers=headers).status_code==202
    def revoke():
        with fixture_db() as db:
            db.scalar(select(TeamMembership).where(TeamMembership.user_id=='atlas-engineer')).enabled=False
            db.commit()
    if when=='before_dispatch':
        revoke()
        monkeypatch.setattr('ownstack.repository_worker.execute',lambda *a,**k:pytest.fail('Revoked team work dispatched'))
    else:fake_executor(monkeypatch,during=revoke)
    assert work(fixture_db,local_repo)
    assert client.get(f'/v1/engineering/{iid}',headers=headers).status_code==404
    peer=client.get(f'/v1/engineering/{iid}',headers=login(client,'atlas-admin'))
    assert peer.status_code==200 and peer.json()['status']=='checks_failed'
    assert not peer.json()['current_checks_usable']
    with fixture_db() as db:
        evidence=db.scalar(select(Evidence).where(Evidence.kind=='repository_checks'))
        assert evidence.result['state']=='superseded'
        if when=='during_execution':assert evidence.result['accepted'] is False and evidence.result['late_result_saved'] is True
        assert db.get(InferenceBudget,'global').reserved_calls==0


@pytest.mark.parametrize('revocation',['membership','identity'])
def test_late_revoked_completion_cannot_clear_a_peer_retry_after_its_read(client,fixture_db,local_repo,monkeypatch,revocation):
    """Explicit fake executor; force the read-to-write race after completion reads."""
    from ownstack.models import TeamMembership
    from ownstack.team_scope import add_general_member
    import ownstack.repository_worker as worker
    with fixture_db() as db:
        author=db.get(User,'atlas-engineer')
        peer=User(id='scope-peer-engineer',tenant_id='atlas',role='engineer',password_hash=author.password_hash)
        db.add(peer);db.flush();add_general_member(db,peer);db.commit()
    iid,_,author,_=item(client);peer=login(client,'scope-peer-engineer');admin=login(client,'atlas-admin')
    first=client.post(f'/v1/engineering/{iid}/verify',headers=author).json()
    original=worker.authorized;calls=0;replacement=[]
    def racing(*args):
        nonlocal calls
        calls+=1
        if calls==2:
            stopped=client.post(f'/v1/engineering/{iid}/repository/cancel',headers=peer,json={'verification_id':first['id']})
            assert stopped.status_code==200
            retry=client.post(f'/v1/engineering/{iid}/repository/retry',headers=peer,json={'verification_id':first['id']})
            assert retry.status_code==200;replacement.append(retry.json()['id'])
            if revocation=='identity':
                assert client.post('/v1/members/atlas-engineer/access',headers=admin,json={'enabled':False}).status_code==200
            else:
                with fixture_db() as db:team=db.scalar(select(TeamMembership).where(TeamMembership.user_id=='atlas-engineer')).team_id
                assert client.put(f'/v1/teams/{team}/members/atlas-engineer',headers=admin,json={'role':'member','enabled':False,'expected_revision':1}).status_code==200
        return original(*args)
    monkeypatch.setattr(worker,'authorized',racing);fake_executor(monkeypatch)
    assert work(fixture_db,local_repo)
    current=client.get(f'/v1/engineering/{iid}',headers=peer).json()
    assert current['repository']['verification_id']==replacement[0]
    assert current['status']=='checking'
    assert [r['state'] for r in current['repository']['checks']]==['canceled','queued']
    assert work(fixture_db,local_repo)
    assert client.get(f'/v1/engineering/{iid}',headers=peer).json()['current_checks_usable']


def test_roles_tenant_scope_and_no_model_routes(client, fixture_db, local_repo):
    iid, _, headers, _ = item(client)
    other = login(client, 'nova-admin')
    assert client.get(f'/v1/engineering/{iid}', headers=other).status_code == 404
    assert client.post(f'/v1/engineering/{iid}/repository', headers=other, json={'case_id': 'pallets__flask-4045'}).status_code == 403
    admin = login(client, 'atlas-admin')
    assert client.post(f'/v1/engineering/{iid}/verify', headers=admin).status_code == 403
    assert client.post(f'/v1/engineering/{iid}/draft', headers=headers).status_code == 409
    assert client.post(f'/v1/engineering/{iid}/repairs', headers=headers, json={'patch_hash': '0'*64}).status_code == 409
    with fixture_db() as db:
        assert db.get(InferenceBudget, 'global').reserved_calls == 0


@pytest.mark.parametrize('patch', [{'command': 'rm -rf /'}, {'edits': [{'path': 'tests/test_a.py', 'old': 'a', 'new': 'b'}]},
    {'edits': [{'path': 'src/flask/../../outside.py', 'old': 'a', 'new': 'b'}]}])
def test_candidate_cannot_supply_commands_tests_or_paths(client, local_repo, patch):
    iid, _, headers, _ = item(client)
    result = client.post(f'/v1/engineering/{iid}/manual-patch', headers=headers, json={'patch': patch, 'candidate_origin': 'model'})
    assert result.status_code == 422


def test_context_policy_and_report_tampering_fail_closed(client, fixture_db, local_repo, monkeypatch):
    iid, _, headers, _ = item(client)
    client.post(f'/v1/engineering/{iid}/verify', headers=headers)
    fake_executor(monkeypatch); assert work(fixture_db, local_repo)
    with fixture_db() as db:
        target = db.scalar(select(Evidence).where(Evidence.kind == 'repository_checks'))
        original = deepcopy(target.result)
        target.result = {**original, 'report': {**original['report'], 'required_tests': None}}
        db.commit()
    assert not client.get(f'/v1/engineering/{iid}', headers=headers).json()['current_checks_usable']
    with fixture_db() as db:
        target = db.scalar(select(Evidence).where(Evidence.kind == 'repository_checks')); target.result = original; db.commit()
    monkeypatch.setattr('ownstack.repository_cockpit.policy_hash', lambda: 'changed-policy')
    assert not client.get(f'/v1/engineering/{iid}', headers=headers).json()['current_checks_usable']


def test_same_patch_new_verification_cannot_cross_review_fence(client, fixture_db, local_repo, monkeypatch):
    from sqlalchemy import update
    import ownstack.repository_cockpit as review
    iid, _, headers, _ = item(client)
    client.post(f'/v1/engineering/{iid}/verify', headers=headers)
    fake_executor(monkeypatch); assert work(fixture_db, local_repo)
    detail = client.get(f'/v1/engineering/{iid}', headers=headers).json()
    original = review.matching
    def replace_after_check(db, work_item):
        passed = original(db, work_item)
        payload = {**work_item.patch, '_verification_id': 'newer-same-patch-check'}
        db.execute(update(EngineeringItem).where(EngineeringItem.id == iid).values(patch=payload)
                   .execution_options(synchronize_session=False))
        return passed
    monkeypatch.setattr(review, 'matching', replace_after_check)
    result = client.post(f'/v1/engineering/{iid}/decide', headers=headers, json={
        'decision': 'accept_for_manual_release', 'patch_hash': detail['patch_hash'],
        'verification_id': detail['repository']['verification_id'], 'context_hash': detail['repository']['context_hash']})
    assert result.status_code == 409
    with fixture_db() as db:
        assert db.get(EngineeringItem, iid).human_decision is None


def test_disk_edit_cannot_be_stamped_as_loaded_code(monkeypatch):
    from fastapi import HTTPException
    import ownstack.repository_cockpit as review
    loaded = review.policy_hash()
    monkeypatch.setattr(review, '_read_policy_sources', lambda: 'different-disk-code')
    with pytest.raises(HTTPException) as rejected:
        review.policy_hash()
    assert rejected.value.status_code == 409
    assert 'restart' in rejected.value.detail
    assert loaded == review._LOADED_POLICY
