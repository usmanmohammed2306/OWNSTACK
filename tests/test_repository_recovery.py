"""Crash/retry control tests with an explicit fake executor, never issue evidence.

Real process, heartbeat, Docker cleanup and PostgreSQL schedules are exercised
separately by the retained local campaign. No test here calls a provider.
"""
from copy import deepcopy
from datetime import timedelta
import json

import pytest
from sqlalchemy import select, func

from ownstack.models import EngineeringItem, Evidence, InferenceBudget, User
from ownstack import repository_recovery as recovery
from ownstack.repository_worker import discard
from ownstack.service import utcnow
from test_repository_cockpit import item, fake_executor, work, local_repo  # noqa: F401


class Crash(BaseException):
    pass


@pytest.fixture(autouse=True)
def controlled_host_identity(monkeypatch):
    # Explicit control: the desktop sandbox cannot read kernel boot metadata.
    monkeypatch.setattr(recovery, 'host_identity', lambda directory: 'unit-host-boot-artifact-root')


def crashed(client, factory, directory, monkeypatch):
    iid, rid, headers, patch = item(client)
    first = client.post(f'/v1/engineering/{iid}/verify', headers=headers).json()
    def die():
        raise Crash()
    fake_executor(monkeypatch, during=die)
    with pytest.raises(Crash):
        work(factory, directory)
    with factory() as db:
        row = db.get(Evidence, first['id'])
        assert row.result['state'] == 'running' and not row.result['lease_closed']
        row.result = {**row.result, 'lease_until': recovery.stamp(utcnow() - timedelta(seconds=10))}
        db.commit()
    return iid, first['id'], headers, patch


def selected(client, iid, headers):
    return client.get(f'/v1/engineering/{iid}', headers=headers).json()


def test_dead_owner_recovers_once_then_exact_review(client, fixture_db, local_repo, monkeypatch):
    iid, old, headers, _ = crashed(client, fixture_db, local_repo, monkeypatch)
    monkeypatch.setattr(recovery, 'process_dead', lambda pid: True)
    assert recovery.recover_once(fixture_db, local_repo)
    detail = selected(client, iid, headers)
    checks = detail['repository']['checks']; new = checks[-1]['id']
    assert [(r['state'], r['recovery_count']) for r in checks] == [('recovered', 0), ('queued', 1)]
    assert checks[0]['cleanup_verified'] and checks[0]['replacement_check_id'] == new != old
    assert 'lease_pid' not in checks[0] and 'lease_host' not in checks[0]
    for _ in range(5):
        assert client.post(f'/v1/engineering/{iid}/verify', headers=headers).json()['id'] == new
        assert client.post(f'/v1/engineering/{iid}/repository/retry', headers=headers,
                           json={'verification_id': old}).json()['id'] == new
    assert not recovery.recover_once(fixture_db, local_repo)
    # A late owner cannot retire the recovered operation or the selected retry.
    with fixture_db() as db:
        discard(db, db.get(EngineeringItem, iid), db.get(Evidence, old),
                event_type='repository.late_result_discarded', report={'passed': True}, owner='old')
        db.commit()
    assert selected(client, iid, headers)['status'] == 'checking'
    with fixture_db() as db:
        assert db.get(Evidence, old).result['state'] == 'recovered'
        assert db.get(Evidence, old).result['late_result_saved']
    fake_executor(monkeypatch)
    assert work(fixture_db, local_repo)
    detail = selected(client, iid, headers)
    assert detail['current_checks_usable']
    body = {'decision': 'accept_for_manual_release', 'patch_hash': detail['patch_hash'],
            'verification_id': old, 'context_hash': detail['repository']['context_hash']}
    assert client.post(f'/v1/engineering/{iid}/decide', headers=headers, json=body).status_code == 409
    body['verification_id'] = new
    assert client.post(f'/v1/engineering/{iid}/decide', headers=headers, json=body).status_code == 200
    assert client.get(f'/v1/engineering/{iid}/artifact', headers=headers).json()['release_state'] == 'not_deployed'
    with fixture_db() as db:
        assert db.get(InferenceBudget, 'global').reserved_calls == 0


