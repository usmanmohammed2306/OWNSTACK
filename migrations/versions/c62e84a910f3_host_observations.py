"""Persist actual host authorization observations without backfilling previews."""
from alembic import op
import sqlalchemy as sa

revision = "c62e84a910f3"
down_revision = "92ab71f0d614"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "host_observations",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("tenant_id", sa.String(40), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("project_id", sa.String(40), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("actor_id", sa.String(40), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("document_id", sa.String(40), sa.ForeignKey("documents.id")),
        sa.Column("variation_id", sa.String(40), sa.ForeignKey("variations.id")),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.Column("basis", sa.String(30), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_host_observations_tenant_id", "host_observations", ["tenant_id"])
    op.create_index("ix_host_observations_variation_id", "host_observations", ["variation_id"])
    op.create_index("ix_host_observation_tenant_time", "host_observations", ["tenant_id", "observed_at"])


def downgrade() -> None:
    op.drop_table("host_observations")
