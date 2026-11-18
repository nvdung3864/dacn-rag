"""Reindex existing local files after changing extraction or embedding identity.

Old versions remain in the database; each document commits independently.
Run with a single backend worker and no concurrent ingestion jobs.
"""
import json
from sqlalchemy import select
from .db import Session
from .models import Document, Source, Job
from .ingestion import extract_file, index_document


def main():
    with Session() as db:
        if db.scalar(select(Job.id).where(Job.status.in_(['PENDING','PROCESSING']))):
            raise SystemExit('Ingestion is running. Wait before reindexing.')
        ids=list(db.scalars(select(Document.id).join(Source,Source.id==Document.source_id).where(
            Document.format.in_(['TXT','PDF','DOCX']),Document.status=='INDEXED',Source.enabled.is_(True))))
        for did in ids:
            doc=db.get(Document,did)
            try:
                result=index_document(db,doc,extract_file(doc.file_path,doc.format))
                title=doc.title
                db.commit()
                print(json.dumps({'title':title,**result},ensure_ascii=False),flush=True)
            except Exception:
                db.rollback()
                raise


if __name__=='__main__':
    main()
