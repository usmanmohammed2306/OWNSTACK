"""A schedule prediction cannot grant access, leak tenants or hide truncation."""
from datetime import datetime, timedelta, timezone
from importlib import import_module
from random import Random
from types import SimpleNamespace
import pytest
from sqlalchemy import func, select
from conftest import login
from test_access_review import approved_grant, URL
from ownstack.access_forecast import access_forecast, MAX_FORECAST_GRANTS
from ownstack.host_access import host_read_decision
from ownstack.models import Attempt, Event, HostObservation, InferenceBudget, Outbox, Project, Proposal, User, Variation
from ownstack.policy import Principal, aware, read_decision

AT = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)


def clone_grant(db, original, name, start, end, **overrides):
    """Explicit synthetic schedule; ordinary approval rejects redundant grants."""
    proposal = db.get(Proposal, original.proposal_id)
    attempt = db.get(Attempt, proposal.attempt_id)
    attrs = {c.name: getattr(attempt, c.name) for c in Attempt.__table__.columns}
    db.add(Attempt(**{**attrs, 'id': name + '-attempt', 'number': 1000 + int(name.split('-')[-1])}))
    db.flush()
    attrs = {c.name: getattr(proposal, c.name) for c in Proposal.__table__.columns}
    db.add(Proposal(**{**attrs, 'id': name + '-proposal', 'attempt_id': name + '-attempt'}))
    db.flush()
    row = Variation(id=name, tenant_id=original.tenant_id, project_id=original.project_id,
                    viewer_id=original.viewer_id, proposal_id=name + '-proposal', state='active',
                    starts_at=AT + timedelta(hours=start), expires_at=AT + timedelta(hours=end))
    for key, value in overrides.items(): setattr(row, key, value)
    db.add(row)
    return row


@pytest.mark.parametrize('intervals,next_hour,allowed', [
    ([(-1, 2)], 2, False),
    ([(-1, 2), (1, 4)], 4, False),
    ([(-1, 2), (2, 4)], 4, False),
    ([(-1, 2), (3, 4)], 2, False),
    ([(2, 3)], 2, True),
    ([(0, 2)], 2, False),
    ([(-2, 0)], None, None),
    ([(168, 169)], 168, True),
    ([(-1, 169)], None, None),
    ([(169, 170)], None, None),
])
def test_exact_boundaries_and_overlaps_match_host_policy(client, fixture_db, monkeypatch, intervals, next_hour, allowed):
    admin, grant = approved_grant(client, fixture_db)
    with fixture_db() as db:
        original = db.get(Variation, grant)
        original.state = 'revoked'
        for index, (start, end) in enumerate(intervals):
            clone_grant(db, original, f'schedule-{index}', start, end)
        db.commit()
    monkeypatch.setattr(import_module('ownstack.api'), 'utcnow', lambda: AT)
    result = client.get(URL, params={'viewer_id': 'atlas-contractor'}, headers=admin).json()
    forecast = result['forecast']
    assert aware(datetime.fromisoformat(forecast['through'])) == AT + timedelta(days=7)
    with fixture_db() as db:
        principal = Principal('atlas-contractor', 'atlas', 'contractor')
        assert result['allowed'] == host_read_decision(db, principal, 'atlas', 'atlas-project', AT).allowed
        if next_hour is None:
            assert forecast['status'] == 'no_scheduled_change' and forecast['next_change'] is None
        else:
            boundary = AT + timedelta(hours=next_hour)
            assert forecast['status'] == 'predicted_change'
            assert forecast['next_change'] == {'at': boundary.isoformat(), 'allowed': allowed}
            assert host_read_decision(db, principal, 'atlas', 'atlas-project', boundary).allowed == allowed
            assert host_read_decision(db, principal, 'atlas', 'atlas-project', boundary - timedelta(microseconds=1)).allowed != allowed


def test_forecast_ignores_revoked_expired_wrong_scope_and_malformed_intervals(client, fixture_db, monkeypatch):
    admin, grant = approved_grant(client, fixture_db)
    with fixture_db() as db:
        original = db.get(Variation, grant)
        original.starts_at, original.expires_at = AT - timedelta(hours=1), AT + timedelta(hours=2)
        for index, attrs in enumerate([{'state': 'revoked'}, {'tenant_id': 'nova'},
                                      {'project_id': 'nova-project'}, {'viewer_id': 'atlas-admin'}]):
            clone_grant(db, original, f'noise-{index}', -1, 6, **attrs)
        clone_grant(db, original, 'noise-4', -2, 0)
        clone_grant(db, original, 'noise-5', 4, 3)
        db.commit()
    monkeypatch.setattr(import_module('ownstack.api'), 'utcnow', lambda: AT)
    forecast = client.get(URL, params={'viewer_id': 'atlas-contractor'}, headers=admin).json()['forecast']
    assert forecast['next_change'] == {'at': (AT + timedelta(hours=2)).isoformat(), 'allowed': False}


