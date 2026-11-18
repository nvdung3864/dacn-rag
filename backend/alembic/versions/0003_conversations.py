from alembic import op
import sqlalchemy as sa

revision='0003_conversations'
down_revision='0002_local_models'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('conversations',
        sa.Column('id',sa.String(),primary_key=True),
        sa.Column('user_id',sa.String(),sa.ForeignKey('users.id',ondelete='CASCADE'),nullable=False),
        sa.Column('title',sa.String(),nullable=False),
        sa.Column('created_at',sa.String(),nullable=False),
        sa.Column('updated_at',sa.String(),nullable=False))
    op.create_index('ix_conversations_user_id','conversations',['user_id'])
    op.create_index('ix_conversations_updated_at','conversations',['updated_at'])
    op.add_column('query_records',sa.Column('conversation_id',sa.String(),nullable=True))
    op.create_foreign_key('fk_query_records_conversation_id','query_records','conversations',['conversation_id'],['id'],ondelete='CASCADE')
    op.create_index('ix_query_records_conversation_id','query_records',['conversation_id'])
    op.execute('INSERT INTO conversations (id,user_id,title,created_at,updated_at) SELECT id,user_id,substr(question,1,120),created_at,created_at FROM query_records')
    op.execute('UPDATE query_records SET conversation_id=id')


def downgrade():
    op.drop_index('ix_query_records_conversation_id',table_name='query_records')
    op.drop_constraint('fk_query_records_conversation_id','query_records',type_='foreignkey')
    op.drop_column('query_records','conversation_id')
    op.drop_table('conversations')
