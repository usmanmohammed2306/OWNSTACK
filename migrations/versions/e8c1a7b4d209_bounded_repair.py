"""Preserve bounded repair runs and every candidate without changing live budgets."""
from alembic import op
import sqlalchemy as sa

revision = "e8c1a7b4d209"
down_revision = "d74f109a32be"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("repair_runs",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("tenant_id", sa.String(40), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("item_id", sa.String(40), sa.ForeignKey("engineering_items.id"), nullable=False),
        sa.Column("request_id", sa.String(40), sa.ForeignKey("change_requests.id"), nullable=False),
        sa.Column("actor_id", sa.String(40), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("original_patch", sa.JSON(), nullable=False),
        sa.Column("original_patch_hash", sa.String(64), nullable=False),
        sa.Column("request_revision", sa.Integer(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("current_attempt_id", sa.String(40)),
        sa.Column("error_code", sa.String(80)),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)))
    for column in ("tenant_id", "item_id", "state"):
        op.create_index("ix_repair_runs_" + column, "repair_runs", [column])
    op.create_table("repair_attempts",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("run_id", sa.String(40), sa.ForeignKey("repair_runs.id"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("model_id", sa.String(120), nullable=False),
        sa.Column("input_patch", sa.JSON(), nullable=False),
        sa.Column("feedback", sa.JSON(), nullable=False),
        sa.Column("candidate", sa.JSON()),
        sa.Column("candidate_hash", sa.String(64)),
        sa.Column("checks", sa.JSON()),
        sa.Column("usage", sa.JSON()),
        sa.Column("error_code", sa.String(80)),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("run_id", "number"))
    for column in ("run_id", "state"):
        op.create_index("ix_repair_attempts_" + column, "repair_attempts", [column])


def downgrade():
    op.drop_table("repair_attempts")
    op.drop_table("repair_runs")