def test_cap_withholds_incomplete_schedule_but_preserves_current_read(client, fixture_db, monkeypatch):
    admin, grant = approved_grant(client, fixture_db)
    with fixture_db() as db:
        original = db.get(Variation, grant)
        original.starts_at, original.expires_at = AT - timedelta(hours=1), AT + timedelta(hours=1)
        for index in range(MAX_FORECAST_GRANTS): clone_grant(db, original, f'cap-{index}', -1, 2)
        db.commit()
    monkeypatch.setattr(import_module('ownstack.api'), 'utcnow', lambda: AT)
    with fixture_db() as db:
        statements = []
        from sqlalchemy import event
        def capture(conn, cursor, sql, parameters, context, many): statements.append((sql, parameters))
        event.listen(db.bind, 'before_cursor_execute', capture)
        try:
            current, forecast = access_forecast(db, db.get(User, 'atlas-contractor'), db.get(Project, 'atlas-project'), AT)
        finally: event.remove(db.bind, 'before_cursor_execute', capture)
        assert current.allowed and forecast['status'] == 'unavailable' and forecast['next_change'] is None
        selects = [(sql, params) for sql, params in statements if 'FROM variations' in sql]
        assert len(selects) == 2
        assert all('LIMIT' in sql for sql, params in selects)
        assert selects[0][1][-2] == MAX_FORECAST_GRANTS + 1
    # Dropping one row below the cap must restore an actual, complete forecast.
    with fixture_db() as db:
        db.get(Variation, 'cap-0').state = 'revoked'
        db.commit()
    response = client.get(URL, params={'viewer_id': 'atlas-contractor'}, headers=admin).json()
    assert response['forecast']['status'] == 'predicted_change'
    assert response['forecast']['next_change']['at'] == (AT + timedelta(hours=2)).isoformat()


@pytest.mark.parametrize('role,enabled,expected', [('admin', True, True), ('member', True, True),
    ('engineer', True, True), ('contractor', False, False), ('unknown', True, False)])
def test_roles_and_disabled_accounts_need_no_schedule_lookup(role, enabled, expected):
    class NoQuery:
        def scalars(self, _): raise AssertionError('Unnecessary grant lookup')
        def scalar(self,statement):
            assert 'team_memberships' in str(statement)
            return 'atlas-project'  # Explicitly authorized team-scope fixture.
    current, forecast = access_forecast(NoQuery(), SimpleNamespace(id='user', tenant_id='atlas', role=role, enabled=enabled),
                                      SimpleNamespace(id='atlas-project', tenant_id='atlas'), AT)
    assert current.allowed is expected
    assert forecast['status'] == 'no_scheduled_change' and forecast['next_change'] is None


def test_forecast_is_read_only_tenant_scoped_and_recomputed_after_revoke(client, fixture_db, monkeypatch):
    admin, grant = approved_grant(client, fixture_db)
    with fixture_db() as db:
        row = db.get(Variation, grant)
        row.starts_at, row.expires_at = AT - timedelta(hours=1), AT + timedelta(hours=2)
        db.get(InferenceBudget, 'global').reserved_calls = 10
        db.commit()
        models = (Attempt, Event, HostObservation, Outbox, Proposal, Variation)
        before = [db.scalar(select(func.count()).select_from(m)) for m in models]
    monkeypatch.setattr(import_module('ownstack.api'), 'utcnow', lambda: AT)
    response = client.get(URL, params={'viewer_id': 'atlas-contractor'}, headers=admin)
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    assert response.json()['forecast']['status'] == 'predicted_change'
    assert 'atlas secret' not in response.text and 'nova' not in response.text
    assert client.get(URL, params={'viewer_id': 'nova-contractor'}, headers=admin).status_code == 404
    assert client.get(URL, params={'viewer_id': 'atlas-contractor'}, headers=login(client, 'nova-admin')).status_code == 404
    with fixture_db() as db:
        assert before == [db.scalar(select(func.count()).select_from(m)) for m in models]
        assert db.get(InferenceBudget, 'global').reserved_calls == 10
    assert client.post(f'/v1/variations/{grant}/revoke', headers={**admin, 'Idempotency-Key': 'forecast-revoke'}).status_code == 200
    result = client.get(URL, params={'viewer_id': 'atlas-contractor'}, headers=admin).json()
    assert not result['allowed'] and result['forecast']['next_change'] is None


def test_seeded_forecasts_agree_with_all_finite_policy_boundaries():
    rng = Random(20261023)
    principal = Principal('viewer', 'atlas', 'contractor')
    viewer = SimpleNamespace(id='viewer', tenant_id='atlas', role='contractor', enabled=True)
    project = SimpleNamespace(id='atlas-project', tenant_id='atlas')
    for case in range(120):
        rows = []
        for index in range(rng.randrange(15)):
            start = rng.randrange(-5, 170)
            rows.append(SimpleNamespace(id=str(index), tenant_id='atlas', project_id='atlas-project', viewer_id='viewer',
                state='active', starts_at=AT + timedelta(hours=start), expires_at=AT + timedelta(hours=start + rng.randrange(1, 10))))
        rows.sort(key=lambda row: row.id)
        rows = [row for row in rows if row.expires_at > AT and row.starts_at <= AT + timedelta(days=7)]
        class SavedRows:
            def scalars(self, _): return SimpleNamespace(all=lambda: rows)
        current, forecast = access_forecast(SavedRows(), viewer, project, AT)
        assert current == read_decision(principal, 'atlas', project.id, rows, AT)
        boundaries = sorted({t for row in rows for t in (row.starts_at, row.expires_at) if AT < t <= AT + timedelta(days=7)})
        expected = next((t for t in boundaries if read_decision(principal, 'atlas', project.id, rows, t).allowed != current.allowed), None)
        if expected is None: assert forecast['next_change'] is None, case
        else: assert forecast['next_change']['at'] == expected.isoformat(), case