@pytest.mark.parametrize('reason', ['alive', 'another_host', 'not_expired', 'legacy'])
def test_expiry_alone_or_missing_ownership_never_steals(client, fixture_db, local_repo, monkeypatch, reason):
    iid, old, headers, _ = crashed(client, fixture_db, local_repo, monkeypatch)
    monkeypatch.setattr(recovery, 'process_dead', lambda pid: reason != 'alive')
    with fixture_db() as db:
        row = db.get(Evidence, old); data = deepcopy(row.result)
        if reason == 'another_host': data['lease_host'] = 'different-boot'
        if reason == 'not_expired': data['lease_until'] = recovery.stamp(utcnow() + timedelta(seconds=30))
        if reason == 'legacy': data.pop('lease_owner')
        row.result = data; db.commit()
    assert not recovery.recover_once(fixture_db, local_repo)
    assert selected(client, iid, headers)['repository']['verification_id'] == old


@pytest.mark.parametrize('change', ['cancel', 'takeover', 'revoke', 'context'])
def test_changes_during_cleanup_win_and_no_auto_release(client, fixture_db, local_repo, monkeypatch, change):
    iid, old, headers, patch = crashed(client, fixture_db, local_repo, monkeypatch)
    monkeypatch.setattr(recovery, 'process_dead', lambda pid: True)
    def clean(directory, check_id):
        # Duplicate deliveries see the saved recovery ID, never dispatch.
        assert client.post(f'/v1/engineering/{iid}/verify', headers=headers).json()['id'] == old
        assert not recovery.recover_once(fixture_db, local_repo)
        if change == 'cancel':
            assert client.post(f'/v1/engineering/{iid}/repository/cancel', headers=headers,
                               json={'verification_id': old}).status_code == 200
        elif change == 'takeover':
            assert client.post(f'/v1/engineering/{iid}/decide', headers=headers,
                json={'decision': 'take_over', 'patch_hash': selected(client, iid, headers)['patch_hash']}).status_code == 200
        else:
            with fixture_db() as db:
                if change == 'revoke':
                    db.get(User, 'atlas-engineer').enabled = False
                else:
                    target = db.get(EngineeringItem, iid)
                    target.patch = {**target.patch, '_candidate_origin': 'human'}
                db.commit()
        return {'cleanup_verified': True}
    monkeypatch.setattr(recovery, 'cleanup', clean)
    assert recovery.recover_once(fixture_db, local_repo)
    with fixture_db() as db:
        row = db.get(Evidence, old)
        assert row.result['state'] == ('canceled' if change in {'cancel', 'takeover'} else 'blocked')
        assert row.result['lease_closed'] and not row.result['accepted']
        assert db.scalar(select(func.count()).select_from(Evidence).where(Evidence.kind == 'repository_checks')) == 1


def test_cleanup_outage_blocks_duplicates_and_patch_until_verified(client, fixture_db, local_repo, monkeypatch):
    iid, old, headers, patch = crashed(client, fixture_db, local_repo, monkeypatch)
    monkeypatch.setattr(recovery, 'process_dead', lambda pid: True)
    def unavailable(*args): raise OSError('offline Docker fixture')
    monkeypatch.setattr(recovery, 'cleanup', unavailable)
    assert recovery.recover_once(fixture_db, local_repo)
    detail = selected(client, iid, headers)
    assert detail['status'] == 'checking' and detail['repository']['checks'][0]['state'] == 'recovery_blocked'
    for _ in range(4):
        result = client.post(f'/v1/engineering/{iid}/repository/retry', headers=headers, json={'verification_id': old})
        assert result.json()['id'] == old and result.json()['state'] == 'recovery_blocked'
    assert not recovery.recover_once(fixture_db, local_repo)  # Backoff, no retry storm.
    assert client.post(f'/v1/engineering/{iid}/repository/cancel', headers=headers, json={'verification_id': old}).status_code == 200
    assert client.post(f'/v1/engineering/{iid}/repository/retry', headers=headers, json={'verification_id': old}).json()['id'] == old
    assert client.post(f'/v1/engineering/{iid}/manual-patch', headers=headers,
                       json={'patch': patch, 'candidate_origin': 'human'}).status_code == 409
    monkeypatch.setattr(recovery, 'cleanup', lambda *args: {'cleanup_verified': True})
    assert recovery.recover_once(fixture_db, local_repo)
    assert selected(client, iid, headers)['repository']['checks'][0]['state'] == 'canceled'
    new = client.post(f'/v1/engineering/{iid}/repository/retry', headers=headers, json={'verification_id': old}).json()
    assert new['id'] != old


