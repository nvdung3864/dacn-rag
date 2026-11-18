"""SSE chat: provisional drafts, live ACL checks, one validated final record."""
import asyncio
import json
import queue
import threading
import time
from fastapi import HTTPException
from sqlalchemy import select
from .db import Session
from .models import User,Source,Document
from .security import allowed_document
from .providers import ProviderError
from .stream_support import generation_hook,GenerationCancelled
from .operations import audit

def live_access(user_id,document_ids):
    with Session() as db:
        user=db.get(User,user_id)
        if not user or not user.active:raise HTTPException(401,'Tài khoản không còn hoạt động.')
        for did in document_ids:
            document=db.get(Document,did);source=db.get(Source,document.source_id) if document else None
            if not source or not allowed_document(document,source,user):raise HTTPException(409,'Quyền truy cập hoặc nguồn đã thay đổi. Vui lòng hỏi lại.')

async def events(user_id,body,request):
    from .rag import query
    outgoing=queue.Queue(maxsize=32);cancel=threading.Event();documents=set();first_draft=None;start=time.perf_counter()
    def put(kind,data):
        while not cancel.is_set():
            try:outgoing.put((kind,data),timeout=.1);return
            except queue.Full:continue
        raise GenerationCancelled()
    def progress(text):
        nonlocal first_draft
        if cancel.is_set():raise GenerationCancelled()
        live_access(user_id,documents)
        if text:
            if first_draft is None:first_draft=round((time.perf_counter()-start)*1000)
            put('draft',{'text':text,'unverified':True})
    def context(hits):
        documents.update(h['document_id'] for h in hits)
        put('status',{'stage':'generating','message':'Đang soạn câu trả lời…'})
    def worker():
        try:
            with Session() as db:
                user=db.get(User,user_id)
                if not user or not user.active:raise HTTPException(401,'Tài khoản không còn hoạt động.')
                with generation_hook(progress,cancel):
                    result=query(db,user,body.question,body.top_k,body.source_ids,body.retrieval_only,body.conversation_id,body.followup_query_id,on_context=context)
                result['stream']={'first_draft_ms':first_draft,'drafts_are_unverified':True}
                live_access(user_id,documents)
                put('result',result)
        except GenerationCancelled:pass
        except (HTTPException,ProviderError) as exc:
            if isinstance(exc,ProviderError):
                with Session() as db:
                    audit(db,db.get(User,user_id),'query.failed','user',user_id,{'error_type':'stream_provider'});db.commit()
            if not cancel.is_set():put('error',{'status':exc.status_code if isinstance(exc,HTTPException) else 503,'detail':exc.detail if isinstance(exc,HTTPException) else str(exc)})
        except Exception:
            import logging
            logging.getLogger('rag.stream').exception('Streaming request failed')
            if not cancel.is_set():put('error',{'status':500,'detail':'Không thể hoàn tất câu trả lời. Vui lòng thử lại.'})
    thread=threading.Thread(target=worker,daemon=True,name='rag-stream');thread.start()
    def frame(kind,data):return 'event: '+kind+'\ndata: '+json.dumps(data,ensure_ascii=False)+'\n\n'
    try:
        yield frame('status',{'stage':'retrieving','message':'Đang tìm ngữ cảnh…'})
        last_ping=time.monotonic()
        while True:
            if await request.is_disconnected():break
            try:kind,data=outgoing.get_nowait()
            except queue.Empty:
                if time.monotonic()-last_ping>10:yield ': keep-alive\n\n';last_ping=time.monotonic()
                await asyncio.sleep(.03);continue
            live_access(user_id,documents)
            yield frame(kind,data)
            if kind in ('result','error'):break
    except HTTPException as exc:
        yield frame('error',{'status':exc.status_code,'detail':exc.detail})
    finally:cancel.set()
