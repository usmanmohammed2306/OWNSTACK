"""SQL candidate selection must match exhaustive policy, not just allow cases."""
from datetime import datetime, timedelta, timezone
from random import Random
import pytest
from sqlalchemy import create_engine, event, insert, select
from sqlalchemy.orm import Session
from ownstack.host_access import host_read_decision, candidate_query
from ownstack.models import Variation
from ownstack.policy import Principal, read_decision

AT = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)


@pytest.fixture
def grants():
    engine = create_engine("sqlite://")
    # Isolated query fixture only, not an application database or live-call ledger.
    Variation.__table__.create(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def row(identifier="grant", **changes):
    return Variation(**{**dict(id=identifier, tenant_id="atlas", project_id="atlas-project",
        viewer_id="contractor", proposal_id="proposal-" + identifier, state="active",
        starts_at=AT - timedelta(hours=1), expires_at=AT + timedelta(hours=1), revision=1), **changes})


CASES = [{}, {"state": "revoked"}, {"expires_at": AT},
         {"expires_at": AT - timedelta(microseconds=1)}, {"starts_at": AT},
         {"starts_at": AT + timedelta(microseconds=1)}, {"viewer_id": "other"},
         {"tenant_id": "nova"}, {"project_id": "nova-project"}]


@pytest.mark.parametrize("changes", CASES)
@pytest.mark.parametrize("role", ["contractor", "admin", "member", "engineer", "product_owner", "unknown"])
def test_candidate_query_matches_exhaustive_policy(grants, changes, role):
    grants.add_all([row("a-first", **changes), row("z-second")])
    grants.commit()
    principal = Principal("contractor", "atlas", role)
    broad = grants.scalars(select(Variation).where(Variation.tenant_id == "atlas",
        Variation.project_id == "atlas-project").order_by(Variation.id)).all()
    assert host_read_decision(grants, principal, "atlas", "atlas-project", AT) == read_decision(
        principal, "atlas", "atlas-project", broad, AT)


def test_no_grant_query_for_roles_or_cross_tenant(grants):
    statements = []
    event.listen(grants.bind, "before_cursor_execute", lambda *args: statements.append(args[2]))
    for role in ["admin", "member", "engineer", "product_owner", "unknown", "contractor"]:
        principal = Principal("contractor", "nova", role)
        assert not host_read_decision(grants, principal, "atlas", "atlas-project", AT).allowed
    assert host_read_decision(grants, Principal("admin", "atlas", "admin"), "atlas", "atlas-project", AT).allowed
    assert statements == []


def test_revoke_and_expiry_are_not_cached(grants):
    grant = row()
    grants.add(grant)
    grants.commit()
    principal = Principal("contractor", "atlas", "contractor")
    assert host_read_decision(grants, principal, "atlas", "atlas-project", AT).allowed
    assert not host_read_decision(grants, principal, "atlas", "atlas-project", grant.expires_at).allowed
    grant.state = "revoked"
    grants.commit()
    assert not host_read_decision(grants, principal, "atlas", "atlas-project", AT).allowed


def test_seeded_policy_parity_across_500_reads(grants):
    random = Random(20261010)
    for index in range(120):
        grants.add(row(f"grant-{index:04d}", tenant_id=random.choice(["atlas", "nova"]),
            project_id=random.choice(["atlas-project", "nova-project"]),
            viewer_id=random.choice(["contractor", "other"]), state=random.choice(["active", "revoked"]),
            starts_at=AT + timedelta(seconds=random.randint(-3, 3)),
            expires_at=AT + timedelta(seconds=random.randint(-3, 3))))
    grants.commit()
    for _ in range(500):
        principal = Principal(random.choice(["contractor", "other"]), random.choice(["atlas", "nova"]),
            random.choice(["contractor", "admin", "engineer", "unknown"]))
        project, tenant = random.choice([("atlas-project", "atlas"), ("nova-project", "nova")])
        at = AT + timedelta(seconds=random.randint(-5, 5))
        broad = grants.scalars(select(Variation).where(Variation.tenant_id == principal.tenant_id,
            Variation.project_id == project).order_by(Variation.id)).all()
        assert host_read_decision(grants, principal, tenant, project, at) == read_decision(
            principal, tenant, project, broad, at)


def test_large_history_materializes_only_first_valid_candidate(grants):
    history = [dict(id=f"old-{i:05d}", tenant_id="atlas", project_id="atlas-project",
        viewer_id="contractor", proposal_id=f"proposal-{i}", state="revoked",
        starts_at=AT - timedelta(hours=2), expires_at=AT + timedelta(hours=1), revision=1) for i in range(10000)]
    grants.execute(insert(Variation), history)
    grants.add_all([row("a-valid"), row("z-valid")])
    grants.commit()
    candidates = grants.scalars(candidate_query(Principal("contractor", "atlas", "contractor"), "atlas-project", AT)).all()
    assert len(candidates) == 1 and candidates[0].id == "a-valid"
