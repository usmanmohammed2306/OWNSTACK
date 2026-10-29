from datetime import datetime,timedelta,timezone
import pytest
from fastapi import HTTPException
from ownstack import authorization_clock as clock
from ownstack.models import RuntimePulse

@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv('OWNSTACK_ENFORCE_AUTH_CLOCK','true')
    monkeypatch.setattr(clock,'_anchor',None)
    point=[100.0];monkeypatch.setattr(clock.time,'monotonic',lambda:point[0])
    return point

def test_small_skew_never_lowers_persisted_authorization_time(fixture_db,enabled):
    at=datetime.now(timezone.utc)
    with fixture_db() as db:
        assert clock.authorization_time(db,at)==at;db.commit()
        assert clock.authorization_time(db,at-timedelta(milliseconds=200))==at;db.commit()
        assert clock.aware(db.get(RuntimePulse,'authorization-clock').touched_at)==at

@pytest.mark.parametrize('seconds',[-5,5])
def test_large_clock_jump_fails_closed_without_lowering_saved_floor(fixture_db,enabled,seconds):
    at=datetime.now(timezone.utc)
    with fixture_db() as db:
        clock.authorization_time(db,at);db.commit()
        with pytest.raises(HTTPException) as exc:clock.authorization_time(db,at+timedelta(seconds=seconds))
        assert exc.value.status_code==503;db.rollback()
        assert clock.aware(db.get(RuntimePulse,'authorization-clock').touched_at)==at

def test_process_restart_keeps_database_floor_and_does_not_reset_it(fixture_db,enabled,monkeypatch):
    at=datetime.now(timezone.utc)
    with fixture_db() as db:clock.authorization_time(db,at);db.commit()
    monkeypatch.setattr(clock,'_anchor',None)
    with fixture_db() as db:
        with pytest.raises(HTTPException):clock.authorization_time(db,at-timedelta(seconds=10))
        db.rollback();assert clock.aware(db.get(RuntimePulse,'authorization-clock').touched_at)==at

def test_normal_wall_and_monotonic_elapsed_advance_together(fixture_db,enabled):
    at=datetime.now(timezone.utc)
    with fixture_db() as db:
        clock.authorization_time(db,at);db.commit();enabled[0]+=20
        assert clock.authorization_time(db,at+timedelta(seconds=20))==at+timedelta(seconds=20)

def test_small_skew_cannot_resurrect_expired_access_in_native_review_or_host_read(client,fixture_db,enabled,monkeypatch):
    from test_api import create_and_propose
    from conftest import login
    from ownstack.models import Variation
    from sqlalchemy import select
    # Prepare an actual scoped grant through the HTTP/policy path before enabling
    # the clock fault. Fixture interpretation is explicitly synthetic, not a model.
    monkeypatch.setenv('OWNSTACK_ENFORCE_AUTH_CLOCK','false')
    admin,_,pid,hash_value=create_and_propose(client,fixture_db)
    approved=client.post('/v1/proposals/'+pid+'/approve',headers={**admin,'Idempotency-Key':'clock-grant'},
        json={'proposal_hash':hash_value}).json()
    floor=datetime.now(timezone.utc)
    with fixture_db() as db:
        grant=db.get(Variation,approved['variation_id'])
        grant.starts_at=floor-timedelta(hours=1);grant.expires_at=floor-timedelta(milliseconds=100)
        db.add(RuntimePulse(component='authorization-clock',touched_at=floor));db.commit()
    monkeypatch.setenv('OWNSTACK_ENFORCE_AUTH_CLOCK','true')
    monkeypatch.setattr('ownstack.api.utcnow',lambda:floor-timedelta(milliseconds=200))
    review=client.get('/v1/host/projects/atlas-project/access-review?viewer_id=atlas-contractor',headers=admin)
    assert review.status_code==200 and review.json()['allowed'] is False
    preview=client.get('/v1/variations/'+approved['variation_id']+'/revoke-preview',headers=admin)
    assert preview.status_code==200 and preview.json()['before']['allowed'] is False
    response=client.get('/v1/host/projects/atlas-project/documents/atlas-doc',headers=login(client,'atlas-contractor'))
    assert response.status_code==403
