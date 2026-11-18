import time,uuid,unicodedata,hashlib
from collections import defaultdict,deque
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI,Depends,HTTPException,UploadFile,File,Form,BackgroundTasks,Request,Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse,StreamingResponse
from sqlalchemy import select,func,update,text
from .db import Base,engine,get_db,Session
from .config import settings,ANSWER_REVISION
from .models import User,Source,Document,Chunk,Job,QueryRecord,Conversation,Evaluation,AnswerFeedback,AuditEvent,now
from .security import current_user,admin,hash_password,check_password,token_for,allowed_source,allowed_document,bearer
from .schemas import Login,UserCreate,UserPatch,SourceCreate,SourcePatch,DocumentPatch,Question,EvaluationRequest,Feedback
from .ingestion import run_job,validate_url
from .rag import query,record_allowed
from .providers import ProviderError
from .operations import audit,usage

@asynccontextmanager
async def lifespan(app):
    if len(settings.jwt_secret)<32 or settings.jwt_secret.startswith('replace-with'):raise RuntimeError('JWT_SECRET phải là secret riêng có ít nhất 32 ký tự. Tạo secret trong .env trước khi khởi động.')
    if engine.dialect.name=='sqlite':Base.metadata.create_all(engine)
    if settings.job_execution_mode not in ('background','worker'):raise RuntimeError('JOB_EXECUTION_MODE phải là background hoặc worker.')
    if settings.job_execution_mode=='background':
        with Session() as db:
            db.execute(update(Job).where(Job.status.in_(['PENDING','PROCESSING'])).values(status='FAILED',error='Tiến trình bị gián đoạn. Vui lòng chạy lại tác vụ.',finished_at=now()))
            db.commit()
    yield

app=FastAPI(title='BK Tri thức — ĐACN RAG',version='0.1.0',lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=list(settings.cors_origins),allow_credentials=False,allow_methods=['GET','POST','PATCH','DELETE'],allow_headers=['Authorization','Content-Type'])

def data(obj,exclude=()):
    return {c.name:getattr(obj,c.name) for c in obj.__table__.columns if c.name not in exclude}
def source_access(db,sid,user):
    source=db.get(Source,sid)
    if not source or (user.role!='admin' and not allowed_source(source,user)):raise HTTPException(404,'Không tìm thấy nguồn được phép truy cập.')
    return source
def doc_access(db,did,user):
    doc=db.get(Document,did)
    if not doc:raise HTTPException(404,'Không tìm thấy tài liệu.')
    src=db.get(Source,doc.source_id)
    if user.role!='admin' and not allowed_document(doc,src,user):raise HTTPException(404,'Không tìm thấy tài liệu được phép truy cập.')
    return doc,src
def doc_data(db,doc):
    count=db.scalar(select(func.count()).select_from(Chunk).where(Chunk.document_id==doc.id,Chunk.version==doc.version))
    return {**data(doc,('file_path',)),'chunks':count,'source_name':db.get(Source,doc.source_id).name}
def enqueue(db,source,doc,kind,tasks,user=None):
    db.scalar(select(Source).where(Source.id==source.id).with_for_update())
    running=select(Job).where(Job.status.in_(['PENDING','PROCESSING']),Job.source_id==source.id)
    if db.scalar(running):raise HTTPException(409,'Nguồn đang được xử lý. Chờ tác vụ hiện tại hoàn thành.')
    job=Job(source_id=source.id,document_id=doc.id if doc else None,kind=kind);db.add(job);db.flush()
    audit(db,user,'job.enqueue','job',job.id,{'kind':kind,'source_id':source.id});db.commit()
    if settings.job_execution_mode=='background':tasks.add_task(run_job,job.id)
    return data(job)

@app.get('/api/health')
def health():return {'status':'ok','version':'0.1.0','answer_revision':ANSWER_REVISION}

@app.get('/api/ready')
def ready(db=Depends(get_db)):
    try:db.execute(text('SELECT 1'))
    except Exception:raise HTTPException(503,'Cơ sở dữ liệu chưa sẵn sàng.')
    return {'status':'ready','database':'ok','model':'not_checked','answer_revision':ANSWER_REVISION}

