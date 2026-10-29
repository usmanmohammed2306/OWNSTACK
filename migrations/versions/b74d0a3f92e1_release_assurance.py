"""Local approved customer requirements and durable release checks."""
from alembic import op
import sqlalchemy as sa

revision = 'b74d0a3f92e1'
down_revision = 'a63d9e104bf2'
branch_labels = None
depends_on = None


def upgrade():
    # Freeze this schema in the migration; future model edits must not rewrite
    # what an older migration creates. Existing rows/ledgers remain untouched.
    op.create_table('release_requirements',
        sa.Column('id',sa.String(40),primary_key=True),
        sa.Column('tenant_id',sa.String(40),sa.ForeignKey('tenants.id'),nullable=False),
        sa.Column('project_id',sa.String(40),sa.ForeignKey('projects.id'),nullable=False),
        sa.Column('key',sa.String(80),nullable=False),sa.Column('version',sa.Integer(),nullable=False),
        sa.Column('spec',sa.JSON(),nullable=False),sa.Column('requirement_hash',sa.String(64),nullable=False),
        sa.Column('state',sa.String(24),nullable=False),
        sa.Column('created_by',sa.String(40),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('approved_by',sa.String(40),sa.ForeignKey('users.id')),
        sa.Column('approver_version',sa.Integer()),sa.Column('approved_at',sa.DateTime(timezone=True)),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('project_id','key','version'),
        sa.CheckConstraint("state IN ('draft','approved','superseded')",name='ck_release_requirement_state'))
    op.create_table('release_checks',
        sa.Column('id',sa.String(40),primary_key=True),
        sa.Column('tenant_id',sa.String(40),sa.ForeignKey('tenants.id'),nullable=False),
        sa.Column('project_id',sa.String(40),sa.ForeignKey('projects.id'),nullable=False),
        sa.Column('requested_by',sa.String(40),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('requester_version',sa.Integer(),nullable=False),
        sa.Column('idempotency_key',sa.String(80),nullable=False),sa.Column('intent_hash',sa.String(64),nullable=False),
        sa.Column('baseline_sha256',sa.String(64),nullable=False),sa.Column('candidate_sha256',sa.String(64),nullable=False),
        sa.Column('requirement_ids',sa.JSON(),nullable=False),sa.Column('requirements_sha256',sa.String(64),nullable=False),
        sa.Column('requirements',sa.JSON(),nullable=False),sa.Column('state',sa.String(24),nullable=False),
        sa.Column('revision',sa.Integer(),nullable=False),sa.Column('claim_token',sa.String(64)),
        sa.Column('deadline_at',sa.DateTime(timezone=True)),sa.Column('report',sa.JSON()),sa.Column('evidence_hash',sa.String(64)),
        sa.Column('reason',sa.String(300)),sa.Column('decision',sa.String(40)),
        sa.Column('decided_by',sa.String(40),sa.ForeignKey('users.id')),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('completed_at',sa.DateTime(timezone=True)),
        sa.UniqueConstraint('tenant_id','requested_by','idempotency_key'),
        sa.CheckConstraint("state IN ('queued','running','passed','regression','baseline_failed','blocked','canceled')",name='ck_release_check_state'))
    op.create_table('release_audit',sa.Column('id',sa.String(40),primary_key=True),
        sa.Column('tenant_id',sa.String(40),sa.ForeignKey('tenants.id'),nullable=False),
        sa.Column('project_id',sa.String(40),sa.ForeignKey('projects.id'),nullable=False),
        sa.Column('subject_id',sa.String(40),nullable=False),sa.Column('action',sa.String(50),nullable=False),
        sa.Column('payload',sa.JSON(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    for table in ('release_requirements','release_checks','release_audit'):
        for column in ('tenant_id','project_id'):
            op.create_index('ix_'+table+'_'+column,table,[column])
    op.create_index('ix_release_audit_subject_id','release_audit',['subject_id'])


def downgrade():
    for name in ('release_audit','release_checks','release_requirements'):
        if op.get_bind().execute(sa.text('SELECT count(*) FROM '+name)).scalar_one():
            raise RuntimeError('Populated release evidence requires an explicitly reviewed downgrade')
    for name in ('release_audit', 'release_checks', 'release_requirements'):
        op.drop_table(name)
