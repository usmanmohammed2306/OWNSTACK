"""Revocable web sessions, shared rate limits, and fenced engineering operations."""
from alembic import op
import sqlalchemy as sa

revision = "92ab71f0d614"
down_revision = "f4a2d9b71c30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_table("web_sessions",
                    sa.Column("token_hash", sa.String(64), primary_key=True),
                    sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id"), nullable=False),
                    sa.Column("csrf_hash", sa.String(64), nullable=False),
                    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_web_sessions_user_id", "web_sessions", ["user_id"])
    op.create_index("ix_web_sessions_expires_at", "web_sessions", ["expires_at"])
    op.create_table("rate_windows",
                    sa.Column("key", sa.String(64), primary_key=True),
                    sa.Column("count", sa.Integer(), nullable=False),
                    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_rate_windows_expires_at", "rate_windows", ["expires_at"])
    op.add_column("engineering_items", sa.Column("operation_id", sa.String(40)))
    op.add_column("engineering_items", sa.Column("operation_deadline", sa.DateTime(timezone=True)))
    op.create_table("runtime_pulses", sa.Column("component", sa.String(40), primary_key=True),
                    sa.Column("touched_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_attempt_state_deadline", "attempts", ["state", "deadline_at"])
    op.create_index("ix_engineering_state_deadline", "engineering_items", ["status", "operation_deadline"])


def downgrade() -> None:
    op.drop_index("ix_engineering_state_deadline", table_name="engineering_items")
    op.drop_index("ix_attempt_state_deadline", table_name="attempts")
    op.drop_table("runtime_pulses")
    op.drop_column("engineering_items", "operation_deadline")
    op.drop_column("engineering_items", "operation_id")
    op.drop_table("rate_windows")
    op.drop_table("web_sessions")
    op.drop_column("users", "enabled")
