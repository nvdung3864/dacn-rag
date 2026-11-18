import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, JSON, ForeignKey, UniqueConstraint, Integer, Boolean, Float
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector
from .db import Base
from .config import settings

def uid(): return str(uuid.uuid4())
def now(): return datetime.now(timezone.utc).isoformat()

class User(Base):
    __tablename__='users'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String)
    password_hash: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String, default='user')
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Source(Base):
    __tablename__='knowledge_sources'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String)
    source_type: Mapped[str] = mapped_column(String)
    location: Mapped[str] = mapped_column(String, default='')
    access_scope: Mapped[str] = mapped_column(String, default='PUBLIC')
    allowed_roles: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_synced_at: Mapped[str|None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=now)
    sync_interval_minutes: Mapped[int] = mapped_column(Integer, default=0)

class Document(Base):
    __tablename__='documents'
    __table_args__=(UniqueConstraint('source_id','location'),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    source_id: Mapped[str] = mapped_column(ForeignKey('knowledge_sources.id',ondelete='CASCADE'))
    title: Mapped[str] = mapped_column(String)
    location: Mapped[str] = mapped_column(String)
    original_name: Mapped[str] = mapped_column(String, default='')
    file_path: Mapped[str] = mapped_column(String, default='')
    format: Mapped[str] = mapped_column(String)
    access_scope: Mapped[str] = mapped_column(String, default='INHERIT')
    allowed_roles: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String, default='PENDING')
    version: Mapped[int] = mapped_column(Integer, default=0)
    content_hash: Mapped[str] = mapped_column(String, default='')
    pipeline: Mapped[str] = mapped_column(String, default='')
    indexed_at: Mapped[str|None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=now)
    category: Mapped[str] = mapped_column(String, default='')
    tags: Mapped[list] = mapped_column(JSON, default=list)
    file_hash: Mapped[str] = mapped_column(String, default='', index=True)

class DocumentVersion(Base):
    __tablename__='document_versions'
    __table_args__=(UniqueConstraint('document_id','version'),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    document_id: Mapped[str] = mapped_column(ForeignKey('documents.id',ondelete='CASCADE'))
    version: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String)
    pipeline: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, default=now)

class Chunk(Base):
    __tablename__='chunks'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey('documents.id',ondelete='CASCADE'),index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey('knowledge_sources.id',ondelete='CASCADE'),index=True)
    version: Mapped[int] = mapped_column(Integer)
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    page: Mapped[int|None] = mapped_column(Integer,nullable=True)
    section: Mapped[str|None] = mapped_column(String,nullable=True)
    embedding: Mapped[list] = mapped_column(Vector().with_variant(JSON(),'sqlite'))
    embedding_model: Mapped[str] = mapped_column(String)

class Job(Base):
    __tablename__='ingestion_jobs'
    id: Mapped[str] = mapped_column(String,primary_key=True,default=uid)
    source_id: Mapped[str] = mapped_column(ForeignKey('knowledge_sources.id',ondelete='CASCADE'))
    document_id: Mapped[str|None] = mapped_column(ForeignKey('documents.id',ondelete='CASCADE'),nullable=True)
    kind: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String,default='PENDING')
    error: Mapped[str|None] = mapped_column(Text,nullable=True)
    stats: Mapped[dict] = mapped_column(JSON,default=dict)
    created_at: Mapped[str] = mapped_column(String,default=now)
    finished_at: Mapped[str|None] = mapped_column(String,nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)

class Conversation(Base):
    __tablename__='conversations'
    id: Mapped[str] = mapped_column(String,primary_key=True,default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True)
    title: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String,default=now)
    updated_at: Mapped[str] = mapped_column(String,default=now,index=True)

class QueryRecord(Base):
    __tablename__='query_records'
    id: Mapped[str] = mapped_column(String,primary_key=True,default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True)
    conversation_id: Mapped[str|None] = mapped_column(ForeignKey('conversations.id',ondelete='CASCADE'),nullable=True,index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String,default=now)

class Evaluation(Base):
    __tablename__='evaluations'
    id: Mapped[str] = mapped_column(String,primary_key=True,default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id',ondelete='CASCADE'))
    title: Mapped[str] = mapped_column(String)
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String,default=now)

class RetrievalSession(Base):
    __tablename__='retrieval_sessions'
    id: Mapped[str] = mapped_column(String,primary_key=True,default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True)
    cache_key: Mapped[str] = mapped_column(String,index=True)
    snapshot: Mapped[str] = mapped_column(String)
    hits: Mapped[list] = mapped_column(JSON)
    expires_at: Mapped[float] = mapped_column(Float,index=True)
    created_at: Mapped[str] = mapped_column(String,default=now)

class AnswerFeedback(Base):
    __tablename__='answer_feedback'
    id: Mapped[str] = mapped_column(String,primary_key=True,default=uid)
    query_id: Mapped[str] = mapped_column(ForeignKey('query_records.id',ondelete='CASCADE'),unique=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True)
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text,default='')
    updated_at: Mapped[str] = mapped_column(String,default=now)

class AuditEvent(Base):
    __tablename__='audit_events'
    id: Mapped[str] = mapped_column(String,primary_key=True,default=uid)
    actor_id: Mapped[str|None] = mapped_column(ForeignKey('users.id',ondelete='SET NULL'),nullable=True)
    action: Mapped[str] = mapped_column(String,index=True)
    resource_type: Mapped[str] = mapped_column(String)
    resource_id: Mapped[str] = mapped_column(String)
    details: Mapped[dict] = mapped_column(JSON,default=dict)
    created_at: Mapped[str] = mapped_column(String,default=now,index=True)
