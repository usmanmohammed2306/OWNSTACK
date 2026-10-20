"""Add fenced outbox leases and account token revocation without renewing budgets."""
from alembic import op
import sqlalchemy as sa

revision = "a14d09c7f602"
down_revision = "e8c1a7b4d209"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("token_version", sa.Integer(), nullable=False, server_default="1"))
    for name, kind in [("destination_id", sa.String(64)), ("lease_id", sa.String(40)),
                       ("lease_until", sa.DateTime(timezone=True)), ("available_at", sa.DateTime(timezone=True)),
                       ("delivered_at", sa.DateTime(timezone=True)), ("last_error", sa.String(40))]:
        op.add_column("outbox", sa.Column(name, kind, nullable=True))
    op.create_index("ix_outbox_dispatch", "outbox", ["tenant_id", "state", "available_at"])
    op.create_table("delivery_receipts",
        sa.Column("event_id", sa.String(40), primary_key=True),
        sa.Column("destination_id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(40), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("envelope_hash", sa.String(64), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_delivery_receipts_tenant_id", "delivery_receipts", ["tenant_id"])
    op.create_table("identity_events",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("tenant_id", sa.String(40), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("actor_id", sa.String(40), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("subject_id", sa.String(40), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_identity_events_tenant_id", "identity_events", ["tenant_id"])


def downgrade():
    op.drop_table("identity_events")
    op.drop_table("delivery_receipts")
    op.drop_index("ix_outbox_dispatch", "outbox")
    for name in ("last_error", "delivered_at", "available_at", "lease_until", "lease_id", "destination_id"):
        op.drop_column("outbox", name)
    op.drop_column("users", "token_version")
