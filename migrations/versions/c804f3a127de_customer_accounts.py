"""Customer onboarding, one-use invitations and explicit AI entitlement.

No inference ledger, existing password or session is reset by this migration.
"""
from alembic import op
import sqlalchemy as sa

revision = "c804f3a127de"
down_revision = "b73e2c91d406"
branch_labels = depends_on = None


def upgrade():
    op.add_column("tenants", sa.Column("ai_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("users", sa.Column("display_name", sa.String(100), nullable=True))
    op.create_table("workspace_invitations",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("tenant_id", sa.String(40), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("issuer_id", sa.String(40), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.Column("used_by", sa.String(40), sa.ForeignKey("users.id")),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_workspace_invitations_tenant_id", "workspace_invitations", ["tenant_id"])


def downgrade():
    op.drop_table("workspace_invitations")
    op.drop_column("users", "display_name")
    op.drop_column("tenants", "ai_enabled")
