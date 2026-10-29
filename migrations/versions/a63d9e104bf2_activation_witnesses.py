"""Freeze selected approval reviews; preserve legacy selection semantics explicitly."""
from uuid import uuid4
from alembic import op
import sqlalchemy as sa

revision='a63d9e104bf2'
down_revision='f7b42c1d9a60'
branch_labels=depends_on=None

def upgrade():
    op.create_table('variation_witnesses',sa.Column('id',sa.String(40),primary_key=True),
        sa.Column('tenant_id',sa.String(40),sa.ForeignKey('tenants.id'),nullable=False),
        sa.Column('variation_id',sa.String(40),sa.ForeignKey('variations.id'),nullable=False),
        sa.Column('witness_id',sa.String(40),sa.ForeignKey('approval_witnesses.id'),nullable=False),
        sa.Column('source',sa.String(30),nullable=False),sa.UniqueConstraint('variation_id','witness_id'),
        sa.CheckConstraint("source IN ('activation','legacy')",name='ck_variation_witness_source'))
    for field in ['tenant_id','variation_id','witness_id']:
        op.create_index('ix_variation_witnesses_'+field,'variation_witnesses',[field])
    connection=op.get_bind()
    # Historical activation-time team membership cannot be reconstructed. Keep
    # the old exact-review set, labeled legacy, without claiming retroactive proof.
    rows=connection.execute(sa.text('''SELECT v.id,v.tenant_id,w.id
        FROM variations v JOIN proposals p ON p.id=v.proposal_id AND p.tenant_id=v.tenant_id
        JOIN approval_witnesses w ON w.proposal_id=p.id AND w.tenant_id=v.tenant_id
          AND w.proposal_hash=p.proposal_hash WHERE v.approval_quorum=2''')).all()
    for variation,tenant,witness in rows:
        connection.execute(sa.text('''INSERT INTO variation_witnesses
            (id,tenant_id,variation_id,witness_id,source) VALUES (:id,:tenant,:variation,:witness,:source)'''),
            {'id':str(uuid4()),'tenant':tenant,'variation':variation,'witness':witness,'source':'legacy'})

def downgrade():
    if op.get_bind().execute(sa.text('SELECT COUNT(*) FROM variation_witnesses')).scalar_one():
        raise RuntimeError('Populated reviewer selections require an explicitly reviewed downgrade')
    op.drop_table('variation_witnesses')
