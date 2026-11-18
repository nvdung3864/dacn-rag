"""Live PostgreSQL contract test with deterministic providers, separate from LLM scoring."""
import argparse
import atexit
import json
import os
import re
import secrets
import subprocess
import sys
import shutil
import tempfile
from pathlib import Path
from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--create-database');parser.add_argument('--output');args=parser.parse_args()
    url=make_url(os.environ['DATABASE_URL'])
    if args.create_database:
        name=args.create_database
        if not re.fullmatch(r'rag_integration_test_[a-z0-9_]+',name):raise SystemExit('Only a dedicated rag_integration_test_* database may be created.')
        with create_engine(url,isolation_level='AUTOCOMMIT').connect() as db:db.execute(text('CREATE DATABASE '+name))
        url=url.set(database=name);os.environ['DATABASE_URL']=url.render_as_string(hide_password=False)
    if not url.database or not (url.database.endswith('_test') or url.database.startswith('rag_integration_test_')):raise SystemExit('Refusing to test a non-test database.')
    # A separate database must also use separate uploads, including when this
    # command is invoked inside the production API container.
    storage=tempfile.mkdtemp(prefix='rag-integration-')
    atexit.register(shutil.rmtree,storage,ignore_errors=True)
    os.environ.update(STORAGE_DIR=storage,JOB_EXECUTION_MODE='background',JWT_SECRET=secrets.token_urlsafe(40),MODEL_PROVIDER='openai',ANSWER_ENGINE='legacy')
    subprocess.run([sys.executable,'-m','alembic','upgrade','head'],check=True)
    from fastapi.testclient import TestClient
    from sqlalchemy import select,func
    from .main import app
    from .db import Session
    from .models import User,Chunk
    from .security import hash_password
    from . import providers
    from .config import settings
    def embed(texts):
        return [[1.,1. if 'private' in t else .1]+[0.]*(settings.embedding_dim-2) for t in texts]
    providers.embed=embed
    providers.generate=lambda q,c,**kwargs:({'answer':'Retrieved evidence. [S1]','source_markers':['S1'],'no_answer':False},{'total_tokens':0})
    password=secrets.token_urlsafe(20)
    with Session() as db:
        if db.scalar(select(func.count()).select_from(User)):raise SystemExit('Test database already has users; refusing to reuse it.')
        db.add_all([User(email='pg-admin@example.test',name='PG Admin',role='admin',password_hash=hash_password(password)),User(email='pg-reader@example.test',name='PG Reader',role='user',password_hash=hash_password(password))]);db.commit()
    checks=[]
    with TestClient(app) as client:
        def headers(email):
            response=client.post('/api/auth/login',json={'email':email,'password':password});assert response.status_code==200
            return {'Authorization':'Bearer '+response.json()['access_token']}
        admin=headers('pg-admin@example.test');reader=headers('pg-reader@example.test')
        ids=[]
        for scope,content in [('RESTRICTED',b'private database evidence'),('PUBLIC',b'public database evidence')]:
            response=client.post('/api/sources',headers=admin,json={'name':scope,'source_type':'FILE','access_scope':scope});assert response.status_code==201,response.text
            sid=response.json()['id'];ids.append(sid)
            response=client.post('/api/documents',headers=admin,data={'source_id':sid},files={'file':('fixture.txt',content,'text/plain')});assert response.status_code==202,response.text
        result=client.post('/api/query',headers=reader,json={'question':'database evidence','top_k':1});assert result.status_code==200,result.text
        result=result.json();assert len(result['retrieved_chunks'])==1 and result['retrieved_chunks'][0]['source_id']==ids[1]
        checks.append('pgvector cosine and permission SQL before top-k')
        again=client.post('/api/query',headers=reader,json={'question':'database evidence','top_k':1,'retrieval_only':True}).json();assert again['retrieval_cache_hit']
        checks.append('persisted retrieval cache on PostgreSQL')
        assert client.patch('/api/sources/'+ids[1],headers=admin,json={'access_scope':'RESTRICTED','allowed_roles':[]}).status_code==200
        revoked=client.post('/api/query',headers=reader,json={'question':'database evidence','top_k':1,'retrieval_only':True}).json();assert not revoked['retrieved_chunks'] and not revoked['retrieval_cache_hit']
        assert client.get('/api/conversations/'+result['conversation_id'],headers=reader).status_code==404
        checks.append('revocation invalidates cache and conversation access')
    result={'passed':True,'database':'isolated PostgreSQL','provider':'deterministic test doubles','checks':checks}
    if args.output:Path(args.output).write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result))
if __name__=='__main__':main()
