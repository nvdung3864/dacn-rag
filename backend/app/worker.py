"""Single durable DB-backed ingestion worker. PostgreSQL advisory lock owns recovery."""
import logging
import signal
import time
from datetime import datetime,timezone
from sqlalchemy import select,update,text
from .db import Session,engine
from .models import Source,Job,now
from .config import settings
from .ingestion import run_job
from .operations import audit

log=logging.getLogger('rag.worker')

def schedule_due(db):
    instant=datetime.now(timezone.utc)
    for source in db.scalars(select(Source).where(Source.enabled.is_(True),Source.source_type=='WEB',Source.sync_interval_minutes>0).with_for_update(skip_locked=True)):
        running=db.scalar(select(Job).where(Job.source_id==source.id,Job.status.in_(['PENDING','PROCESSING'])))
        if running:continue
        latest=db.scalar(select(Job).where(Job.source_id==source.id,Job.kind=='SYNC').order_by(Job.created_at.desc()).limit(1))
        previous=(latest.finished_at or latest.created_at) if latest else source.last_synced_at
        if previous and (instant-datetime.fromisoformat(previous)).total_seconds()<source.sync_interval_minutes*60:continue
        job=Job(source_id=source.id,kind='SYNC');db.add(job);db.flush()
        audit(db,None,'job.schedule','job',job.id,{'source_id':source.id})
    db.commit()

def claim_next(db):
    job=db.scalar(select(Job).where(Job.status=='PENDING').order_by(Job.created_at,Job.id).with_for_update(skip_locked=True).limit(1))
    if not job:return None
    job.status='PROCESSING';db.commit();return job.id

def main():
    if engine.dialect.name!='postgresql':raise SystemExit('Worker bền vững yêu cầu PostgreSQL. Dev/test có thể dùng background mode.')
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    stop=False
    def shutdown(*_):
        nonlocal stop
        stop=True
    signal.signal(signal.SIGTERM,shutdown);signal.signal(signal.SIGINT,shutdown)
    with engine.connect() as lock:
        if not lock.scalar(text('SELECT pg_try_advisory_lock(723401)')):raise SystemExit('Đã có worker giữ khóa. Chỉ chạy một worker cho bản hiện tại.')
        lock.commit()
        with Session() as db:
            db.execute(update(Job).where(Job.status=='PROCESSING').values(status='PENDING',error='Khôi phục sau khi worker bị gián đoạn.'))
            db.commit()
        log.info('Worker ready; pending jobs retained and scheduled WEB sync enabled.')
        while not stop:
            try:
                with Session() as db:
                    schedule_due(db);job_id=claim_next(db)
                if job_id:
                    run_job(job_id);log.info('Processed job %s',job_id)
                else:time.sleep(max(0.1,min(10,settings.worker_poll_seconds)))
            except Exception:
                log.exception('Worker iteration failed; retrying after delay.')
                time.sleep(3)

if __name__=='__main__':main()