login_attempts=defaultdict(deque)
@app.post('/api/auth/login')
def login(body:Login,request:Request,db=Depends(get_db)):
    key=request.client.host if request.client else 'unknown';t=time.monotonic();attempts=login_attempts[key]
    while attempts and t-attempts[0]>60:attempts.popleft()
    if len(attempts)>=10:raise HTTPException(429,'Đăng nhập quá nhiều lần. Thử lại sau một phút.')
    user=db.scalar(select(User).where(User.email==body.email.strip().lower()))
    if not user or not user.active or not check_password(body.password,user.password_hash):
        attempts.append(t);raise HTTPException(401,'Email hoặc mật khẩu không đúng.')
    attempts.clear()
    audit(db,user,'auth.login','user',user.id);db.commit()
    return {'access_token':token_for(user),'token_type':'bearer','user':data(user,('password_hash',))}
@app.get('/api/auth/me')
def me(user=Depends(current_user)):return data(user,('password_hash',))

@app.get('/api/users')
def users(user=Depends(admin),db=Depends(get_db)):
    return [data(u,('password_hash',)) for u in db.scalars(select(User).order_by(User.name)).all()]
@app.post('/api/users',status_code=201)
def add_user(body:UserCreate,user=Depends(admin),db=Depends(get_db)):
    email=body.email.strip().lower()
    if '@' not in email:raise HTTPException(422,'Email không hợp lệ.')
    if db.scalar(select(User).where(User.email==email)):raise HTTPException(409,'Email đã tồn tại.')
    u=User(email=email,name=body.name,password_hash=hash_password(body.password),role=body.role);db.add(u);db.flush()
    audit(db,user,'user.create','user',u.id,{'role':u.role});db.commit();return data(u,('password_hash',))
@app.patch('/api/users/{uid}')
def patch_user(uid:str,body:UserPatch,user=Depends(admin),db=Depends(get_db)):
    u=db.get(User,uid)
    if not u:raise HTTPException(404,'Không tìm thấy người dùng.')
    if uid==user.id and (body.active is False or body.role=='user'):raise HTTPException(409,'Không tự khóa hoặc hạ quyền tài khoản quản trị hiện tại.')
    for k,v in body.model_dump(exclude_none=True).items():setattr(u,k,v)
    audit(db,user,'user.update','user',u.id,body.model_dump(exclude_none=True))
    db.commit();return data(u,('password_hash',))

@app.get('/api/system')
def system(user=Depends(current_user)):
    return {'embedding_model':settings.embedding_model,'llm_model':settings.llm_model,'answer_engine':settings.answer_engine,'model_configured':settings.provider=='ollama' or bool(settings.provider_key),'model_provider':settings.provider,'database':engine.dialect.name,'chunk_size':settings.chunk_size,'overlap':settings.overlap,'top_k':settings.top_k,'config_version':settings.config_version,'answer_revision':ANSWER_REVISION,'wiki_hosts':list(settings.wiki_hosts),'retrieval_strategy':settings.retrieval_strategy,'retrieval_cache_seconds':settings.retrieval_cache_seconds,'freshness_days':settings.freshness_days,'job_execution_mode':settings.job_execution_mode}
@app.get('/api/stats')
def stats(user=Depends(current_user),db=Depends(get_db)):
    sources=[s for s in db.scalars(select(Source)).all() if user.role=='admin' or allowed_source(s,user)]
    source_map={s.id:s for s in sources}
    documents=[d for d in db.scalars(select(Document)).all() if d.source_id in source_map and (user.role=='admin' or allowed_document(d,source_map[d.source_id],user))]
    ids=[d.id for d in documents]
    chunks=db.scalar(select(func.count()).select_from(Chunk).join(Document,Document.id==Chunk.document_id).where(Chunk.document_id.in_(ids),Chunk.version==Document.version)) or 0
    return {'sources':len(sources),'documents':len(documents),'indexed':sum(d.status=='INDEXED' for d in documents),'chunks':chunks,'questions':db.scalar(select(func.count()).select_from(QueryRecord).where(QueryRecord.user_id==user.id))}

