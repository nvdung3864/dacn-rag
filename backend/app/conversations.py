import re
import unicodedata
from fastapi import HTTPException
from sqlalchemy import select
from .models import Conversation,QueryRecord,Document,Source
from .security import allowed_document
from .questions import normalize_question,annual_language_requirement,requests_explanation


def records(db,conversation_id):
    return list(db.scalars(select(QueryRecord).where(QueryRecord.conversation_id==conversation_id).order_by(QueryRecord.created_at,QueryRecord.id)))


def record_visible(db,record,user):
    if record.user_id!=user.id:return False
    for hit in record.result.get('retrieved_chunks',[]):
        document=db.get(Document,hit['document_id']);source=db.get(Source,hit['source_id'])
        if not document or not source or not allowed_document(document,source,user):return False
    return True


def access(db,conversation_id,user,lock=False):
    statement=select(Conversation).where(Conversation.id==conversation_id,Conversation.user_id==user.id)
    if lock:statement=statement.with_for_update()
    conversation=db.scalar(statement)
    if not conversation:raise HTTPException(404,'Không tìm thấy cuộc trò chuyện.')
    messages=records(db,conversation_id)
    if not all(record_visible(db,m,user) for m in messages):raise HTTPException(404,'Cuộc trò chuyện có dữ liệu không còn được phép truy cập.')
    return conversation,messages


def summary(conversation,messages):
    last=messages[-1] if messages else None
    return {'id':conversation.id,'title':conversation.title,'question':conversation.title,
            'answer_preview':last.answer[:240] if last else '',
            'created_at':conversation.created_at,'updated_at':conversation.updated_at,
            'message_count':len(messages),'no_answer':last.result.get('no_answer',False) if last else False,
            'needs_clarification':last.result.get('needs_clarification',False) if last else False}


def search(db,user,q,page,page_size):
    def fold(text):return ''.join(c for c in unicodedata.normalize('NFD',text.casefold().replace('đ','d')) if unicodedata.category(c)!='Mn')
    terms=fold(q).split();matches=[]
    for conversation in db.scalars(select(Conversation).where(Conversation.user_id==user.id).order_by(Conversation.updated_at.desc(),Conversation.id.desc())):
        messages=records(db,conversation.id)
        if not messages:continue
        if not all(record_visible(db,m,user) for m in messages):continue
        content=fold(conversation.title+' '+' '.join(m.question+' '+m.answer for m in messages))
        if all(term in content for term in terms):matches.append(summary(conversation,messages))
    start=(page-1)*page_size
    return {'items':matches[start:start+page_size],'total':len(matches),'page':page,'page_size':page_size}


def short_context_question(question):
    text=normalize_question(question)
    return bool(re.fullmatch(r'(?:k(?:hóa)?\s*)?(?:20)?\d{2}[.!?]*',text)
                or re.fullmatch(r'(?:năm|đợt)\s+(?:thứ\s+)?[1-4](?:\s+thì sao)?[.!?]*',text))


def resolve_question(question,messages):
    from . import providers
    text=normalize_question(question)
    if not messages:
        if short_context_question(question):
            return question,'Bạn muốn hỏi thông tin gì về khóa/năm học hoặc đợt này? Hãy nêu chủ đề để mình tra đúng tài liệu nhé.'
        return question,None
    previous=messages[-1].result.get('resolved_question') or messages[-1].question
    if re.fullmatch(r'(?:giải thích|nói rõ|làm rõ|phân tích)(?:\s+(?:thêm|kỹ|chi tiết|hơn|giúp|mình|đi|nhé|ạ))*[.!?]*',text):
        return previous,None
    cohort=re.fullmatch(r'(?:k(?:hóa)?\s*)?((?:20)?\d{2})[.!?]*',text)
    if cohort:
        value=cohort[1] if len(cohort[1])==4 else '20'+cohort[1]
        topic=re.sub(r'\bkhóa\s+\d{2,4}\b|\bk\d{2}\b','',previous,flags=re.I).strip(' ;')
        return topic+f'; khóa {value}',None
    score=re.fullmatch(r'(?:còn\s+)?(\d+(?:[.,]\d+)?)(?:\s*(?:điểm|chấm))?(?:\s+thì sao)?[?!.]*',text)
    certificate=re.search(r'\b(vstep|ielts|toeic|vnu[ -]?ept|toefl(?: ibt)?)\s+\d+(?:[.,]\d+)?(?:\s+chấm)?',previous,re.I)
    if score and certificate:
        return previous[:certificate.start()]+certificate[1]+' '+score[1]+previous[certificate.end():],None
    phase=re.fullmatch(r'(?:còn\s+)?đợt\s+(\d+)(?:\s+thì sao)?[?!.]*',text)
    if phase and re.search(r'\bđợt\s+\d+\b',previous,re.I):
        return re.sub(r'\bđợt\s+\d+\b','đợt '+phase[1],previous,flags=re.I),None
    if annual_language_requirement(previous):
        year=re.fullmatch(r'(?:còn\s+)?năm\s+(?:thứ\s+)?([1-4]|nhất|hai|ba|tư)(?:\s+thì sao)?[.!?]*',text)
        if year:
            topic=re.sub(r'năm\s+(?:thứ\s+)?(?:[1-4]|nhất|hai|ba|tư)\b','',previous,flags=re.I)
            return topic+f'; chuẩn ngoại ngữ năm thứ {year[1]}',None
    latest=messages[-1]
    if latest.result.get('needs_clarification') and re.fullmatch(r'(?:vstep|ielts|toeic|toefl(?: ibt)?|vnu[ -]?ept)',text):
        return question.strip()+' '+previous,None
    if annual_language_requirement(text):return question,None
    if not requests_explanation(text) and re.search(r'toeic|ielts|vstep|ngoại ngữ|anh văn',text) and re.search(r'đồ án chuyên ngành|(?:đồ án|luận văn|khóa luận) tốt nghiệp',text):
        return question,None
    if not requests_explanation(text) and re.search(r'\b(?:điều kiện|quy trình|học phí|thời tiết|mã số sinh viên)\b',text) and len(text.split())>=6:
        return question,None
    try:
        resolved=providers.resolve_followup(question,messages[-6:])
    except providers.ProviderError:
        return question,'Mình chưa xác định được câu này nối với nội dung nào. Bạn nói rõ đối tượng hoặc điều kiện muốn hỏi tiếp nhé.'
    if normalize_question(resolved)==text and requests_explanation(text):
        contextual=question+'\nChủ đề đang trao đổi: '+previous
        if len(contextual)<=3000:return contextual,None
        return question,'Bạn nêu rõ đối tượng trong phần muốn giải thích thêm để mình tra đúng tài liệu nhé.'
    if normalize_question(resolved)==text and re.search(r'thì sao|còn|vậy|cái đó|cái này|môn đó|môn này',text):
        return question,'Mình chưa nối được đối tượng trong câu này với nội dung trước. Bạn cho biết rõ điều muốn hỏi tiếp nhé.'
    return resolved,None
