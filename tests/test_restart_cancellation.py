"""Forced schedules for saved cancellation and competing recovery ownership.

Executor/process-death controls here are explicit doubles. Actual process and
database-outage journeys are recorded separately by the local drill harness.
"""
from datetime import timedelta

import pytest
from sqlalchemy import event

from ownstack import repository_recovery as recovery
from ownstack.models import Evidence
from ownstack.service import utcnow
from test_repository_recovery import Crash, crashed, controlled_host_identity, selected  # noqa: F401
from test_repository_cockpit import local_repo  # noqa: F401


def test_cancel_preserves_recovery_claim_acquired_after_its_read(client, fixture_db, local_repo, monkeypatch):
    iid, old, headers, _ = crashed(client, fixture_db, local_repo, monkeypatch)
    monkeypatch.setattr(recovery, 'process_dead', lambda pid: True)
    def die_after_claim(*args):raise Crash()
    monkeypatch.setattr(recovery, 'cleanup', die_after_claim)
    engine=fixture_db.kw['bind'];triggered=False
    def acquire_between_read_and_cancel_write(connection,cursor,statement,parameters,context,many):
        nonlocal triggered
        if triggered or not statement.startswith('UPDATE engineering_items SET'):return
        triggered=True
        with pytest.raises(Crash):recovery.recover_once(fixture_db,local_repo)
    event.listen(engine,'before_cursor_execute',acquire_between_read_and_cancel_write)
    try:
        result=client.post(f'/v1/engineering/{iid}/repository/cancel',headers=headers,json={'verification_id':old})
        assert result.status_code==200,result.text
    finally:event.remove(engine,'before_cursor_execute',acquire_between_read_and_cancel_write)
    assert triggered
    with fixture_db() as db:
        data=db.get(Evidence,old).result
        assert data['state']=='canceled'
        assert data.get('recovery_token') and data.get('cleanup_attempts')==1
        assert not data['lease_closed']
    for _ in range(8):
        result=client.post(f'/v1/engineering/{iid}/repository/retry',headers=headers,json={'verification_id':old})
        assert result.json()['id']==old and result.json()['state']=='canceled'
    with fixture_db() as db:
        row=db.get(Evidence,old)
        row.result={**row.result,'recovery_until':recovery.stamp(utcnow()-timedelta(seconds=1))};db.commit()
    monkeypatch.setattr(recovery,'cleanup',lambda *args:{'cleanup_verified':True})
    assert recovery.recover_once(fixture_db,local_repo)
    current=selected(client,iid,headers)
    assert len(current['repository']['checks'])==1 and current['repository']['checks'][0]['state']=='canceled'
    with fixture_db() as db:assert db.get(Evidence,old).result['lease_closed']