@app.get('/api/sources')
def sources(user=Depends(current_user),db=Depends(get_db)):
    rows=[s for s in db.scalars(select(Source).order_by(Source.created_at.desc())).all() if user.role=='admin' or allowed_source(s,user)]
    source_map={s.id:s for s in rows};counts=defaultdict(int)
    for d in db.scalars(select(Document).where(Document.source_id.in_(source_map))):
        if user.role=='admin' or allowed_document(d,source_map[d.source_id],user):counts[d.source_id]+=1
    return [{**data(s),'documents':counts[s.id]} for s in rows]
@app.post('/api/sources',status_code=201)
def add_source(body:SourceCreate,user=Depends(admin),db=Depends(get_db)):
    if body.source_type=='FILE' and body.sync_interval_minutes:raise HTTPException(422,'Chỉ nguồn WEB có lịch đồng bộ.')
    if body.source_type=='WEB':
        try:validate_url(body.location)
        except ValueError as exc:raise HTTPException(422,str(exc))
    row=Source(**body.model_dump());db.add(row);db.flush();audit(db,user,'source.create','source',row.id,{'source_type':row.source_type});db.commit();return data(row)
@app.get('/api/sources/{sid}')
def get_source(sid:str,user=Depends(current_user),db=Depends(get_db)):return data(source_access(db,sid,user))
@app.patch('/api/sources/{sid}')
def patch_source(sid:str,body:SourcePatch,user=Depends(admin),db=Depends(get_db)):
    row=source_access(db,sid,user)
    if row.source_type=='FILE' and body.sync_interval_minutes:raise HTTPException(422,'Chỉ nguồn WEB có lịch đồng bộ.')
    for k,v in body.model_dump(exclude_none=True).items():setattr(row,k,v)
    audit(db,user,'source.update','source',sid,{'fields':list(body.model_dump(exclude_none=True))})
    db.commit();return data(row)
@app.delete('/api/sources/{sid}',status_code=204)
def delete_source(sid:str,user=Depends(admin),db=Depends(get_db)):
    row=source_access(db,sid,user)
    if db.scalar(select(Job).where(Job.source_id==sid,Job.status.in_(['PENDING','PROCESSING']))):raise HTTPException(409,'Nguồn đang xử lý.')
    paths=[d.file_path for d in db.scalars(select(Document).where(Document.source_id==sid)) if d.file_path]
    audit(db,user,'source.delete','source',sid);db.delete(row);db.commit()
    for path in paths:Path(path).unlink(missing_ok=True)
@app.post('/api/sources/{sid}/sync',status_code=202)
def sync(sid:str,tasks:BackgroundTasks,user=Depends(admin),db=Depends(get_db)):
    src=source_access(db,sid,user)
    if src.source_type!='WEB':raise HTTPException(422,'Nguồn FILE sử dụng upload tài liệu.')
    if not src.enabled:raise HTTPException(409,'Nguồn đang tạm dừng.')
    return enqueue(db,src,None,'SYNC',tasks,user)
@app.get('/api/sources/{sid}/status')
def status(sid:str,user=Depends(admin),db=Depends(get_db)):
    source_access(db,sid,user)
    return [data(j) for j in db.scalars(select(Job).where(Job.source_id==sid).order_by(Job.created_at.desc()).limit(30))]

@app.get('/api/documents')
def documents(user=Depends(current_user),db=Depends(get_db)):
    counts=select(Chunk.document_id.label('did'),func.count().label('n')).join(Document,Document.id==Chunk.document_id).where(Chunk.version==Document.version).group_by(Chunk.document_id).subquery()
    rows=db.execute(select(Document,Source,func.coalesce(counts.c.n,0)).join(Source,Source.id==Document.source_id).outerjoin(counts,counts.c.did==Document.id).order_by(Document.created_at.desc())).all()
    return [{**data(d,('file_path',)),'chunks':count,'source_name':s.name} for d,s,count in rows if user.role=='admin' or allowed_document(d,s,user)]
