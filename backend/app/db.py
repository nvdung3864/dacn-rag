from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import settings

class Base(DeclarativeBase):
    pass

settings.storage_dir.mkdir(parents=True, exist_ok=True)
if settings.database_url.startswith('sqlite:///'):
    from pathlib import Path
    Path(settings.database_url[10:]).parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(settings.database_url, connect_args={'check_same_thread':False} if settings.database_url.startswith('sqlite') else {}, pool_pre_ping=True)
if engine.dialect.name == 'sqlite':
    @event.listens_for(engine, 'connect')
    def enable_foreign_keys(conn, record):
        conn.execute('PRAGMA foreign_keys=ON')
Session = sessionmaker(bind=engine, expire_on_commit=False)
def get_db():
    with Session() as db:
        yield db
