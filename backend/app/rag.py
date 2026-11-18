import math,re,time
from fastapi import HTTPException
from sqlalchemy import select,or_,String,func
from .models import Chunk,Source,Document,QueryRecord,Conversation,User,now
from .security import allowed_document
from .config import settings,pipeline_key,ANSWER_REVISION
from . import providers
from .questions import normalize_question,retrieval_question,annual_language_requirement,clarification_for,only_repeats_question,unavailable_personal_answer,requests_explanation
from .ranking import rerank
from .structured_answers import structured_answer
from .answer_contract import requirements_for,missing_answer

def serialize_chunk(chunk,doc,source,score):
    return {'chunk_id':chunk.id,'document_id':doc.id,'source_id':source.id,'title':doc.title,'source_name':source.name,'location':doc.location,'format':doc.format,'page':chunk.page,'section':chunk.section,'text':chunk.text,'score':round(score,5),'version':chunk.version,'last_synced_at':source.last_synced_at,'indexed_at':doc.indexed_at,'freshness_days':settings.freshness_days}

def clean_answer_citations(answer):
    answer=re.sub(r'\s*\[S\d+\]','',answer)
    return re.sub(r'[ \t]+([.,;:!?])',r'\1',answer).strip()

def continuation_context(db,hits):
    expanded=[];seen=set()
    for hit in hits:
        text=hit.get('text','').lstrip()
        current=db.get(Chunk,hit['chunk_id'])
        if text and text[0].islower() and current and current.chunk_index>0:
            row=db.execute(select(Chunk,Document,Source).join(Document,Document.id==Chunk.document_id).join(Source,Source.id==Chunk.source_id).where(
                Chunk.document_id==current.document_id,Chunk.version==current.version,Chunk.chunk_index==current.chunk_index-1)).first()
            if row:
                chunk,document,source=row
                if chunk.id not in seen:
                    expanded.append(serialize_chunk(chunk,document,source,hit['score']))
                    seen.add(chunk.id)
        if hit['chunk_id'] not in seen:
            expanded.append(hit);seen.add(hit['chunk_id'])
    return expanded

def retrieve(db,user,question,top_k,source_ids=None,*,strategy=None,use_cache=True,query_vector=None):
    from . import retrieval_sessions as sessions
    started=time.perf_counter();search_question=retrieval_question(question)
    strategy=strategy or settings.retrieval_strategy
    if strategy not in ('vector','vector_keyword'):raise ValueError('Chiến lược retrieval không hợp lệ.')
    cache_key=snapshot=None
    if use_cache and settings.retrieval_cache_seconds>0:
        cache_key=sessions.key_for(search_question,top_k,source_ids,strategy);snapshot=sessions.fingerprint(db,user)
        saved=sessions.load(db,user,cache_key,snapshot)
        if saved:return saved.hits,{'embedding_ms':0,'retrieval_ms':round((time.perf_counter()-started)*1000),'retrieval_cache_hit':True,'retrieval_session_id':saved.id}
    q=query_vector if query_vector is not None else providers.embed([search_question])[0]
    embedded=time.perf_counter()
    candidate_count=min(80,max(top_k,top_k*4))
    stmt=select(Chunk,Document,Source).join(Document,Document.id==Chunk.document_id).join(Source,Source.id==Chunk.source_id).where(Source.enabled.is_(True),Document.status=='INDEXED',Chunk.version==Document.version,Document.pipeline==pipeline_key())
    if source_ids:stmt=stmt.where(Source.id.in_(source_ids))
    if user.role!='admin':
        # Permissions are applied by SQL before top-k selection, never after LIMIT.
        stmt=stmt.where(or_(Source.access_scope=='PUBLIC',Source.allowed_roles.cast(String).contains('"'+user.role+'"')),or_(Document.access_scope.in_(['PUBLIC','INHERIT']),Document.allowed_roles.cast(String).contains('"'+user.role+'"')))
    if db.bind.dialect.name=='postgresql':
        stmt=stmt.where(func.vector_dims(Chunk.embedding)==settings.embedding_dim)
        distance=Chunk.embedding.cosine_distance(q)
        rows=db.execute(stmt.add_columns(distance).order_by(distance,Chunk.id).limit(candidate_count)).all()
        hits=[serialize_chunk(c,d,s,1-float(dist)) for c,d,s,dist in rows]
    else:
        # SQLite is an explicit development/test fallback; PostgreSQL uses pgvector.
        def cosine(v):
            return sum(a*b for a,b in zip(q,v))/(math.sqrt(sum(a*a for a in q))*math.sqrt(sum(b*b for b in v)))
        candidates=[(cosine(c.embedding),c,d,s) for c,d,s in db.execute(stmt).all() if len(c.embedding)==len(q) and allowed_document(d,s,user)]
        candidates.sort(key=lambda x:(-x[0],x[1].id))
        hits=[serialize_chunk(c,d,s,score) for score,c,d,s in candidates[:candidate_count]]
    if strategy=='vector':hits=hits[:top_k]
    elif annual_language_requirement(question):
        from .annual_requirements import requirements,requested_year
        wanted=requested_year(question)
        coverage={h['chunk_id']:{r['year'] for r in requirements(h['text'],h['title']) if not wanted or r['year']==wanted} for h in hits}
        hits=rerank(search_question,[h for h in hits if coverage[h['chunk_id']]],len(hits))
        selected=[];covered=set()
        while hits and len(selected)<top_k:
            index=max(range(len(hits)),key=lambda i:(len(coverage[hits[i]['chunk_id']]-covered),-i))
            hit=hits.pop(index);selected.append(hit);covered.update(coverage[hit['chunk_id']])
        hits=selected
    else:hits=rerank(search_question,hits,top_k)
    finished=time.perf_counter()
    session=sessions.save(db,user,cache_key,snapshot,hits) if cache_key else None
    return hits,{'embedding_ms':round((embedded-started)*1000),'retrieval_ms':round((finished-embedded)*1000),'retrieval_cache_hit':False,'retrieval_session_id':session.id if session else None}

