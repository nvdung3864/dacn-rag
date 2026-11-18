"""Keep historical vectors when changing embedding models and dimensions."""
from alembic import op

revision='0002_local_models'
down_revision='0001_baseline'
branch_labels=None
depends_on=None

def upgrade():
    # Removing the dimension constraint keeps all existing vectors intact.
    # Retrieval filters by current document pipeline, version and vector length.
    op.execute('ALTER TABLE chunks ALTER COLUMN embedding TYPE vector USING embedding::vector')

def downgrade():
    # PostgreSQL rejects this cast if non-1536 vectors remain; never delete them.
    op.execute('ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(1536) USING embedding::vector(1536)')
