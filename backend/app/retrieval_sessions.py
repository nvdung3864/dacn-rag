"""Short-lived result reuse, invalidated by corpus, policy or configuration changes."""
import hashlib
import json
import time
from sqlalchemy import select,delete
from .config import settings,pipeline_key
from .models import Source,Document,Chunk,RetrievalSession
from .security import allowed_document

def fingerprint(db,user):
    # Include all documents, not just hits: a newly indexed document can change top-k.
    sources=[(s.id,s.enabled,s.access_scope,s.allowed_roles,s.last_synced_at) for s in db.scalars(select(Source).order_by(Source.id))]
    docs=[(d.id,d.source_id,d.status,d.version,d.pipeline,d.access_scope,d.allowed_roles,d.indexed_at) for d in db.scalars(select(Document).order_by(Document.id))]
    value=[user.id,user.role,user.active,pipeline_key(),settings.config_version,settings.min_score,
        settings.llm_model,settings.answer_engine,settings.context_chars,settings.freshness_days,
        settings.retrieval_cache_seconds,sources,docs]
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def key_for(question,top_k,source_ids,strategy):
    return hashlib.sha256(json.dumps([question,top_k,sorted(set(source_ids or [])),strategy],ensure_ascii=False).encode()).hexdigest()

def load(db,user,key,snapshot):
    row=db.scalar(select(RetrievalSession).where(RetrievalSession.user_id==user.id,RetrievalSession.cache_key==key,
        RetrievalSession.snapshot==snapshot,RetrievalSession.expires_at>time.time()).order_by(RetrievalSession.expires_at.desc()))
    if not row:return None
    for hit in row.hits:
        chunk=db.get(Chunk,hit['chunk_id']);doc=db.get(Document,hit['document_id']);source=db.get(Source,hit['source_id'])
        if not chunk or not doc or not source or chunk.version!=doc.version or not allowed_document(doc,source,user):return None
    return row

def save(db,user,key,snapshot,hits):
    db.execute(delete(RetrievalSession).where(RetrievalSession.expires_at<=time.time()))
    # Limit retained text for each account even if the user asks many distinct questions.
    old=list(db.scalars(select(RetrievalSession.id).where(RetrievalSession.user_id==user.id).order_by(RetrievalSession.expires_at.desc()).offset(199)))
    if old:db.execute(delete(RetrievalSession).where(RetrievalSession.id.in_(old)))
    row=RetrievalSession(user_id=user.id,cache_key=key,snapshot=snapshot,hits=hits,
        expires_at=time.time()+min(3600,max(0,settings.retrieval_cache_seconds)))
    db.add(row);db.flush()
    return row