def answer_from_context(question,hits,dialogue=None,current_question=None):
    personal=unavailable_personal_answer(question)
    if personal:
        return {'answer':personal,'citations':[],'no_answer':True,'token_usage':{}},0
    clarification=clarification_for(question)
    if clarification:
        return {'answer':clarification,'citations':[],'no_answer':True,'needs_clarification':True,'token_usage':{}},0
    eligible=[h for h in hits if h['score']>=settings.min_score]
    # Character budget bounds the request before sending it to the model.
    context=[];remaining=settings.context_chars
    for hit in eligible:
        if remaining<=0:break
        copy={**hit,'text':hit['text'][:remaining]};remaining-=len(copy['text']);context.append(copy)
    if not context:
        requirements=requirements_for(current_question or question)
        answer=missing_answer(requirements,question) if requirements else {'answer':'Chưa tìm thấy đủ thông tin trong các tài liệu được phép truy cập.','no_answer':True}
        return {**answer,'citations':[],'token_usage':{}},0
    explanation=requests_explanation(current_question or question)
    started=time.perf_counter();obj=None if explanation or settings.answer_engine=='grounded' else structured_answer(question,context);usage={}
    if obj is not None and len(requirements_for(current_question or question))>1:obj=None
    if obj is not None and any(r['kind']=='verdict' for r in requirements_for(current_question or question)) and not re.match(r'^(?:Có|Không|Đúng|Sai)\b',obj['answer']):obj=None
    if obj is None:
        if dialogue:obj,usage=providers.generate(question,context,dialogue=dialogue,current_question=current_question or question)
        else:obj,usage=providers.generate(question,context)
    if explanation and dialogue and not obj['no_answer'] and any(only_repeats_question(obj['answer'],m['answer']) for m in dialogue[-2:]):
        return {'answer':'Các đoạn nguồn hiện có chưa cung cấp thêm chi tiết cho yêu cầu này. Mình chưa có căn cứ để giải thích thêm ngoài nội dung đã trả lời.','citations':[],'no_answer':True,'token_usage':usage},round((time.perf_counter()-started)*1000)
    if not obj['no_answer'] and only_repeats_question(obj['answer'],question):
        return {'answer':'Chưa tìm thấy đủ thông tin trong các tài liệu được phép truy cập.','citations':[],'no_answer':True,'token_usage':usage},round((time.perf_counter()-started)*1000)
    coverage={k:obj[k] for k in ('missing_information','validation_failed') if k in obj}
    if obj['no_answer'] and (settings.answer_engine!='grounded' or not obj['source_markers']):return {'answer':obj['answer'],'citations':[],'no_answer':True,'token_usage':usage,**coverage},round((time.perf_counter()-started)*1000)
    claimed=obj['source_markers']
    inline=re.findall(r'\[(S\d+)\]',obj['answer'])
    if not claimed or set(claimed)!=set(inline):raise providers.ProviderError('Câu trả lời thiếu hoặc không khớp citation. Vui lòng thử lại.')
    citations=[]
    for marker in dict.fromkeys(claimed):
        if not isinstance(marker,str) or not re.fullmatch(r'S[1-9]\d*',marker) or int(marker[1:])>len(context):
            raise providers.ProviderError('LLM viện dẫn nguồn ngoài context. Kết quả đã bị chặn.')
        citations.append({k:v for k,v in {**context[int(marker[1:])-1],'marker':marker,'supporting_quotes':[e['quote'] for e in obj.get('supporting_evidence',[]) if e['source']==marker]}.items() if k!='score'})
    return {'answer':clean_answer_citations(obj['answer']),'citations':citations,'no_answer':obj['no_answer'],'token_usage':usage,**coverage},round((time.perf_counter()-started)*1000)

