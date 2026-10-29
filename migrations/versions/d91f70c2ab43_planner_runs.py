"""Durable local command lifecycle; preserves existing workflow and budget rows."""
from alembic import op
import sqlalchemy as sa

revision='d91f70c2ab43'
down_revision='c804f3a127de'
branch_labels=depends_on=None


def upgrade():
    op.add_column('tenants',sa.Column('approval_quorum',sa.Integer(),nullable=False,server_default='1'))
    op.add_column('variations',sa.Column('approval_quorum',sa.Integer(),nullable=False,server_default='1'))
    op.create_table('approval_witnesses',
        sa.Column('id',sa.String(40),primary_key=True),
        sa.Column('tenant_id',sa.String(40),sa.ForeignKey('tenants.id'),nullable=False),
        sa.Column('proposal_id',sa.String(40),sa.ForeignKey('proposals.id'),nullable=False),
        sa.Column('proposal_hash',sa.String(64),nullable=False),
        sa.Column('actor_id',sa.String(40),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('identity_version',sa.Integer(),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_approval_witnesses_tenant_id','approval_witnesses',['tenant_id'])
    op.create_index('ix_approval_witnesses_proposal_id','approval_witnesses',['proposal_id'])
    op.create_table('planner_runs',
        sa.Column('id',sa.String(40),primary_key=True),
        sa.Column('tenant_id',sa.String(40),sa.ForeignKey('tenants.id'),nullable=False),
        sa.Column('actor_id',sa.String(40),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('idempotency_key',sa.String(100),nullable=False),
        sa.Column('command_hash',sa.String(64),nullable=False),
        sa.Column('command_text',sa.Text(),nullable=False),
        sa.Column('role',sa.String(20),nullable=False),
        sa.Column('identity_version',sa.Integer(),nullable=False),
        sa.Column('generation',sa.Integer(),nullable=False),
        sa.Column('status',sa.String(20),nullable=False),
        sa.Column('result',sa.JSON()),
        sa.Column('error_code',sa.String(40)),
        sa.Column('deadline_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('tenant_id','actor_id','idempotency_key'))
    op.create_index('ix_planner_runs_tenant_id','planner_runs',['tenant_id'])


def downgrade():
    op.drop_table('planner_runs')
    op.drop_table('approval_witnesses')
    op.drop_column('variations','approval_quorum')
    op.drop_column('tenants','approval_quorum')
