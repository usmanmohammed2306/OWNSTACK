"""Synthetic demonstration identities. Never use these passwords in production."""
from sqlalchemy import select
from ownstack.auth import password_hash
from ownstack.config import Settings
from ownstack.db import transaction
from ownstack.models import Contract, Document, Project, Tenant, User
from ownstack.policy import CONTRACT, digest


def seed() -> None:
    settings = Settings()
    settings.validate()
    with transaction() as db:
        if db.scalar(select(Tenant.id).limit(1)):
            if not db.get(Tenant, "platform"):
                db.add(Tenant(id="platform", name="OwnStack product team"))
                db.flush()
                db.add(User(id="platform-owner", tenant_id="platform", role="product_owner", password_hash=password_hash(settings.demo_password)))
            return
        db.add_all([Tenant(id="atlas", name="Atlas Industries"), Tenant(id="nova", name="Nova Labs"),
                    Tenant(id="platform", name="OwnStack product team")])
        db.flush()
        users = [
            ("atlas-admin", "atlas", "admin"),
            ("atlas-contractor", "atlas", "contractor"),
            ("atlas-engineer", "atlas", "engineer"),
            ("nova-admin", "nova", "admin"),
            ("nova-contractor", "nova", "contractor"),
            ("platform-owner", "platform", "product_owner"),
        ]
        db.add_all(User(id=name, tenant_id=tenant, role=role, password_hash=password_hash(settings.demo_password)) for name, tenant, role in users)
        db.add_all([
            Project(id="atlas-project", tenant_id="atlas", name="Project Atlas", revision=1),
            Project(id="nova-project", tenant_id="nova", name="Project Nova", revision=1),
        ])
        db.flush()
        db.add_all([
            Document(id="atlas-roadmap", tenant_id="atlas", project_id="atlas-project", title="Atlas roadmap", body="Atlas-only planning notes"),
            Document(id="atlas-budget", tenant_id="atlas", project_id="atlas-project", title="Atlas budget", body="Atlas-only synthetic budget"),
            Document(id="nova-roadmap", tenant_id="nova", project_id="nova-project", title="Nova roadmap", body="Nova-only planning notes"),
        ])
        db.add(Contract(id=CONTRACT["id"], version=1, manifest=CONTRACT, manifest_hash=digest(CONTRACT)))


if __name__ == "__main__":
    seed()
    print("Seeded Atlas/Nova synthetic fixture")
