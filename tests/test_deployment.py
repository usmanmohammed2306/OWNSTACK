import json
import stat

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ownstack.auth import check_password
from ownstack.db import Base, make_engine
from ownstack.deployment import ACCOUNTS, initialize_fixture, prepare, read_account_file, validate_accounts, validate_domain, validate_observed_reservations
from ownstack.models import IdentityEvent, InferenceBudget, Tenant, User


def bundle():
    return {"version": 1, "passwords": {name: "synthetic-unique-passphrase-" + name for name in ACCOUNTS}}


@pytest.mark.parametrize("domain", ["https://ownstack.com", "example.com", "a.example.com", "a.example", "A.com", "a.com/", "a.com\n", "*.a.com", "127.0.0.1", "-a.com", "a..com", "a"*64+".com"])
def test_domain_rejects_templates_and_unsafe_env_values(domain):
    with pytest.raises(ValueError):
        validate_domain(domain)


def test_prepare_creates_private_independent_secrets_without_enabling_inference(tmp_path):
    destination = tmp_path / "private-launch"
    result = prepare("ownstack.usman.dev", destination, observed_reservations=32)
    assert result["deployed"] is False and "password" not in json.dumps(result)
    assert stat.S_IMODE(destination.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in destination.iterdir())
    payload = json.loads((destination / "accounts.json").read_text())
    passwords = validate_accounts(payload)
    assert len(set(passwords.values())) == 6
    content = (destination / ".env.production").read_text()
    assert "OWNSTACK_AI_MODE=off\n" in content and "OWNSTACK_MAX_LIVE_CALLS=0\n" in content
    assert "OWNSTACK_OBSERVED_RESERVATIONS=32\n" in content
    assert not any(password in content for password in passwords.values())
    original = content
    with pytest.raises(FileExistsError):
        prepare("ownstack.usman.dev", destination, observed_reservations=32)
    assert (destination / ".env.production").read_text() == original


def test_prepare_refuses_symlink_destination(tmp_path):
    real = tmp_path / "existing"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(FileExistsError):
        prepare("ownstack.usman.dev", linked, observed_reservations=32)
    assert list(real.iterdir()) == []


def test_private_account_reader_rejects_public_linked_large_and_nonregular_files(tmp_path):
    path = tmp_path / "accounts.json"
    path.write_text(json.dumps(bundle()))
    path.chmod(0o600)
    assert read_account_file(path) == bundle()["passwords"]
    path.chmod(0o644)
    with pytest.raises(ValueError, match="0600"):
        read_account_file(path)
    path.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(OSError):
        read_account_file(link)
    path.write_text("x"*16385)
    with pytest.raises(ValueError, match="0600"):
        read_account_file(path)
    fifo = tmp_path / "pipe"
    import os
    os.mkfifo(fifo, 0o600)
    with pytest.raises(ValueError, match="0600"):
        read_account_file(fifo)


@pytest.mark.parametrize("payload", [None, {}, {"version": True, "passwords": {}},
    {"version": 2, "passwords": {}}, {**bundle(), "extra": "no"},
    {"version": 1, "passwords": {name: "shared-password-for-everyone" for name in ACCOUNTS}},
    {"version": 1, "passwords": {**bundle()["passwords"], "atlas-admin": "short"}}])
def test_account_bundle_rejects_missing_weak_or_shared_credentials(payload):
    with pytest.raises(ValueError):
        validate_accounts(payload)


def test_initialization_is_atomic_scoped_and_does_not_renew_exhausted_budget(tmp_path):
    engine = make_engine("sqlite:///" + str(tmp_path / "new.db"))
    Base.metadata.create_all(engine)
    payload = bundle()
    with Session(engine) as db:
        initialize_fixture(db, payload, observed_reservations=32)
        assert db.get(InferenceBudget, "global").reserved_calls == 32
        assert db.scalar(select(func.count(User.id))) == 6
        assert db.scalar(select(func.count(IdentityEvent.id))) == 6
        for name, (tenant, role) in ACCOUNTS.items():
            user = db.get(User, name)
            assert (user.tenant_id, user.role) == (tenant, role)
            assert check_password(payload["passwords"][name], user.password_hash)
        db.rollback()
        assert db.scalar(select(func.count(Tenant.id))) == 0
        initialize_fixture(db, payload, observed_reservations=32)
        db.commit()
        old_hash = db.get(User, "atlas-admin").password_hash
        with pytest.raises(ValueError, match="empty"):
            initialize_fixture(db, payload, observed_reservations=32)
        db.rollback()
        assert db.get(User, "atlas-admin").password_hash == old_hash
        assert db.get(InferenceBudget, "global").reserved_calls == 32
    engine.dispose()


@pytest.mark.parametrize("initial,allowed", [(0, True), (1, False), (20, False), (40, False)])
def test_only_an_unused_migration_counter_can_be_carried_forward(tmp_path, initial, allowed):
    engine = make_engine("sqlite:///" + str(tmp_path / "existing.db"))
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(InferenceBudget(id="global", reserved_calls=initial))
        db.commit()
        if allowed:
            initialize_fixture(db, bundle(), observed_reservations=32)
            assert db.get(InferenceBudget, "global").reserved_calls == 32
            db.rollback()
        else:
            with pytest.raises(ValueError, match="empty"):
                initialize_fixture(db, bundle(), observed_reservations=32)
            assert db.scalar(select(func.count(User.id))) == 0
            assert db.get(InferenceBudget, "global").reserved_calls == initial
    engine.dispose()


@pytest.mark.parametrize("value", [0, 19, 41, True, None, "32"])
def test_observed_ledger_count_is_explicit_bounded_and_never_coerced(value):
    with pytest.raises(ValueError):
        validate_observed_reservations(value)
