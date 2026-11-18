from datetime import datetime,timezone,timedelta
import math
from sqlalchemy import select
from .models import AuditEvent,QueryRecord,AnswerFeedback,User,Job

def audit(db,actor,action,kind,resource_id,details=None):
    # Call sites provide a small, explicit metadata allowlist. Never record tokens or passwords.
    db.add(AuditEvent(actor_id=actor.id if actor else None,action=action,resource_type=kind,
        resource_id=resource_id,details=details or {}))

def percentile(values,p):
    if not values:return None
    values=sorted(values);position=(len(values)-1)*p;lower=math.floor(position);upper=math.ceil(position)
    return round(values[lower]+(values[upper]-values[lower])*(position-lower),2)

def usage(db,days):
    since=(datetime.now(timezone.utc)-timedelta(days=days)).isoformat()
    rows=list(db.scalars(select(QueryRecord).where(QueryRecord.created_at>=since)))
    times=[r.result.get('latency_ms',{}).get('total_ms') for r in rows]
    times=[t for t in times if isinstance(t,(int,float))]
    feedback=list(db.scalars(select(AnswerFeedback).where(AnswerFeedback.updated_at>=since)))
    return {'days':days,'questions':len(rows),'active_users':len({r.user_id for r in rows}),
        'no_answer':sum(bool(r.result.get('no_answer')) for r in rows),
        'cache_hits':sum(bool(r.result.get('retrieval_cache_hit')) for r in rows),
        'prompt_tokens':sum(r.result.get('token_usage',{}).get('prompt_tokens',0) or 0 for r in rows),
        'completion_tokens':sum(r.result.get('token_usage',{}).get('completion_tokens',0) or 0 for r in rows),
        'latency_p50_ms':percentile(times,0.5),'latency_p95_ms':percentile(times,0.95),
        'positive_feedback':sum(f.rating==1 for f in feedback),'negative_feedback':sum(f.rating==-1 for f in feedback),
        'note':'Số liệu vận hành, không phải điểm accuracy; token chỉ gồm dữ liệu provider trả về.'}
