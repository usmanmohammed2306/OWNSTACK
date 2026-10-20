"""Durable inference call cap.

Revision ID: f4a2d9b71c30
Revises: bd01c3fe60ce
"""
from alembic import op
import sqlalchemy as sa

revision = "f4a2d9b71c30"
down_revision = "bd01c3fe60ce"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = op.create_table(
        "inference_budget",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("reserved_calls", sa.Integer(), nullable=False),
    )
    op.bulk_insert(table, [{"id": "global", "reserved_calls": 0}])


def downgrade() -> None:
    op.drop_table("inference_budget")
