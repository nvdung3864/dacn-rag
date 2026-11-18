"""Real HTTP + PostgreSQL + Ollama checks, only against the isolated QA stack."""
import argparse
import hashlib
import json
import secrets
import time
from pathlib import Path
import httpx
from sqlalchemy import select
from .db import Session
from .models import User,Source,Document,Job
from .security import hash_password
from .config import settings,ANSWER_REVISION

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--corpus',default='/corpus');parser.add_argument('--output',default='/results/acceptance.json')
    args=parser.parse_args();checks=[]
    # A mount exclusive to compose.acceptance.yml prevents accidental production seeding.
    if not Path(args.corpus).is_dir() or not Path('/results').is_dir():raise SystemExit('Chỉ chạy trong stack compose.acceptance.yml có /corpus và /results.')
    password=secrets.token_urlsafe(24)
    with Session() as db:
        admin=db.scalar(select(User).where(User.email=='acceptance-admin@example.test'))
        if not admin:
            admin=User(email='acceptance-admin@example.test',name='Acceptance Admin',role='admin',password_hash=hash_password(password));db.add(admin)
        else:admin.password_hash=hash_password(password)
        db.commit()
    client=httpx.Client(base_url='http://127.0.0.1:8000',timeout=650)
    def check(name,condition):
        checks.append({'check':name,'passed':bool(condition)})
        if not condition:raise AssertionError(name)
        print('PASS '+name,flush=True)
    def login(email,secret):
        response=client.post('/api/auth/login',json={'email':email,'password':secret});response.raise_for_status()
        return {'Authorization':'Bearer '+response.json()['access_token']}
    def call(method,path,headers,**kwargs):
        response=client.request(method,'/api'+path,headers=headers,**kwargs)
        if response.status_code>=400:raise RuntimeError(f'{method} {path}: HTTP {response.status_code}: {response.json().get("detail")}')
        return response.json() if response.content else None
    def wait_job(jid):
        started=time.monotonic()
        while time.monotonic()-started<600:
            rows=call('GET','/jobs',ah);job=next(j for j in rows if j['id']==jid)
            if job['status'] in ['SUCCEEDED','PARTIAL','FAILED']:return job
            time.sleep(1)
        raise TimeoutError('Job did not finish within 600s.')
    ah=login('acceptance-admin@example.test',password)
    reader_email='acceptance-reader-'+secrets.token_hex(4)+'@example.test'
    call('POST','/users',ah,json={'name':'Acceptance Reader','email':reader_email,'password':password,'role':'user'})
    rh=login(reader_email,password)
    output={'answer_revision':ANSWER_REVISION,'provider':settings.provider,'embedding_model':settings.embedding_model,'llm_model':settings.llm_model,'checks':checks,'success':False}
    try:
        check('database_ready',client.get('/api/ready').status_code==200)
        check('anonymous_denied',client.get('/api/documents').status_code==401)
        check('reader_admin_route_denied',client.get('/api/admin/audit',headers=rh).status_code==403)
        for old in call('GET','/sources',ah):
            if old['name'] in ['Acceptance public fixture','Acceptance private fixture']:
                call('DELETE','/sources/'+old['id'],ah)
        public=call('POST','/sources',ah,json={'name':'Acceptance public fixture','source_type':'FILE'})['id']
        private=call('POST','/sources',ah,json={'name':'Acceptance private fixture','source_type':'FILE','access_scope':'RESTRICTED'})['id']
        def upload(sid,name,content):
            return call('POST','/documents',ah,data={'source_id':sid},files={'file':(name,content,'application/octet-stream')})
        text='Thông tin thử nghiệm công khai: hệ thống tiếp nhận PDF, DOCX và TXT.'
        uploaded=upload(public,'public.txt',text.encode());did=uploaded['document']['id']
        check('worker_indexes_public_text',wait_job(uploaded['job']['id'])['status']=='SUCCEEDED')
        secret=upload(private,'private.txt','Thông tin thử nghiệm bí mật: mã riêng là SECRET_ACCEPTANCE_ONLY.'.encode())
        check('worker_indexes_private_text',wait_job(secret['job']['id'])['status']=='SUCCEEDED')
        secretid=secret['document']['id'];secretchunk=call('GET','/documents/'+secretid+'/chunks',ah)[0]['id']
        for suffix in ['', '/chunks','/download']:
            check('reader_private_document'+(suffix or '_detail')+'_denied',client.get('/api/documents/'+secretid+suffix,headers=rh).status_code==404)
        check('private_citation_denied',client.get('/api/citations/'+secretchunk,headers=rh).status_code==404)
        check('duplicate_upload_rejected',client.post('/api/documents',headers=ah,data={'source_id':public},files={'file':('renamed.txt',text.encode(),'text/plain')}).status_code==409)
        question='Những định dạng nào được chấp nhận trong thông tin thử nghiệm công khai?'
        a=call('POST','/query',rh,json={'question':question,'top_k':1,'source_ids':[public,private],'retrieval_only':True})
        b=call('POST','/query',rh,json={'question':question,'top_k':1,'source_ids':[public,private],'retrieval_only':True})
        check('permission_filter_applied_before_topk',len(a['retrieved_chunks'])==1 and a['retrieved_chunks'][0]['document_id']==did)
        check('retrieval_session_reused',b['retrieval_cache_hit'] and a['retrieval_session_id']==b['retrieval_session_id'])
        answer=call('POST','/query',rh,json={'question':question,'top_k':1,'source_ids':[public,private]})
        check('real_model_answer_has_permitted_citation',bool(answer['citations']) and all(c['document_id']==did for c in answer['citations']))
        call('POST','/history/'+answer['query_id']+'/feedback',rh,json={'rating':1,'comment':'Isolated acceptance check'})
        check('feedback_saved',call('GET','/conversations/'+answer['conversation_id'],rh)['messages'][0]['result']['feedback']['rating']==1)
        call('PATCH','/documents/'+did,ah,json={'category':'Kiểm thử','tags':['nghiệm thu']})
        check('document_labels_saved',call('GET','/documents/'+did,ah)['tags']==['nghiệm thu'])
        call('PATCH','/sources/'+public,ah,json={'access_scope':'RESTRICTED','allowed_roles':[]})
        revoked=call('POST','/query',rh,json={'question':question,'top_k':1,'source_ids':[public,private],'retrieval_only':True})
        check('revoked_cache_not_reused',not revoked['retrieval_cache_hit'] and not revoked['retrieved_chunks'])
        check('revoked_history_denied',client.get('/api/conversations/'+answer['conversation_id'],headers=rh).status_code==404)
        check('revoked_old_citation_denied',client.get('/api/citations/'+answer['citations'][0]['chunk_id'],headers=rh).status_code==404)
        for sid in [public,private]:call('DELETE','/sources/'+sid,ah)
        with Session() as db:
            corpus=db.scalar(select(Source).where(Source.name=='Acceptance PDF corpus'))
        sid=corpus.id if corpus else call('POST','/sources',ah,json={'name':'Acceptance PDF corpus','source_type':'FILE'})['id']
        known={d['file_hash']:d for d in call('GET','/documents',ah) if d['source_id']==sid}
        corpus_records=[]
        for path in sorted(Path(args.corpus).glob('*.pdf')):
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            if digest in known:document=known[digest]
            else:
                uploaded=upload(sid,path.name,path.read_bytes());job=wait_job(uploaded['job']['id'])
                check('pdf_indexed_'+path.name,job['status']=='SUCCEEDED');document=uploaded['document']
            corpus_records.append({'file_name':path.name,'sha256':digest,'document_id':document['id']})
        check('pdf_corpus_has_three_documents',len(corpus_records)==3)
        output['corpus']=corpus_records;output['success']=True
        check('audit_events_present',call('GET','/admin/audit',ah)['total']>0)
    finally:
        destination=Path(args.output);destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8');client.close()
    print('Acceptance evidence saved; credentials were not written to the report.',flush=True)

if __name__=='__main__':main()
