"""Persist organizational teams and backfill existing authority into General."""
from alembic import op
import hashlib
import sqlalchemy as sa
from uuid import uuid4

revision='f7b42c1d9a60'
down_revision='e02c81d3bf54'
branch_labels=depends_on=None


def upgrade():
    op.create_table('teams',sa.Column('id',sa.String(40),primary_key=True),
        sa.Column('tenant_id',sa.String(40),sa.ForeignKey('tenants.id'),nullable=False),
        sa.Column('name',sa.String(80),nullable=False),sa.Column('name_key',sa.String(160),nullable=False),
        sa.Column('enabled',sa.Boolean(),nullable=False,server_default=sa.true()),
        sa.UniqueConstraint('tenant_id','id'),sa.UniqueConstraint('tenant_id','name_key'))
    op.create_index('ix_teams_tenant_id','teams',['tenant_id'])
    op.create_index('uq_users_tenant_id_id','users',['tenant_id','id'],unique=True)
    op.create_table('team_memberships',sa.Column('id',sa.String(40),primary_key=True),
        sa.Column('tenant_id',sa.String(40),sa.ForeignKey('tenants.id'),nullable=False),
        sa.Column('team_id',sa.String(40),nullable=False),sa.Column('user_id',sa.String(40),nullable=False),
        sa.Column('role',sa.String(20),nullable=False),sa.Column('enabled',sa.Boolean(),nullable=False,server_default=sa.true()),
        sa.Column('revision',sa.Integer(),nullable=False,server_default='1'),sa.UniqueConstraint('team_id','user_id'),
        sa.CheckConstraint("role IN ('member','manager')",name='ck_team_membership_role'),
        sa.CheckConstraint('revision >= 1',name='ck_team_membership_revision'),
        sa.ForeignKeyConstraint(['tenant_id','team_id'],['teams.tenant_id','teams.id']),
        sa.ForeignKeyConstraint(['tenant_id','user_id'],['users.tenant_id','users.id']))
    for field in ['tenant_id','team_id','user_id']:op.create_index('ix_team_memberships_'+field,'team_memberships',[field])
    op.create_table('team_audit',sa.Column('id',sa.String(40),primary_key=True),
        sa.Column('tenant_id',sa.String(40),sa.ForeignKey('tenants.id'),nullable=False),
        sa.Column('actor_id',sa.String(40),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('team_id',sa.String(40),sa.ForeignKey('teams.id'),nullable=False),
        sa.Column('subject_id',sa.String(40),sa.ForeignKey('users.id')),
        sa.Column('action',sa.String(40),nullable=False),sa.Column('payload',sa.JSON(),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_team_audit_tenant_id','team_audit',['tenant_id'])
    op.create_index('ix_team_audit_team_id','team_audit',['team_id'])
    connection=op.get_bind()
    for table in ['projects','change_requests','workspace_invitations']:
        if connection.dialect.name=='sqlite':
            # SQLite supports adding a nullable REFERENCES column directly.
            # Avoid rebuilding populated identity/project tables and their FKs.
            op.execute(sa.text(f'ALTER TABLE {table} ADD COLUMN team_id VARCHAR(40) REFERENCES teams(id)'))
        else:op.add_column(table,sa.Column('team_id',sa.String(40),sa.ForeignKey('teams.id')))
        if table!='workspace_invitations':op.create_index('ix_'+table+'_team_id',table,['team_id'])
    for tenant in connection.execute(sa.text('SELECT id FROM tenants')).scalars().all():
        key=hashlib.sha256(('ownstack:general:'+tenant).encode()).hexdigest()[:32]
        connection.execute(sa.text('INSERT INTO teams (id,tenant_id,name,name_key,enabled) VALUES (:id,:tenant,:name,:key,:enabled)'),
            {'id':key,'tenant':tenant,'name':'General','key':'general','enabled':True})
        for user,role in connection.execute(sa.text('SELECT id,role FROM users WHERE tenant_id=:tenant'),{'tenant':tenant}):
            connection.execute(sa.text('INSERT INTO team_memberships (id,tenant_id,team_id,user_id,role,enabled,revision) VALUES (:id,:tenant,:team,:user,:role,:enabled,1)'),
                {'id':str(uuid4()),'tenant':tenant,'team':key,'user':user,'role':'manager' if role in {'admin','manager'} else 'member','enabled':True})
        for table in ['projects','change_requests','workspace_invitations']:
            connection.execute(sa.text(f'UPDATE {table} SET team_id=:team WHERE tenant_id=:tenant'),{'team':key,'tenant':tenant})


def downgrade():
    # Empty installation rollback is safe. Removing populated scope would expand
    # access, so real data requires a separate explicitly reviewed migration.
    if op.get_bind().execute(sa.text('SELECT COUNT(*) FROM teams')).scalar_one():
        raise RuntimeError('Populated team-scope downgrade requires an explicit reviewed data migration')
    for table in ['workspace_invitations','change_requests','projects']:
        if table!='workspace_invitations':op.drop_index('ix_'+table+'_team_id',table_name=table)
        op.drop_column(table,'team_id')
    op.drop_table('team_audit');op.drop_table('team_memberships');op.drop_table('teams')
    op.drop_index('uq_users_tenant_id_id',table_name='users')
