from typing import Literal
from pydantic import BaseModel,Field,field_validator

class Login(BaseModel):
    email:str=Field(min_length=3,max_length=254)
    password:str=Field(min_length=1,max_length=128)
class UserCreate(Login):
    name:str=Field(min_length=1,max_length=100)
    role:Literal['user','admin']='user'
    @field_validator('password')
    @classmethod
    def strong(cls,v):
        if len(v)<10:raise ValueError('Mật khẩu tối thiểu 10 ký tự.')
        return v
class UserPatch(BaseModel):
    active:bool|None=None
    role:Literal['user','admin']|None=None
class SourceCreate(BaseModel):
    name:str=Field(min_length=1,max_length=200)
    source_type:Literal['WEB','FILE']
    location:str=Field(default='',max_length=2048)
    access_scope:Literal['PUBLIC','RESTRICTED']='PUBLIC'
    allowed_roles:list[Literal['user','admin']]=[]
    sync_interval_minutes:int=Field(default=0,ge=0,le=43200)
class SourcePatch(BaseModel):
    name:str|None=Field(default=None,min_length=1,max_length=200)
    enabled:bool|None=None
    access_scope:Literal['PUBLIC','RESTRICTED']|None=None
    allowed_roles:list[Literal['user','admin']]|None=None
    sync_interval_minutes:int|None=Field(default=None,ge=0,le=43200)
class DocumentPatch(BaseModel):
    access_scope:Literal['INHERIT','PUBLIC','RESTRICTED']|None=None
    allowed_roles:list[Literal['user','admin']]|None=None
    category:str|None=Field(default=None,max_length=80)
    tags:list[str]|None=Field(default=None,max_length=20)
    @field_validator('tags')
    @classmethod
    def clean_tags(cls,value):
        if value is None:return value
        tags=list(dict.fromkeys(t.strip() for t in value if t.strip()))
        if any(len(t)>40 for t in tags):raise ValueError('Mỗi nhãn tối đa 40 ký tự.')
        return tags

class Feedback(BaseModel):
    rating:Literal[-1,1]
    comment:str=Field(default='',max_length=1000)
class Question(BaseModel):
    question:str=Field(min_length=2,max_length=3000)
    top_k:int=Field(default=5,ge=1,le=20)
    source_ids:list[str]=Field(default_factory=list,max_length=100)
    retrieval_only:bool=False
    conversation_id:str|None=Field(default=None,min_length=1,max_length=100)
    followup_query_id:str|None=Field(default=None,min_length=1,max_length=100)
    @field_validator('question')
    @classmethod
    def not_blank(cls,v):
        if len(v.strip())<2:raise ValueError('Câu hỏi không được để trống.')
        return v.strip()
class TestCase(BaseModel):
    question:str=Field(min_length=2,max_length=3000)
    expected_document_ids:list[str]=Field(default_factory=list,max_length=100)
    expected_chunk_ids:list[str]=Field(default_factory=list,max_length=100)
    no_answer:bool=False
class EvaluationRequest(BaseModel):
    title:str=Field(default='Thử nghiệm baseline',max_length=200)
    top_k:int=Field(default=5,ge=1,le=20)
    strategy:Literal['vector','vector_keyword']='vector_keyword'
    cases:list[TestCase]=Field(min_length=1,max_length=100)