def test_crashed_reaper_is_resumable_and_retries_are_bounded(client, fixture_db, local_repo, monkeypatch):
    iid, old, headers, _ = crashed(client, fixture_db, local_repo, monkeypatch)
    monkeypatch.setattr(recovery, 'process_dead', lambda pid: True)
    def die(*args): raise Crash()
    monkeypatch.setattr(recovery, 'cleanup', die)
    with pytest.raises(Crash): recovery.recover_once(fixture_db, local_repo)
    assert not recovery.recover_once(fixture_db, local_repo)
    with fixture_db() as db:
        row = db.get(Evidence, old)
        row.result = {**row.result, 'recovery_until': recovery.stamp(utcnow() - timedelta(seconds=1))}
        db.commit()
    monkeypatch.setattr(recovery, 'cleanup', lambda *args: {'cleanup_verified': True})
    assert recovery.recover_once(fixture_db, local_repo)
    for count in (1, 2):
        new = selected(client, iid, headers)['repository']['verification_id']
        fake_executor(monkeypatch, during=lambda: (_ for _ in ()).throw(Crash()))
        with pytest.raises(Crash): work(fixture_db, local_repo)
        with fixture_db() as db:
            row = db.get(Evidence, new)
            row.result = {**row.result, 'lease_until': recovery.stamp(utcnow() - timedelta(seconds=1))}
            db.commit()
        assert recovery.recover_once(fixture_db, local_repo)
    detail = selected(client, iid, headers)
    assert detail['status'] == 'checks_failed'
    assert [r['state'] for r in detail['repository']['checks']] == ['recovered', 'recovered', 'blocked']
    assert detail['repository']['checks'][-1]['error_code'] == 'RECOVERY_LIMIT'


def test_heartbeat_cannot_revive_an_expired_or_replaced_lease(client, fixture_db, local_repo, monkeypatch):
    _, old, _, _ = crashed(client, fixture_db, local_repo, monkeypatch)
    with fixture_db() as db: owner = db.get(Evidence, old).result['lease_owner']
    assert not recovery.renew(fixture_db, old, owner)
    assert not recovery.renew(fixture_db, old, 'another-owner')
    with fixture_db() as db:
        row = db.get(Evidence, old)
        row.result = {**row.result, 'lease_until': recovery.stamp(utcnow() + timedelta(seconds=10))}
        db.commit()
    assert recovery.renew(fixture_db, old, owner)


def test_time_passing_between_heartbeat_reads_cannot_revive_lease(client, fixture_db, local_repo, monkeypatch):
    _, old, _, _ = crashed(client, fixture_db, local_repo, monkeypatch)
    instant=utcnow()
    with fixture_db() as db:
        row=db.get(Evidence,old);owner=row.result['lease_owner']
        row.result={**row.result,'lease_until':recovery.stamp(instant+timedelta(seconds=10))};db.commit()
    times=iter([instant,instant+timedelta(seconds=11)])
    monkeypatch.setattr(recovery,'now',lambda db:next(times))
    assert not recovery.renew(fixture_db,old,owner)


def test_all_tenant_views_redact_operator_tokens(client, fixture_db, local_repo, monkeypatch):
    iid, old, headers, _ = crashed(client, fixture_db, local_repo, monkeypatch)
    with fixture_db() as db:
        row=db.get(Evidence,old);rid=row.request_id
        row.result={**row.result,'recovery_token':'private-token','recovery_pid':12345};db.commit()
    views=[selected(client,iid,headers)['repository']['checks'][0],
        next(r for r in client.get(f'/v1/evidence/{rid}',headers=headers).json() if r['id']==old)['result'],
        next(r for r in client.get(f'/v1/requests/{rid}/proof',headers=headers).json()['payload']['evidence'] if r['id']==old)['result']]
    for view in views:
        assert not {'lease_owner','lease_pid','lease_host','recovery_token','recovery_pid'} & view.keys()
    with fixture_db() as db:assert db.get(Evidence,old).result['recovery_token']=='private-token'


