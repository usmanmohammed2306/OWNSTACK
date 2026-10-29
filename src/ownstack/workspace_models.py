"""Reporting metadata and source-bound collaboration, never new permission roles."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from ownstack.db import Base
from ownstack.models import now


class OrganizationProfile(Base):
    __tablename__='organization_profiles'
    user_id:Mapped[str]=mapped_column(String(40),primary_key=True)
    tenant_id:Mapped[str]=mapped_column(ForeignKey('tenants.id'),index=True)
    title:Mapped[str]=mapped_column(String(80),default='Employee')
    manager_id:Mapped[str|None]=mapped_column(String(40),index=True)
    revision:Mapped[int]=mapped_column(Integer,default=1)
    updated_by:Mapped[str]=mapped_column(ForeignKey('users.id'))
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    __table_args__=(ForeignKeyConstraint(['tenant_id','user_id'],['users.tenant_id','users.id']),
        ForeignKeyConstraint(['tenant_id','manager_id'],['users.tenant_id','users.id']))


class OrganizationChange(Base):
    __tablename__='organization_changes'
    id:Mapped[str]=mapped_column(String(40),primary_key=True)
    tenant_id:Mapped[str]=mapped_column(ForeignKey('tenants.id'),index=True)
    actor_id:Mapped[str]=mapped_column(ForeignKey('users.id'))
    subject_id:Mapped[str]=mapped_column(ForeignKey('users.id'))
    payload:Mapped[dict]=mapped_column(JSON)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)


class RequestWorkspace(Base):
    __tablename__='request_workspaces'
    request_id:Mapped[str]=mapped_column(ForeignKey('change_requests.id'),primary_key=True)
    tenant_id:Mapped[str]=mapped_column(ForeignKey('tenants.id'),index=True)
    customer_text:Mapped[str]=mapped_column(Text)
    effective_text:Mapped[str|None]=mapped_column(Text)
    code_files:Mapped[dict]=mapped_column(JSON,default=dict)
    code_hash:Mapped[str|None]=mapped_column(String(64))


class RequestGuidance(Base):
    __tablename__='request_guidance'
    id:Mapped[str]=mapped_column(String(40),primary_key=True)
    tenant_id:Mapped[str]=mapped_column(ForeignKey('tenants.id'),index=True)
    request_id:Mapped[str]=mapped_column(ForeignKey('change_requests.id'),index=True)
    actor_id:Mapped[str]=mapped_column(ForeignKey('users.id'))
    request_revision:Mapped[int]=mapped_column(Integer)
    pattern_id:Mapped[str]=mapped_column(String(80))
    pattern_hash:Mapped[str]=mapped_column(String(64))
    decision:Mapped[str]=mapped_column(String(10))
    note:Mapped[str]=mapped_column(Text)
    snapshot:Mapped[dict]=mapped_column(JSON)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    __table_args__=(UniqueConstraint('request_id','request_revision'),)


class EngineeringComment(Base):
    __tablename__='engineering_comments'
    id:Mapped[str]=mapped_column(String(40),primary_key=True)
    tenant_id:Mapped[str]=mapped_column(ForeignKey('tenants.id'),index=True)
    item_id:Mapped[str]=mapped_column(ForeignKey('engineering_items.id'),index=True)
    request_id:Mapped[str]=mapped_column(ForeignKey('change_requests.id'))
    actor_id:Mapped[str]=mapped_column(ForeignKey('users.id'))
    patch_hash:Mapped[str]=mapped_column(String(64))
    request_revision:Mapped[int]=mapped_column(Integer)
    body:Mapped[str]=mapped_column(Text)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
