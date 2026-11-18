import os
import hashlib
from dataclasses import dataclass
from pathlib import Path

ANSWER_REVISION = 'qa-v13'

@dataclass
class Settings:
    database_url: str = os.getenv('DATABASE_URL', 'sqlite:///./data/dev.db')
    jwt_secret: str = os.getenv('JWT_SECRET', '')
    storage_dir: Path = Path(os.getenv('STORAGE_DIR', './data/uploads'))
    provider_url: str = os.getenv('MODEL_BASE_URL', 'https://api.openai.com/v1')
    provider_key: str = os.getenv('MODEL_API_KEY', '')
    provider: str = os.getenv('MODEL_PROVIDER', 'openai').lower()
    model_timeout: int = int(os.getenv('MODEL_TIMEOUT_SECONDS', '300'))
    embedding_batch_size: int = int(os.getenv('EMBEDDING_BATCH_SIZE', '8'))
    embedding_keep_alive: str = os.getenv('OLLAMA_EMBED_KEEP_ALIVE', '0')
    local_context: int = int(os.getenv('OLLAMA_NUM_CTX', '8192'))
    context_chars: int = int(os.getenv('CONTEXT_MAX_CHARS', '12000'))
    embedding_model: str = os.getenv('EMBEDDING_MODEL', 'text-embedding-3-small')
    embedding_dim: int = int(os.getenv('EMBEDDING_DIM', '1536'))
    llm_model: str = os.getenv('LLM_MODEL', 'gpt-4.1-mini')
    answer_engine: str = os.getenv('ANSWER_ENGINE','legacy')
    chunk_size: int = int(os.getenv('CHUNK_SIZE', '400'))
    overlap: int = int(os.getenv('CHUNK_OVERLAP', '60'))
    top_k: int = int(os.getenv('TOP_K', '5'))
    min_score: float = float(os.getenv('MIN_SIMILARITY', '0.25'))
    max_upload: int = int(os.getenv('MAX_UPLOAD_MB', '20')) * 1024 * 1024
    wiki_hosts: tuple = tuple(x.strip() for x in os.getenv('WIKI_ALLOWED_HOSTS','wiki.hcmut.edu.vn,bkwiki.hcmut.edu.vn,mybk.hcmut.edu.vn').split(',') if x.strip())
    bksi_max_articles: int = int(os.getenv('BKSI_MAX_ARTICLES','100'))
    bksi_max_pages: int = int(os.getenv('BKSI_MAX_PAGES','180'))
    web_delay_seconds: float = float(os.getenv('WEB_REQUEST_DELAY_SECONDS','0.3'))
    cors_origins: tuple = tuple(os.getenv('CORS_ORIGINS','http://localhost:5173,http://localhost:8080').split(','))
    config_version: str = os.getenv('CONFIG_VERSION', 'baseline-v1')
    retrieval_strategy: str = os.getenv('RETRIEVAL_STRATEGY', 'vector_keyword')
    retrieval_cache_seconds: int = int(os.getenv('RETRIEVAL_CACHE_SECONDS', '600'))
    freshness_days: int = int(os.getenv('SOURCE_FRESHNESS_DAYS', '30'))
    job_execution_mode: str = os.getenv('JOB_EXECUTION_MODE', 'background')
    worker_poll_seconds: float = float(os.getenv('WORKER_POLL_SECONDS', '2'))
    ollama_num_gpu: int = int(os.getenv('OLLAMA_NUM_GPU', '-1'))
    ollama_cpu_fallback: bool = os.getenv('OLLAMA_CPU_FALLBACK', 'true').lower()=='true'

settings = Settings()
def pipeline_key():
    space=hashlib.sha256(f'{settings.provider}:{settings.provider_url.rstrip("/")}'.encode()).hexdigest()[:16]
    key=f'{settings.embedding_model}:{settings.embedding_dim}:{settings.chunk_size}:{settings.overlap}:extract-v3:space-{space}'
    return 'ollama:'+key if settings.provider=='ollama' else key
