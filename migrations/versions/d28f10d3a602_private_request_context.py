"""Keep internal engineering instructions separate from public request text."""
from alembic import op
import sqlalchemy as sa
revision='d28f10d3a602'
down_revision='c28f10d3a601'
branch_labels=None
depends_on=None


def upgrade():
    blocked=op.get_bind().execute(sa.text("SELECT count(*) FROM request_workspaces w JOIN change_requests r ON r.id=w.request_id WHERE r.accepted_proposal_id IS NOT NULL AND r.text<>w.customer_text")).scalar_one()
    if blocked:raise RuntimeError('A prepared prototype request needs an operator-reviewed private-context migration')
    op.add_column('request_workspaces',sa.Column('effective_text',sa.Text(),nullable=True))
    op.execute(sa.text('UPDATE request_workspaces SET effective_text=(SELECT text FROM change_requests WHERE id=request_id)'))
    op.execute(sa.text("UPDATE attempts SET state='superseded',error_code='REQUEST_CONTEXT_MIGRATED',finished_at=CURRENT_TIMESTAMP WHERE request_id IN (SELECT request_id FROM request_workspaces) AND state IN ('queued','running')"))
    op.execute(sa.text("UPDATE change_requests SET text=(SELECT customer_text FROM request_workspaces WHERE request_id=change_requests.id),revision=revision+1,current_attempt_id=NULL,status='new' WHERE id IN (SELECT request_id FROM request_workspaces) AND accepted_proposal_id IS NULL"))


def downgrade():
    if op.get_bind().execute(sa.text('SELECT count(*) FROM request_workspaces WHERE effective_text IS NOT NULL')).scalar_one():
        raise RuntimeError('Private engineering context requires a reviewed export before downgrade')
    op.drop_column('request_workspaces','effective_text')
