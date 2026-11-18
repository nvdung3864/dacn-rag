"""Read-only RAG experiments; outputs raw answers and an unfilled review sheet."""
import argparse
import csv
import hashlib
import json
import platform
import time
import unicodedata
from pathlib import Path
from sqlalchemy import select
from .config import settings,pipeline_key,ANSWER_REVISION
from .db import Session,engine
from .models import User,Document,Source,Chunk,now
from .security import allowed_document
from .questions import retrieval_question,clarification_for,unavailable_personal_answer
from .rag import retrieve,answer_from_context,continuation_context
from .retrieval_sessions import fingerprint
from .operations import percentile
from . import providers

def folded(value):return ''.join(c for c in unicodedata.normalize('NFKC',value).casefold() if c.isalnum())

def summarize(rows):
    summaries={}
    for variant in dict.fromkeys(r['variant'] for r in rows):
        records=[r for r in rows if r['variant']==variant]
        eligible=[r for r in records if r['expected_document_ids']]
        chunk_labeled=[r for r in eligible if r['expected_chunk_ids']]
        successful=[r for r in records if not r.get('error')]
        times=[r['latency_ms']['total_ms'] for r in successful]
        summaries[variant]={'cases':len(records),'errors':len(records)-len(successful),
            'validation_failures':sum(bool(r.get('validation_failed')) for r in records),
            'answerable_cases':len(eligible),'chunk_labeled_cases':len(chunk_labeled),
            'document_hit_at_k':sum(r['document_hit'] for r in eligible)/len(eligible) if eligible else None,
            'document_recall_at_k':sum(r['document_recall'] for r in eligible)/len(eligible) if eligible else None,
            'chunk_hit_at_k':sum(r['chunk_hit'] for r in chunk_labeled)/len(chunk_labeled) if chunk_labeled else None,
            'chunk_recall_at_k':sum(r['chunk_recall'] for r in chunk_labeled)/len(chunk_labeled) if chunk_labeled else None,
            'latency_p50_ms':percentile(times,.5),'latency_p95_ms':percentile(times,.95),
            'prompt_tokens':sum(r.get('token_usage',{}).get('prompt_tokens',0) or 0 for r in records),
            'completion_tokens':sum(r.get('token_usage',{}).get('completion_tokens',0) or 0 for r in records),
            'answer_accuracy':None,'citation_grounding':None,'human_review_required':True}
    return summaries

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',default='/evaluation/holdout-candidate-v1.json')
    parser.add_argument('--output',default='/results/benchmark.json')
    parser.add_argument('--variants',default='vector:5,vector_keyword:5')
    parser.add_argument('--answers',action='store_true',help='Call the LLM, otherwise compare retrieval only.')
    parser.add_argument('--limit',type=int,default=0)
    parser.add_argument('--allow-draft',action='store_true')
    args=parser.parse_args();path=Path(args.dataset);raw=path.read_bytes();dataset=json.loads(raw)
    if not dataset.get('reference_reviewed') and not args.allow_draft:raise SystemExit('Reference labels await independent review. Use --allow-draft for an explicitly provisional development run.')
    variants=[]
    for spec in args.variants.split(','):
        strategy,k=spec.split(':');k=int(k)
        if strategy not in ['vector','vector_keyword'] or not 1<=k<=20:raise SystemExit('Invalid strategy or top-k.')
        variants.append((strategy,k))
    destination=Path(args.output);destination.parent.mkdir(parents=True,exist_ok=True)
    cases=dataset['cases'][:args.limit or None]
    with Session() as db:
        user=db.scalar(select(User).where(User.active.is_(True),User.role=='admin').order_by(User.id))
        if not user:raise SystemExit('An existing active admin is required; no permissions are bypassed.')
        documents={}
        for item in dataset['corpus']:
            found=[d for d in db.scalars(select(Document).where(Document.original_name==item['file_name'],Document.status=='INDEXED',Document.pipeline==pipeline_key())) if allowed_document(d,db.get(Source,d.source_id),user)]
            if len(found)!=1:raise SystemExit('Expected exactly one indexed current-pipeline document: '+item['file_name'])
            d=found[0]
            if hashlib.sha256(Path(d.file_path).read_bytes()).hexdigest()!=item['sha256']:raise SystemExit('Corpus bytes changed: '+item['file_name'])
            documents[item['file_name']]=d
        source_ids=sorted({d.source_id for d in documents.values()})
        snap=fingerprint(db,user)
        chunk_rows=list(db.scalars(select(Chunk).where(Chunk.document_id.in_([d.id for d in documents.values()]))))
        chunk_rows=[c for c in chunk_rows if c.version==db.get(Document,c.document_id).version]
        report={'schema_version':1,'started_at':now(),'complete':False,'provisional':not dataset.get('reference_reviewed'),
            'dataset_id':dataset['id'],'dataset_sha256':hashlib.sha256(raw).hexdigest(),'corpus_snapshot':snap,
            'mode':'answers' if args.answers else 'retrieval-only',
            'configuration':{'answer_revision':ANSWER_REVISION,'config_version':settings.config_version,'embedding_model':settings.embedding_model,'embedding_dim':settings.embedding_dim,'llm_model':settings.llm_model,'answer_engine':settings.answer_engine,'provider':settings.provider,'chunk_size':settings.chunk_size,'overlap':settings.overlap,'min_similarity':settings.min_score,'context_chars':settings.context_chars,'ollama_num_ctx':settings.local_context,'ollama_num_gpu':settings.ollama_num_gpu,'python':platform.python_version(),'platform':platform.platform(),'database':engine.dialect.name},
            'notes':['No answer grades are invented. Structural citation checks are not semantic grounding.','Embedding vectors are shared across variants for a controlled retrieval comparison; embedding_batch_ms is recorded separately.','This run does not modify queries, feedback, documents, permissions or source data.'],
            'rows':[]}
        def save():
            report['summary']=summarize(report['rows'])
            temporary=destination.with_suffix('.tmp');temporary.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(destination)
        vectors={};embedding_started=time.perf_counter()
        # Batch across questions; do not repeatedly unload/reload the same embedding model.
        for start in range(0,len(cases),8):
            batch=cases[start:start+8]
            outputs=providers.embed([retrieval_question(c['question']) for c in batch])
            vectors.update({c['id']:v for c,v in zip(batch,outputs)})
            print(f'Embedded {min(start+8,len(cases))}/{len(cases)} questions',flush=True)
        report['embedding_batch_ms']=round((time.perf_counter()-embedding_started)*1000);save()
        for strategy,k in variants:
            for case in cases:
                if fingerprint(db,user)!=snap:raise SystemExit('Corpus or policy changed during the run; partial evidence was retained.')
                started=time.perf_counter();expected={documents[e['file_name']].id for e in case['expected_evidence']}
                expected_chunks={c.id for e in case['expected_evidence'] for c in chunk_rows if c.document_id==documents[e['file_name']].id and c.page==e['page'] and folded(e['quote']) in folded(c.text)}
                row={'case_id':case['id'],'variant':strategy+':'+str(k),'question':case['question'],'group':case['group'],
                    'expected_behavior':case['expected_behavior'],'expected_points':case['expected_points'],
                    'expected_evidence':case['expected_evidence'],'expected_document_ids':sorted(expected),'expected_chunk_ids':sorted(expected_chunks),
                    'document_hit':False,'document_recall':0.0,'chunk_hit':False,'chunk_recall':0.0,'retrieved_chunks':[],
                    'answer':None,'citations':[],'no_answer':None,'token_usage':{},'error':None}
                try:
                    clarification=clarification_for(case['question']);personal=unavailable_personal_answer(case['question'])
                    if args.answers and (clarification or personal):
                        hits=[];timing={'embedding_ms':0,'retrieval_ms':0};generation_ms=0
                        result={'answer':clarification or personal,'no_answer':True,'needs_clarification':bool(clarification),'citations':[],'token_usage':{}}
                    else:
                        hits,timing=retrieve(db,user,case['question'],k,source_ids,strategy=strategy,use_cache=False,query_vector=vectors[case['id']])
                        result={};generation_ms=0
                        if args.answers:result,generation_ms=answer_from_context(case['question'],continuation_context(db,hits))
                    got={h['document_id'] for h in hits};got_chunks={h['chunk_id'] for h in hits}
                    row.update({key:result[key] for key in ['answer','citations','no_answer','missing_information','needs_clarification','validation_failed','token_usage'] if key in result})
                    row.update(retrieved_chunks=hits,document_hit=bool(expected&got),document_recall=len(expected&got)/len(expected) if expected else 0,
                        chunk_hit=bool(expected_chunks&got_chunks),chunk_recall=len(expected_chunks&got_chunks)/len(expected_chunks) if expected_chunks else 0,
                        latency_ms={**timing,'generation_ms':generation_ms,'total_ms':round((time.perf_counter()-started)*1000)})
                except (providers.ProviderError,ValueError) as exc:
                    row['error']=str(exc);row['latency_ms']={'total_ms':round((time.perf_counter()-started)*1000)}
                report['rows'].append(row);save()
                print(f'{strategy}:{k} {case["id"]}: '+('ERROR' if row['error'] else 'saved'),flush=True)
        report.update(complete=True,finished_at=now());save()
        if args.answers:
            with destination.with_name(destination.stem+'-review.csv').open('w',encoding='utf-8-sig',newline='') as file:
                writer=csv.DictWriter(file,fieldnames=['case_id','variant','reviewer','correctness_0_2','completeness_0_2','citation_support_0_2','behavior_0_2','notes']);writer.writeheader()
                for row in report['rows']:writer.writerow({'case_id':row['case_id'],'variant':row['variant']})
    print('Experiment complete. Raw evidence and null (ungraded) answer metrics saved.',flush=True)

if __name__=='__main__':main()
