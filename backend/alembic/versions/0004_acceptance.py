"""Retrieval sessions, document labels, feedback and operations evidence."""
from alembic import op
import sqlalchemy as sa

revision='0004_acceptance'
down_revision='0003_conversations'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('knowledge_sources',sa.Column('sync_interval_minutes',sa.Integer(),nullable=False,server_default='0'))
    op.add_column('documents',sa.Column('category',sa.String(),nullable=False,server_default=''))
    op.add_column('documents',sa.Column('tags',sa.JSON(),nullable=False,server_default='[]'))
    op.add_column('documents',sa.Column('file_hash',sa.String(),nullable=False,server_default=''))
    op.create_index('ix_documents_file_hash','documents',['file_hash'])
    op.add_column('ingestion_jobs',sa.Column('attempts',sa.Integer(),nullable=False,server_default='0'))
    op.create_table('retrieval_sessions',sa.Column('id',sa.String(),primary_key=True),
        sa.Column('user_id',sa.String(),sa.ForeignKey('users.id',ondelete='CASCADE'),nullable=False),
        sa.Column('cache_key',sa.String(),nullable=False),sa.Column('snapshot',sa.String(),nullable=False),
        sa.Column('hits',sa.JSON(),nullable=False),sa.Column('expires_at',sa.Float(),nullable=False),sa.Column('created_at',sa.String(),nullable=False))
    for name in ['user_id','cache_key','expires_at']:op.create_index('ix_retrieval_sessions_'+name,'retrieval_sessions',[name])
    op.create_table('answer_feedback',sa.Column('id',sa.String(),primary_key=True),
        sa.Column('query_id',sa.String(),sa.ForeignKey('query_records.id',ondelete='CASCADE'),nullable=False,unique=True),
        sa.Column('user_id',sa.String(),sa.ForeignKey('users.id',ondelete='CASCADE'),nullable=False),
        sa.Column('rating',sa.Integer(),nullable=False),sa.Column('comment',sa.Text(),nullable=False),sa.Column('updated_at',sa.String(),nullable=False))
    op.create_index('ix_answer_feedback_user_id','answer_feedback',['user_id'])
    op.create_table('audit_events',sa.Column('id',sa.String(),primary_key=True),
        sa.Column('actor_id',sa.String(),sa.ForeignKey('users.id',ondelete='SET NULL'),nullable=True),
        sa.Column('action',sa.String(),nullable=False),sa.Column('resource_type',sa.String(),nullable=False),
        sa.Column('resource_id',sa.String(),nullable=False),sa.Column('details',sa.JSON(),nullable=False),sa.Column('created_at',sa.String(),nullable=False))
    for name in ['action','created_at']:op.create_index('ix_audit_events_'+name,'audit_events',[name])

def downgrade():
    op.drop_table('audit_events');op.drop_table('answer_feedback');op.drop_table('retrieval_sessions')
    op.drop_column('ingestion_jobs','attempts')
    op.drop_index('ix_documents_file_hash',table_name='documents')
    for name in ['file_hash','tags','category']:op.drop_column('documents',name)
    op.drop_column('knowledge_sources','sync_interval_minutes')