@app.post('/api/documents',status_code=202)
async def upload(tasks:BackgroundTasks,file:UploadFile=File(...),source_id:str=Form(...),user=Depends(admin),db=Depends(get_db)):
    src=source_access(db,source_id,user)
    if src.source_type!='FILE' or not src.enabled:raise HTTPException(422,'Cần chọn nguồn FILE đang hoạt động.')
    if db.scalar(select(Job).where(Job.source_id==src.id,Job.status.in_(['PENDING','PROCESSING']))):raise HTTPException(409,'Nguồn đang xử lý. Vui lòng chờ trước khi upload.')
    name=Path((file.filename or '').replace('\\','/')).name[:200]
    ext=Path(name).suffix.lower()
    if ext not in ['.pdf','.docx','.txt']:raise HTTPException(422,'Chỉ nhận PDF, DOCX hoặc TXT.')
    path=settings.storage_dir/(str(uuid.uuid4())+ext);size=0;digest=hashlib.sha256()
    try:
        with path.open('wb') as out:
            while block:=await file.read(64*1024):
                size+=len(block)
                if size>settings.max_upload:raise HTTPException(413,'File vượt giới hạn dung lượng.')
                digest.update(block)
                out.write(block)
        if size==0:raise HTTPException(422,'File rỗng.')
        db.scalar(select(Source).where(Source.id==src.id).with_for_update())
        # Existing installations may not yet have raw file hashes; fill them lazily.
        from .ingestion import file_fingerprint
        for previous in db.scalars(select(Document).where(Document.source_id==src.id,Document.file_path!='')):
            previous_hash=previous.file_hash
            if not previous_hash and Path(previous.file_path).is_file():
                previous_hash=file_fingerprint(previous.file_path);previous.file_hash=previous_hash
            if previous_hash==digest.hexdigest():raise HTTPException(409,'File này đã có trong nguồn. Mở tài liệu hiện có để xử lý lại.')
        doc=Document(source_id=src.id,title=name,original_name=name,location=path.name,file_path=str(path),format=ext[1:].upper(),file_hash=digest.hexdigest())
        db.add(doc);db.flush()
        job=enqueue(db,src,doc,'INGEST',tasks,user)
        return {'document':doc_data(db,doc),'job':job}
    except Exception:
        db.rollback();path.unlink(missing_ok=True);raise
@app.get('/api/documents/{did}')
def document(did:str,user=Depends(current_user),db=Depends(get_db)):
    doc,_=doc_access(db,did,user);return doc_data(db,doc)
@app.patch('/api/documents/{did}')
def document_permission(did:str,body:DocumentPatch,user=Depends(admin),db=Depends(get_db)):
    doc,_=doc_access(db,did,user)
    for k,v in body.model_dump(exclude_none=True).items():setattr(doc,k,v)
    audit(db,user,'document.update','document',did,{'fields':list(body.model_dump(exclude_none=True))})
    db.commit();return doc_data(db,doc)
@app.get('/api/documents/{did}/download')
def download(did:str,user=Depends(current_user),db=Depends(get_db)):
    doc,_=doc_access(db,did,user)
    if not doc.file_path or not Path(doc.file_path).is_file():raise HTTPException(404,'Không có file gốc để tải.')
    return FileResponse(doc.file_path,filename=doc.original_name)
@app.get('/api/documents/{did}/chunks')
def chunks(did:str,user=Depends(current_user),db=Depends(get_db)):
    doc,_=doc_access(db,did,user)
    return [data(c,('embedding',)) for c in db.scalars(select(Chunk).where(Chunk.document_id==did,Chunk.version==doc.version).order_by(Chunk.chunk_index))]
@app.post('/api/documents/{did}/reprocess',status_code=202)
def reprocess(did:str,tasks:BackgroundTasks,user=Depends(admin),db=Depends(get_db)):
    doc,src=doc_access(db,did,user);return enqueue(db,src,doc,'INGEST',tasks,user)
