"""Index exact read-time grant candidates without rewriting historical records."""
from alembic import op

revision = "d74f109a32be"
down_revision = "c62e84a910f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_variation_read_candidate", "variations",
                    ["tenant_id", "project_id", "viewer_id", "state", "expires_at"])


def downgrade() -> None:
    op.drop_index("ix_variation_read_candidate", table_name="variations")
