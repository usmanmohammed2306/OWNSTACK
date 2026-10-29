"""Reporting metadata, bounded request context and exact-code comments."""
from alembic import op
import sqlalchemy as sa

revision='c28f10d3a601'
down_revision='b74d0a3f92e1'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('organization_profiles',
        sa.Column('user_id',sa.String(40),primary_key=True),sa.Column('tenant_id',sa.String(40),sa.ForeignKey('tenants.id'),nullable=False),
        sa.Column('title',sa.String(80),nullable=False),sa.Column('manager_id',sa.String(40)),sa.Column('revision',sa.Integer(),nullable=False),
        sa.Column('updated_by',sa.String(40),sa.ForeignKey('users.id'),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),
        sa.ForeignKeyConstraint(['tenant_id','user_id'],['users.tenant_id','users.id']),
        sa.ForeignKeyConstraint(['tenant_id','manager_id'],['users.tenant_id','users.id']))
    op.create_table('organization_changes',sa.Column('id',sa.String(40),primary_key=True),
        sa.Column('tenant_id',sa.String(40),sa.ForeignKey('tenants.id'),nullable=False),
        sa.Column('actor_id',sa.String(40),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('subject_id',sa.String(40),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('payload',sa.JSON(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_table('request_workspaces',
        sa.Column('request_id',sa.String(40),sa.ForeignKey('change_requests.id'),primary_key=True),
        sa.Column('tenant_id',sa.String(40),sa.ForeignKey('tenants.id'),nullable=False),
        sa.Column('customer_text',sa.Text(),nullable=False),sa.Column('code_files',sa.JSON(),nullable=False),sa.Column('code_hash',sa.String(64)))
    op.create_table('request_guidance',sa.Column('id',sa.String(40),primary_key=True),
        sa.Column('tenant_id',sa.String(40),sa.ForeignKey('tenants.id'),nullable=False),
        sa.Column('request_id',sa.String(40),sa.ForeignKey('change_requests.id'),nullable=False),
        sa.Column('actor_id',sa.String(40),sa.ForeignKey('users.id'),nullable=False),sa.Column('request_revision',sa.Integer(),nullable=False),
        sa.Column('pattern_id',sa.String(80),nullable=False),sa.Column('pattern_hash',sa.String(64),nullable=False),
        sa.Column('decision',sa.String(10),nullable=False),sa.Column('note',sa.Text(),nullable=False),
        sa.Column('snapshot',sa.JSON(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('request_id','request_revision'))
    op.create_table('engineering_comments',sa.Column('id',sa.String(40),primary_key=True),
        sa.Column('tenant_id',sa.String(40),sa.ForeignKey('tenants.id'),nullable=False),
        sa.Column('item_id',sa.String(40),sa.ForeignKey('engineering_items.id'),nullable=False),
        sa.Column('request_id',sa.String(40),sa.ForeignKey('change_requests.id'),nullable=False),
        sa.Column('actor_id',sa.String(40),sa.ForeignKey('users.id'),nullable=False),sa.Column('patch_hash',sa.String(64),nullable=False),
        sa.Column('request_revision',sa.Integer(),nullable=False),sa.Column('body',sa.Text(),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    for table in ('organization_profiles','organization_changes','request_workspaces','request_guidance','engineering_comments'):
        op.create_index('ix_'+table+'_tenant_id',table,['tenant_id'])
    op.create_index('ix_organization_profiles_manager_id','organization_profiles',['manager_id'])
    op.create_index('ix_request_guidance_request_id','request_guidance',['request_id'])
    op.create_index('ix_engineering_comments_item_id','engineering_comments',['item_id'])


def downgrade():
    tables=('engineering_comments','request_guidance','request_workspaces','organization_changes','organization_profiles')
    for name in tables:
        if op.get_bind().execute(sa.text('SELECT count(*) FROM '+name)).scalar_one():
            raise RuntimeError('Populated collaboration history needs an explicitly reviewed downgrade')
    for name in tables:op.drop_table(name)
