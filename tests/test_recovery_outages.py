"""Offline fault controls. These executor results are explicit test doubles."""
from datetime import timedelta

import pytest
from sqlalchemy import event, select, func
from sqlalchemy.exc import OperationalError

from ownstack import repository_recovery as recovery
from ownstack.models import Evidence, Event, InferenceBudget
from ownstack.service import utcnow
from test_repository_recovery import (Crash, crashed, controlled_host_identity, selected)  # noqa: F401
from test_repository_cockpit import local_repo, fake_executor, work  # noqa: F401


def test_three_reaper_crashes_become_honest_blocked_progress(client, fixture_db, local_repo, monkeypatch):
    iid, old, headers, _ = crashed(client, fixture_db, local_repo, monkeypatch)
    monkeypatch.setattr(recovery, 'process_dead', lambda pid: True)
    def die(*args): raise Crash()
    monkeypatch.setattr(recovery, 'cleanup', die)
    for _ in range(3):
        with pytest.raises(Crash): recovery.recover_once(fixture_db, local_repo)
        with fixture_db() as db:
            row = db.get(Evidence, old)
            row.result = {**row.result, 'recovery_until': recovery.stamp(utcnow()-timedelta(seconds=1))}
            db.commit()
    recovery.recover_once(fixture_db, local_repo)
    row = selected(client, iid, headers)['repository']['checks'][0]
    assert row['state'] == 'recovery_blocked' and row['error_code'] == 'RECOVERY_CLEANUP_LIMIT'
    for _ in range(12):
        result = client.post(f'/v1/engineering/{iid}/repository/retry', headers=headers, json={'verification_id': old})
        assert result.json()['id'] == old and result.json()['state'] == 'recovery_blocked'
    assert not recovery.recover_once(fixture_db, local_repo)


def test_database_outage_returns_retryable_private_status(client, fixture_db):
    from conftest import login
    headers = login(client, 'atlas-engineer')
    engine = fixture_db.kw['bind']
    def unavailable(*args):
        raise OperationalError('SELECT private_sql', {}, Exception('private database connection detail'))
    event.listen(engine, 'before_cursor_execute', unavailable)
    try:
        response = client.get('/v1/engineering', headers=headers)
        assert response.status_code == 503 and response.headers['Retry-After'] == '2'
        assert 'private' not in response.text and 'SELECT' not in response.text
    finally:
        event.remove(engine, 'before_cursor_execute', unavailable)
    assert client.get('/v1/engineering', headers=headers).status_code == 200


@pytest.mark.parametrize('outcome', ['before_commit', 'lost_ack_after_commit'])
def test_unknown_requeue_commit_reloads_durable_state_without_duplicate(client, fixture_db, local_repo, monkeypatch, outcome):
    from sqlalchemy.orm import Session, sessionmaker
    import ownstack.repository_cockpit as cockpit
    iid, old, headers, _ = crashed(client, fixture_db, local_repo, monkeypatch)
    monkeypatch.setattr(recovery, 'process_dead', lambda pid: True)
    original = cockpit.enqueue; armed = True
    def mark_commit(db, *args, **kwargs):
        nonlocal armed
        result = original(db, *args, **kwargs)
        if armed:db.info['commit_fault'] = True;armed = False
        return result
    monkeypatch.setattr(cockpit, 'enqueue', mark_commit)
    class FaultSession(Session):
        def commit(self):
            fault = self.info.pop('commit_fault', False)
            if fault and outcome == 'before_commit':
                raise OperationalError('COMMIT', {}, Exception('offline control'))
            super().commit()
            if fault:
                raise OperationalError('COMMIT', {}, Exception('lost acknowledgement control'))
    factory = sessionmaker(bind=fixture_db.kw['bind'], expire_on_commit=False, class_=FaultSession)
    with pytest.raises(OperationalError): recovery.recover_once(factory, local_repo)
    with fixture_db() as db:
        row = db.get(Evidence, old)
        assert row.result['state'] == ('recovering' if outcome == 'before_commit' else 'recovered')
        if outcome == 'before_commit':
            row.result = {**row.result, 'recovery_until': recovery.stamp(utcnow()-timedelta(seconds=1))}
        db.commit()
    assert recovery.recover_once(factory, local_repo) == (outcome == 'before_commit')
    new = selected(client, iid, headers)['repository']['verification_id']
    assert new != old
    for _ in range(12):
        assert client.post(f'/v1/engineering/{iid}/repository/retry', headers=headers,
                           json={'verification_id': old}).json()['id'] == new
    fake_executor(monkeypatch);assert work(fixture_db, local_repo)
    assert selected(client, iid, headers)['current_checks_usable']
    with fixture_db() as db:
        assert db.scalar(select(func.count()).select_from(Evidence).where(Evidence.kind=='repository_checks')) == 2
        assert db.scalar(select(func.count()).select_from(Event).where(Event.event_type=='repository.check_queued')) == 2
        assert db.get(InferenceBudget, 'global').reserved_calls == 0


@pytest.mark.parametrize('code,restarts', [(75, True), (-9, True), (70, False)])
def test_supervisor_retries_process_failure_at_bounded_rate(monkeypatch, code, restarts):
    import threading
    from types import SimpleNamespace
    import ownstack.repository_supervisor as supervisor
    monkeypatch.setenv('OWNSTACK_AI_MODE', 'off')
    stop=threading.Event();children=[];events=[]
    def spawn(command):
        child=SimpleNamespace(pid=100+len(children),returncode=code if not children else 0)
        child.poll=lambda:child.returncode
        children.append(child);return child
    monkeypatch.setattr(supervisor.subprocess,'Popen',spawn)
    monkeypatch.setattr(supervisor,'emit',lambda name,**fields:events.append((name,fields)))
    result=supervisor.supervise(['owned-test-command'],stop=stop,initial_delay=.001,max_delay=.002)
    assert len(children)==(2 if restarts else 1)
    assert result==(0 if restarts else 70)
    assert sum(name=='operator_retry_wait' for name,_ in events)==int(restarts)


@pytest.mark.parametrize('error,expected', [(OperationalError('safe',{},Exception('secret')),75),
    (__import__('sqlalchemy').exc.IntegrityError('safe',{},Exception('secret')),70)])
def test_worker_failure_status_is_private_and_distinguishes_logical_error(monkeypatch, capsys, local_repo, error, expected):
    import ownstack.repository_supervisor as supervisor
    import ownstack.repository_worker as worker
    monkeypatch.setenv('OWNSTACK_AI_MODE','off')
    def fail(*args):raise error
    monkeypatch.setattr(worker,'work_once',fail)
    assert supervisor.worker_loop(None,local_repo,local_repo/'oracle',local_repo/'cache')==expected
    assert 'secret' not in capsys.readouterr().out