@app.delete('/api/documents/{did}',status_code=204)
def delete_document(did:str,user=Depends(admin),db=Depends(get_db)):
    doc,_=doc_access(db,did,user)
    if db.scalar(select(Job).where(Job.source_id==doc.source_id,Job.status.in_(['PENDING','PROCESSING']))):raise HTTPException(409,'Nguồn đang xử lý.')
    path=doc.file_path;audit(db,user,'document.delete','document',did);db.delete(doc);db.commit()
    if path:Path(path).unlink(missing_ok=True)

@app.get('/api/jobs')
def jobs(user=Depends(admin),db=Depends(get_db)):
    return [{**data(j),'source_name':db.get(Source,j.source_id).name} for j in db.scalars(select(Job).order_by(Job.created_at.desc()).limit(100))]

@app.post('/api/jobs/{jid}/retry',status_code=202)
def retry_job(jid:str,tasks:BackgroundTasks,user=Depends(admin),db=Depends(get_db)):
    previous=db.get(Job,jid)
    if not previous:raise HTTPException(404,'Không tìm thấy tác vụ.')
    if previous.status not in ('FAILED','PARTIAL'):raise HTTPException(409,'Chỉ thử lại tác vụ lỗi hoặc hoàn thành một phần.')
    source=source_access(db,previous.source_id,user)
    if not source.enabled:raise HTTPException(409,'Nguồn đang tạm dừng.')
    doc=db.get(Document,previous.document_id) if previous.document_id else None
    return enqueue(db,source,doc,previous.kind,tasks,user)
@app.post('/api/query')
def ask(body:Question,user=Depends(current_user),db=Depends(get_db)):
    try:return query(db,user,body.question,body.top_k,body.source_ids,body.retrieval_only,body.conversation_id,body.followup_query_id)
    except ProviderError as exc:
        db.rollback();audit(db,user,'query.failed','user',user.id,{'error_type':'provider'});db.commit()
        raise HTTPException(503,str(exc))

@app.post('/api/query/stream')
async def ask_stream(body:Question,request:Request,credentials=Depends(bearer)):
    from .streaming import events
    # Release the authentication connection before the long-lived response.
    # The worker and each live policy check own separate short-lived sessions.
    with Session() as db:user=current_user(credentials,db)
    return StreamingResponse(events(user.id,body,request),media_type='text/event-stream',
        headers={'Cache-Control':'no-cache, no-store','X-Accel-Buffering':'no'})
@app.get('/api/history')
def history(user=Depends(current_user),db=Depends(get_db),limit:int=Query(default=100,ge=1,le=100)):
    rows=db.scalars(select(QueryRecord).where(QueryRecord.user_id==user.id).order_by(QueryRecord.created_at.desc(),QueryRecord.id.desc()))
    result=[]
    for row in rows:
        if record_allowed(row,db,user):result.append(data(row))
        if len(result)==limit:break
    return result

@app.get('/api/conversations')
def list_conversations(limit:int=Query(default=4,ge=1,le=100),user=Depends(current_user),db=Depends(get_db)):
    from .conversations import search
    return search(db,user,'',1,limit)['items']

@app.get('/api/conversations/search')
def search_conversations(q:str=Query(default='',max_length=300),page:int=Query(default=1,ge=1),page_size:int=Query(default=10,ge=1,le=50),user=Depends(current_user),db=Depends(get_db)):
    from .conversations import search
    return search(db,user,q,page,page_size)

@app.get('/api/conversations/{cid}')
def open_conversation(cid:str,user=Depends(current_user),db=Depends(get_db)):
    from .conversations import access,summary
    conversation,messages=access(db,cid,user)
    feedback={f.query_id:{'rating':f.rating,'comment':f.comment} for f in db.scalars(select(AnswerFeedback).where(AnswerFeedback.user_id==user.id,AnswerFeedback.query_id.in_([m.id for m in messages])))}
    return {**summary(conversation,messages),'messages':[{**data(m),'result':{**m.result,'feedback':feedback.get(m.id)}} for m in messages]}

@app.delete('/api/conversations/{cid}',status_code=204)
def delete_conversation(cid:str,user=Depends(current_user),db=Depends(get_db)):
    conversation=db.get(Conversation,cid)
    if not conversation or conversation.user_id!=user.id:raise HTTPException(404,'Không tìm thấy cuộc trò chuyện.')
    db.delete(conversation);db.commit()

