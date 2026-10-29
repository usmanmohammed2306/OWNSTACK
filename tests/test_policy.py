from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
from ownstack.policy import Principal, can_read, validate_grant


def test_host_policy_is_tenant_project_viewer_and_time_scoped():
    now = datetime.now(timezone.utc)
    grant = SimpleNamespace(tenant_id="atlas", project_id="atlas-project", viewer_id="atlas-contractor",
                            state="active", starts_at=now - timedelta(minutes=1), expires_at=now + timedelta(hours=1))
    atlas = Principal("atlas-contractor", "atlas", "contractor")
    nova = Principal("nova-contractor", "nova", "contractor")
    assert can_read(atlas, "atlas", "atlas-project", [grant], now)
    assert not can_read(atlas, "atlas", "other-project", [grant], now)
    assert not can_read(nova, "atlas", "atlas-project", [grant], now)
    assert not can_read(atlas, "atlas", "atlas-project", [grant], now + timedelta(days=1))
    grant.state = "revoked"
    assert not can_read(atlas, "atlas", "atlas-project", [grant], now)


def test_capability_rejects_cross_tenant_or_long_duration():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError, match="cross_tenant"):
        validate_grant("atlas", "atlas", "nova", now + timedelta(days=1), now)
    with pytest.raises(ValueError, match="invalid_expiry"):
        validate_grant("atlas", "atlas", "atlas", now + timedelta(days=8), now)