def query(db,user,question,top_k,source_ids=None,retrieval_only=False,conversation_id=None,followup_query_id=None,*,on_context=None):
    from .conversations import access,resolve_question
    started=time.perf_counter()
    conversation=None;messages=[]
    if conversation_id:conversation,messages=access(db,conversation_id,user,lock=True)
    if followup_query_id:
        reference=next((m for m in messages if m.id==followup_query_id),None)
        if not reference:raise HTTPException(404,'Không tìm thấy lượt trả lời trong cuộc trò chuyện này.')
        if retrieval_only or not requests_explanation(question):raise HTTPException(422,'Tham chiếu lượt trả lời chỉ dùng cho yêu cầu giải thích thêm.')
        messages=messages[:messages.index(reference)+1]
        resolved=reference.result.get('resolved_question') or reference.question;followup_clarification=None
    else:resolved,followup_clarification=resolve_question(question,messages) if not retrieval_only else (question,None)
    if len(resolved)>3000:resolved=resolved[-3000:]
    if not retrieval_only and (followup_clarification or clarification_for(resolved) or unavailable_personal_answer(resolved)):
        hits=[];timing={'embedding_ms':0,'retrieval_ms':0}
    else:
        hits,timing=retrieve(db,user,resolved,top_k,source_ids)
    if on_context:on_context(hits)
    result={'answer':'','citations':[],'no_answer':False,'token_usage':{}};generation_ms=0
    if followup_clarification:
        result={'answer':followup_clarification,'citations':[],'no_answer':True,'needs_clarification':True,'token_usage':{}}
    elif not retrieval_only:
        dialogue=[{'question':m.question,'answer':m.answer} for m in messages[-2:]]
        result,generation_ms=answer_from_context(resolved,continuation_context(db,hits),dialogue=dialogue or None,current_question=question)
    # A model call can take minutes. Recheck live policy before publishing context
    # selected earlier, including when the user was demoted during generation.
    from .stream_support import HOOK,GenerationCancelled
    hook=HOOK.get()
    if hook and hook[1].is_set():raise GenerationCancelled()
    current=db.scalar(select(User).where(User.id==user.id).execution_options(populate_existing=True))
    if not current or not current.active:raise HTTPException(401,'Tài khoản không còn hoạt động.')
    for did in {h['document_id'] for h in hits+result.get('citations',[])}:
        document=db.scalar(select(Document).where(Document.id==did).execution_options(populate_existing=True))
        source=db.scalar(select(Source).where(Source.id==document.source_id).execution_options(populate_existing=True)) if document else None
        if not document or not source or not allowed_document(document,source,current):
            raise HTTPException(409,'Quyền truy cập hoặc nguồn đã thay đổi trong lúc trả lời. Vui lòng hỏi lại.')
    result.update({'resolved_question':resolved,'source_ids':source_ids or [],'retrieved_chunks':hits,
        'latency_ms':{k:timing.get(k,0) for k in ('embedding_ms','retrieval_ms')},
        'retrieval_cache_hit':timing.get('retrieval_cache_hit',False),'retrieval_session_id':timing.get('retrieval_session_id'),
        'retrieved_at':now(),'retrieval_strategy':settings.retrieval_strategy,'followup_query_id':followup_query_id,
        'config_version':settings.config_version,'answer_revision':ANSWER_REVISION,'answer_engine':settings.answer_engine,'normalized_question':normalize_question(resolved),'embedding_model':settings.embedding_model,'llm_model':settings.llm_model,'top_k':top_k})
    result['latency_ms'].update(generation_ms=generation_ms,total_ms=round((time.perf_counter()-started)*1000))
    if not retrieval_only:
        if conversation is None:
            conversation=Conversation(user_id=user.id,title=question[:120]);db.add(conversation);db.flush()
        conversation.updated_at=now()
        row=QueryRecord(user_id=user.id,conversation_id=conversation.id,question=question,answer=result['answer'],result=result)
        db.add(row);db.flush();result.update(query_id=row.id,conversation_id=conversation.id);row.result={**result};db.commit()
    else:db.commit()
    return result

def record_allowed(record,db,user):
    if record.user_id!=user.id:return False
    for c in record.result.get('retrieved_chunks',[]):
        doc=db.get(Document,c['document_id']);source=db.get(Source,c['source_id'])
        if not doc or not source or not allowed_document(doc,source,user):return False
    return True