@app.get('/api/history/search')
def search_history(q:str=Query(default='',max_length=300),page:int=Query(default=1,ge=1),page_size:int=Query(default=10,ge=1,le=50),user=Depends(current_user),db=Depends(get_db)):
    def fold(value):
        return ''.join(c for c in unicodedata.normalize('NFD',value.casefold().replace('đ','d')) if unicodedata.category(c)!='Mn')
    terms=fold(q).split();items=[];total=0;start=(page-1)*page_size
    rows=db.scalars(select(QueryRecord).where(QueryRecord.user_id==user.id).order_by(QueryRecord.created_at.desc(),QueryRecord.id.desc()))
    for row in rows:
        if not record_allowed(row,db,user):continue
        if terms and not all(term in fold(row.question+' '+row.answer) for term in terms):continue
        if start<=total<start+page_size:
            items.append({'id':row.id,'question':row.question,'answer_preview':row.answer[:240],'created_at':row.created_at,'no_answer':row.result.get('no_answer',False),'needs_clarification':row.result.get('needs_clarification',False)})
        total+=1
    return {'items':items,'total':total,'page':page,'page_size':page_size}

@app.get('/api/history/{rid}')
def get_history(rid:str,user=Depends(current_user),db=Depends(get_db)):
    row=db.get(QueryRecord,rid)
    if not row or not record_allowed(row,db,user):raise HTTPException(404,'Không tìm thấy cuộc trò chuyện.')
    return data(row)

@app.post('/api/history/{rid}/feedback')
def answer_feedback(rid:str,body:Feedback,user=Depends(current_user),db=Depends(get_db)):
    row=db.scalar(select(QueryRecord).where(QueryRecord.id==rid).with_for_update())
    if not row or not record_allowed(row,db,user):raise HTTPException(404,'Không tìm thấy câu trả lời được phép đánh giá.')
    feedback=db.scalar(select(AnswerFeedback).where(AnswerFeedback.query_id==rid))
    if not feedback:
        feedback=AnswerFeedback(query_id=rid,user_id=user.id,rating=body.rating);db.add(feedback)
    feedback.rating=body.rating;feedback.comment=body.comment.strip();feedback.updated_at=now()
    db.commit();return {'rating':feedback.rating,'comment':feedback.comment}
@app.delete('/api/history/{rid}',status_code=204)
def delete_history(rid:str,user=Depends(current_user),db=Depends(get_db)):
    row=db.get(QueryRecord,rid)
    if not row or row.user_id!=user.id:raise HTTPException(404,'Không tìm thấy câu hỏi.')
    db.delete(row);db.commit()
@app.get('/api/citations/{cid}')
def citation(cid:str,user=Depends(current_user),db=Depends(get_db)):
    chunk=db.get(Chunk,cid)
    if not chunk:raise HTTPException(404,'Nguồn trích dẫn không còn tồn tại.')
    doc,src=doc_access(db,chunk.document_id,user)
    return {**data(chunk,('embedding',)),'title':doc.title,'location':doc.location,'format':doc.format,'source_name':src.name,'last_synced_at':src.last_synced_at,'freshness_days':settings.freshness_days,'indexed_at':doc.indexed_at}

@app.get('/api/admin/usage')
def usage_summary(days:int=Query(default=30,ge=1,le=365),user=Depends(admin),db=Depends(get_db)):
    return usage(db,days)

@app.get('/api/admin/audit')
def audit_log(page:int=Query(default=1,ge=1),page_size:int=Query(default=25,ge=1,le=100),user=Depends(admin),db=Depends(get_db)):
    total=db.scalar(select(func.count()).select_from(AuditEvent))
    rows=db.execute(select(AuditEvent,User.name).outerjoin(User,User.id==AuditEvent.actor_id).order_by(AuditEvent.created_at.desc(),AuditEvent.id).offset((page-1)*page_size).limit(page_size))
    return {'items':[{**data(row),'actor_name':name} for row,name in rows],'total':total,'page':page,'page_size':page_size}