def test_ambiguous_or_symlink_cleanup_is_fail_closed(local_repo, tmp_path):
    from uuid import uuid4
    ident = str(uuid4()); root = local_repo / ident / 'execution' / 'baseline'
    root.mkdir(parents=True, mode=0o700)
    path = root / 'invocation.json'
    path.write_text(json.dumps({'container': 'not-owned', 'argv': ['docker', 'run']})); path.chmod(0o600)
    with pytest.raises(ValueError): recovery.cleanup(local_repo, ident)
    path.unlink(); path.symlink_to(tmp_path / 'outside')
    (tmp_path / 'outside').write_text('{}')
    with pytest.raises(ValueError): recovery.cleanup(local_repo, ident)


def test_unavailable_boot_identity_disables_takeover(client, fixture_db, local_repo, monkeypatch):
    iid, old, headers, _ = crashed(client, fixture_db, local_repo, monkeypatch)
    monkeypatch.setattr(recovery, 'host_identity', lambda directory: None)
    monkeypatch.setattr(recovery, 'process_dead', lambda pid: True)
    assert not recovery.recover_once(fixture_db, local_repo)
    assert selected(client, iid, headers)['repository']['verification_id'] == old


@pytest.mark.parametrize('seconds', ['0', '4', '61', 'invalid'])
def test_invalid_lease_configuration_fails_closed(monkeypatch, seconds):
    monkeypatch.setenv('OWNSTACK_REPOSITORY_LEASE_SECONDS', seconds)
    with pytest.raises(ValueError): recovery.lease_seconds()


@pytest.mark.parametrize('fault', ['missing_child', 'wrong_child', 'wrong_image', 'wrong_mount', 'docker_outage', 'verified_absent'])
def test_cleanup_requires_exact_owned_process_and_container(local_repo, monkeypatch, fault):
    from uuid import uuid4
    ident=str(uuid4());root=local_repo/ident/'execution/baseline';root.mkdir(parents=True,mode=0o700)
    name='ownstack-repo-'+uuid4().hex;image='sha256:'+'a'*64
    command=['docker','run','--name',name,image]
    for file,data in [('invocation.json',{'container':name,'argv':command}),
                      ('process.json',{'pid':22222,'pgid':22222,'argv':command})]:
        path=root/file;path.write_text(json.dumps(data));path.chmod(0o600)
    monkeypatch.setattr(recovery,'process_dead',lambda pid:True)
    if fault=='missing_child':(root/'process.json').unlink()
    if fault=='wrong_child':
        (root/'process.json').write_text(json.dumps({'pid':1,'pgid':1,'argv':command}))
    def inspect(name):
        if fault=='docker_outage':raise OSError('Docker unavailable')
        if fault=='verified_absent':return None
        return {'Image':'sha256:'+'b'*64 if fault=='wrong_image' else image,
            'HostConfig':{'NetworkMode':'none','ReadonlyRootfs':True},
            'Mounts':[{'Source':'/wrong','Destination':'/repo','RW':False}]}
    monkeypatch.setattr(recovery,'_inspect',inspect)
    if fault=='verified_absent':
        assert recovery.cleanup(local_repo,ident)['cleanup_verified']
    else:
        with pytest.raises((ValueError,OSError)):recovery.cleanup(local_repo,ident)


@pytest.mark.parametrize('message', [b'error: no such object: ownstack-repo-abc',
    b'Error: No such container: ownstack-repo-abc', b'Cannot connect to the Docker daemon'])
def test_docker_absence_is_case_insensitive_but_outage_is_not_absence(monkeypatch, message):
    from types import SimpleNamespace
    monkeypatch.setattr(recovery.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=1,stderr=message,stdout=b'[]'))
    if b'no such' in message.lower():assert recovery._inspect('ownstack-repo-abc') is None
    else:
        with pytest.raises(RuntimeError):recovery._inspect('ownstack-repo-abc')
