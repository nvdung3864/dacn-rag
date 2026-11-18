"""Baseline schema frozen at creation; changes require a new migration."""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
revision='0001_baseline'
down_revision=None
branch_labels=None
depends_on=None

def table(name,*cols,**kw):op.create_table(name,*cols,**kw)
def col(name,kind=sa.String(),nullable=False,**kw):return sa.Column(name,kind,nullable=nullable,**kw)
def fk(name,target,nullable=False):return sa.Column(name,sa.String(),sa.ForeignKey(target,ondelete='CASCADE'),nullable=nullable)
def ident():return col('id',primary_key=True)
def upgrade():
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    table('users',ident(),col('email',unique=True),col('name'),col('password_hash'),col('role'),col('active',sa.Boolean()))
    table('knowledge_sources',ident(),col('name'),col('source_type'),col('location'),col('access_scope'),col('allowed_roles',sa.JSON()),col('enabled',sa.Boolean()),col('last_synced_at',nullable=True),col('created_at'))
    table('documents',ident(),fk('source_id','knowledge_sources.id'),col('title'),col('location'),col('original_name'),col('file_path'),col('format'),col('access_scope'),col('allowed_roles',sa.JSON()),col('status'),col('version',sa.Integer()),col('content_hash'),col('pipeline'),col('indexed_at',nullable=True),col('created_at'),sa.UniqueConstraint('source_id','location'))
    table('document_versions',ident(),fk('document_id','documents.id'),col('version',sa.Integer()),col('content_hash'),col('pipeline'),col('created_at'),sa.UniqueConstraint('document_id','version'))
    table('chunks',ident(),fk('document_id','documents.id'),fk('source_id','knowledge_sources.id'),col('version',sa.Integer()),col('chunk_index',sa.Integer()),col('text',sa.Text()),col('page',sa.Integer(),nullable=True),col('section',nullable=True),col('embedding',Vector(1536)),col('embedding_model'))
    op.create_index('ix_chunks_document_id','chunks',['document_id']);op.create_index('ix_chunks_source_id','chunks',['source_id'])
    table('ingestion_jobs',ident(),fk('source_id','knowledge_sources.id'),fk('document_id','documents.id',nullable=True),col('kind'),col('status'),col('error',sa.Text(),nullable=True),col('stats',sa.JSON()),col('created_at'),col('finished_at',nullable=True))
    table('query_records',ident(),fk('user_id','users.id'),col('question',sa.Text()),col('answer',sa.Text()),col('result',sa.JSON()),col('created_at'))
    op.create_index('ix_query_records_user_id','query_records',['user_id'])
    table('evaluations',ident(),fk('user_id','users.id'),col('title'),col('result',sa.JSON()),col('created_at'))
def downgrade():
    for name in ['evaluations','query_records','ingestion_jobs','chunks','document_versions','documents','knowledge_sources','users']:op.drop_table(name)
