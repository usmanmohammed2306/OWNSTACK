"""Add scoped investigation memory without changing existing records or budgets."""
from alembic import op
import sqlalchemy as sa

revision = "b73e2c91d406"
down_revision = "a14d09c7f602"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("investigations",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("tenant_id", sa.String(40), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("request_id", sa.String(40), sa.ForeignKey("change_requests.id"), nullable=False),
        sa.Column("actor_id", sa.String(40), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("workflow_hash", sa.String(64), nullable=False),
        sa.Column("model_id", sa.String(120), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("memory", sa.JSON(), nullable=False),
        sa.Column("lease_id", sa.String(40)),
        sa.Column("deadline_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(40)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "request_id", "snapshot_hash", "workflow_hash", "model_id"))
    op.create_index("ix_investigation_request", "investigations", ["tenant_id", "request_id"])


def downgrade():
    op.drop_table("investigations")
