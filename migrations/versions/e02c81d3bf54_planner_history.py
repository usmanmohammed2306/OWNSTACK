"""Append-only planner terminal history; no invented pre-migration attempts."""
from alembic import op
import sqlalchemy as sa
revision='e02c81d3bf54'
down_revision='d91f70c2ab43'
branch_labels=depends_on=None

def upgrade():
    op.create_table('planner_events',sa.Column('id',sa.String(40),primary_key=True),
        sa.Column('run_id',sa.String(40),sa.ForeignKey('planner_runs.id'),nullable=False),
        sa.Column('generation',sa.Integer(),nullable=False),sa.Column('status',sa.String(20),nullable=False),
        sa.Column('error_code',sa.String(40)),sa.Column('finished_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('run_id','generation'))
    op.create_index('ix_planner_events_run_id','planner_events',['run_id'])

def downgrade():op.drop_table('planner_events')
