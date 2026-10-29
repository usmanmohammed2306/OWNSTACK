"""A vendor workspace owns customer accounts, never customer staff authority."""
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, ForeignKeyConstraint, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from ownstack.db import Base
from ownstack.models import now


class CustomerAccount(Base):
    __tablename__ = 'customer_accounts'
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey('tenants.id'), index=True)
    name: Mapped[str] = mapped_column(String(100))
    key: Mapped[str] = mapped_column(String(80))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (UniqueConstraint('tenant_id', 'id'), UniqueConstraint('tenant_id', 'key'))


class CustomerProject(Base):
    __tablename__ = 'customer_projects'
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey('tenants.id'), index=True)
    customer_id: Mapped[str] = mapped_column(String(40))
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (ForeignKeyConstraint(['tenant_id', 'customer_id'], ['customer_accounts.tenant_id', 'customer_accounts.id']),
                      UniqueConstraint('tenant_id', 'customer_id', 'project_id'))


class CustomerInvitation(Base):
    __tablename__ = 'customer_invitations'
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey('tenants.id'), index=True)
    customer_id: Mapped[str] = mapped_column(String(40))
    account_revision: Mapped[int] = mapped_column(Integer)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (ForeignKeyConstraint(['tenant_id', 'customer_id'], ['customer_accounts.tenant_id', 'customer_accounts.id']),)


class CustomerIdentity(Base):
    __tablename__ = 'customer_identities'
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey('tenants.id'), index=True)
    customer_id: Mapped[str] = mapped_column(String(40))
    username: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (ForeignKeyConstraint(['tenant_id', 'customer_id'], ['customer_accounts.tenant_id', 'customer_accounts.id']),)


class CustomerSession(Base):
    __tablename__ = 'customer_sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    identity_id: Mapped[str] = mapped_column(ForeignKey('customer_identities.id'), index=True)
    identity_revision: Mapped[int] = mapped_column(Integer)
    account_revision: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CustomerSubmission(Base):
    __tablename__ = 'customer_submissions'
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey('tenants.id'), index=True)
    customer_id: Mapped[str] = mapped_column(String(40))
    identity_id: Mapped[str] = mapped_column(ForeignKey('customer_identities.id'))
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'))
    text: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(80))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (ForeignKeyConstraint(['tenant_id', 'customer_id', 'project_id'],
                        ['customer_projects.tenant_id', 'customer_projects.customer_id', 'customer_projects.project_id']),
                      UniqueConstraint('identity_id', 'idempotency_key'))


class CustomerRequestLink(Base):
    __tablename__ = 'customer_request_links'
    request_id: Mapped[str] = mapped_column(ForeignKey('change_requests.id'), primary_key=True)
    submission_id: Mapped[str] = mapped_column(ForeignKey('customer_submissions.id'), unique=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey('tenants.id'))
    customer_id: Mapped[str] = mapped_column(String(40))
    account_revision: Mapped[int] = mapped_column(Integer)
    project_revision: Mapped[int] = mapped_column(Integer)
    __table_args__ = (ForeignKeyConstraint(['tenant_id', 'customer_id'], ['customer_accounts.tenant_id', 'customer_accounts.id']),)


class CustomerRequirementLink(Base):
    __tablename__ = 'customer_requirement_links'
    requirement_id: Mapped[str] = mapped_column(ForeignKey('release_requirements.id'), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey('tenants.id'))
    customer_id: Mapped[str] = mapped_column(String(40))
    account_revision: Mapped[int] = mapped_column(Integer)
    project_revision: Mapped[int] = mapped_column(Integer)
    __table_args__ = (ForeignKeyConstraint(['tenant_id', 'customer_id'], ['customer_accounts.tenant_id', 'customer_accounts.id']),)


class CustomerAudit(Base):
    __tablename__ = 'customer_audit'
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey('tenants.id'), index=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey('customer_accounts.id'))
    actor_id: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
