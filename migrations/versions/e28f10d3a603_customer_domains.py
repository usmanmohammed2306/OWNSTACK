"""Separate vendor workspaces from their customer accounts and portal identities."""
from alembic import op
import sqlalchemy as sa

revision = 'e28f10d3a603'
down_revision = 'd28f10d3a602'
branch_labels = None
depends_on = None
TABLES = ('customer_accounts', 'customer_projects', 'customer_invitations', 'customer_identities',
          'customer_sessions', 'customer_submissions', 'customer_request_links', 'customer_requirement_links', 'customer_audit')


def ident():
    return sa.Column('id', sa.String(40), primary_key=True)


def tenant():
    return sa.Column('tenant_id', sa.String(40), sa.ForeignKey('tenants.id'), nullable=False)


def customer():
    return sa.Column('customer_id', sa.String(40), nullable=False)


def customer_fk():
    return sa.ForeignKeyConstraint(['tenant_id', 'customer_id'], ['customer_accounts.tenant_id', 'customer_accounts.id'])


def upgrade():
    # No old tenant is guessed to be either a vendor or its customer. Existing
    # rows stay unchanged and become linked only by explicit new onboarding.
    op.create_table('customer_accounts', ident(), tenant(), sa.Column('name', sa.String(100), nullable=False),
        sa.Column('key', sa.String(80), nullable=False), sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False), sa.UniqueConstraint('tenant_id', 'id'), sa.UniqueConstraint('tenant_id', 'key'))
    op.create_table('customer_projects', ident(), tenant(), customer(), sa.Column('project_id', sa.String(40), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False), sa.Column('revision', sa.Integer(), nullable=False), customer_fk(),
        sa.UniqueConstraint('tenant_id', 'customer_id', 'project_id'))
    op.create_table('customer_invitations', ident(), tenant(), customer(), sa.Column('account_revision', sa.Integer(), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False, unique=True), sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used', sa.Boolean(), nullable=False), customer_fk())
    op.create_table('customer_identities', ident(), tenant(), customer(), sa.Column('username', sa.String(40), nullable=False, unique=True),
        sa.Column('name', sa.String(100), nullable=False), sa.Column('password_hash', sa.String(200), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False), sa.Column('revision', sa.Integer(), nullable=False), customer_fk())
    op.create_table('customer_sessions', sa.Column('token_hash', sa.String(64), primary_key=True),
        sa.Column('identity_id', sa.String(40), sa.ForeignKey('customer_identities.id'), nullable=False),
        sa.Column('identity_revision', sa.Integer(), nullable=False), sa.Column('account_revision', sa.Integer(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('customer_submissions', ident(), tenant(), customer(),
        sa.Column('identity_id', sa.String(40), sa.ForeignKey('customer_identities.id'), nullable=False),
        sa.Column('project_id', sa.String(40), sa.ForeignKey('projects.id'), nullable=False), sa.Column('text', sa.Text(), nullable=False),
        sa.Column('idempotency_key', sa.String(80), nullable=False), sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id', 'customer_id', 'project_id'],
            ['customer_projects.tenant_id', 'customer_projects.customer_id', 'customer_projects.project_id']),
        sa.UniqueConstraint('identity_id', 'idempotency_key'))
    for name, subject, target in [('customer_request_links', 'request_id', 'change_requests.id'),
                                  ('customer_requirement_links', 'requirement_id', 'release_requirements.id')]:
        extra = [sa.Column('submission_id', sa.String(40), sa.ForeignKey('customer_submissions.id'), nullable=False, unique=True)] if subject == 'request_id' else []
        op.create_table(name, sa.Column(subject, sa.String(40), sa.ForeignKey(target), primary_key=True), tenant(), customer(),
            sa.Column('account_revision', sa.Integer(), nullable=False), sa.Column('project_revision', sa.Integer(), nullable=False), *extra, customer_fk())
    op.create_table('customer_audit', ident(), tenant(), sa.Column('customer_id', sa.String(40), sa.ForeignKey('customer_accounts.id'), nullable=False),
        sa.Column('actor_id', sa.String(40), nullable=False), sa.Column('action', sa.String(40), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    for table in TABLES:
        if table not in ('customer_sessions', 'customer_request_links', 'customer_requirement_links'):
            op.create_index('ix_' + table + '_tenant_id', table, ['tenant_id'])
    op.create_index('ix_customer_sessions_identity_id', 'customer_sessions', ['identity_id'])


def downgrade():
    for table in TABLES:
        if op.get_bind().execute(sa.text('SELECT count(*) FROM ' + table)).scalar_one():
            raise RuntimeError('Customer records need a reviewed private export before downgrade')
    for table in reversed(TABLES):
        op.drop_table(table)