@app.get('/api/evaluations')
def evaluations(user=Depends(admin),db=Depends(get_db)):
    return [data(e) for e in db.scalars(select(Evaluation).order_by(Evaluation.created_at.desc()).limit(30))]
@app.post('/api/evaluations')
def evaluate(body:EvaluationRequest,user=Depends(admin),db=Depends(get_db)):
    from .rag import retrieve
    from .retrieval_sessions import fingerprint
    snapshot=fingerprint(db,user)
    rows=[];hits=[];recalls=[];chunk_hits=[];chunk_recalls=[]
    for case in body.cases:
        if not case.no_answer and not case.expected_document_ids:raise HTTPException(422,'Câu có đáp án cần expected_document_ids.')
        if case.no_answer and case.expected_document_ids:raise HTTPException(422,'Câu no-answer không có expected_document_ids.')
        if case.no_answer and case.expected_chunk_ids:raise HTTPException(422,'Câu no-answer không có expected_chunk_ids.')
        for did in case.expected_document_ids:doc_access(db,did,user)
        for cid in case.expected_chunk_ids:
            chunk=db.get(Chunk,cid)
            if not chunk:raise HTTPException(422,'Không tìm thấy chunk kỳ vọng.')
            doc,_=doc_access(db,chunk.document_id,user)
            if doc.id not in case.expected_document_ids or chunk.version!=doc.version:
                raise HTTPException(422,'Chunk kỳ vọng phải thuộc tài liệu kỳ vọng và phiên bản hiện tại.')
        try:found,timing=retrieve(db,user,case.question,body.top_k,strategy=body.strategy,use_cache=False)
        except ProviderError as exc:raise HTTPException(503,str(exc))
        expected=set(case.expected_document_ids);got={h['document_id'] for h in found};overlap=len(expected&got)
        if expected:hits.append(int(overlap>0));recalls.append(overlap/len(expected))
        expected_chunks=set(case.expected_chunk_ids);got_chunks={h['chunk_id'] for h in found}
        chunk_overlap=len(expected_chunks&got_chunks)
        if expected_chunks:
            chunk_hits.append(int(chunk_overlap>0));chunk_recalls.append(chunk_overlap/len(expected_chunks))
        rows.append({'question':case.question,'expected_document_ids':list(expected),'retrieved_document_ids':list(got),'hit':bool(overlap) if expected else None,'recall':overlap/len(expected) if expected else None,'expected_chunk_ids':list(expected_chunks),'retrieved_chunk_ids':list(got_chunks),'chunk_hit':bool(chunk_overlap) if expected_chunks else None,'chunk_recall':chunk_overlap/len(expected_chunks) if expected_chunks else None,'no_answer':case.no_answer,'latency_ms':timing})
    result={'hit_at_k':sum(hits)/len(hits) if hits else None,'recall_at_k':sum(recalls)/len(recalls) if recalls else None,'chunk_hit_at_k':sum(chunk_hits)/len(chunk_hits) if chunk_hits else None,'chunk_recall_at_k':sum(chunk_recalls)/len(chunk_recalls) if chunk_recalls else None,'chunk_labeled_cases':len(chunk_hits),'top_k':body.top_k,'answerable_cases':len(hits),'cases':rows,'config_version':settings.config_version,'scope':'retrieval-only','note':'No-answer, answer correctness và citation cần chấm riêng; lượt này chỉ đo retrieval.'}
    if fingerprint(db,user)!=snapshot:raise HTTPException(409,'Kho tri thức thay đổi trong lúc đánh giá. Vui lòng chạy lại.')
    result.update(retrieval_strategy=body.strategy,corpus_snapshot=snapshot,embedding_model=settings.embedding_model,answer_revision=ANSWER_REVISION)
    row=Evaluation(user_id=user.id,title=body.title,result=result);db.add(row);db.flush();audit(db,user,'evaluation.run','evaluation',row.id,{'cases':len(body.cases),'strategy':body.strategy});db.commit();return data(row)
