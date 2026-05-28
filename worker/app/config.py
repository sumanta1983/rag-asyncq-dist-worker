from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "learning_langchain"
    valkey_url: str = "redis://valkey:6379/0"
    ingest_dir: str = "/data/ingest"
    ingest_stream: str = "ingest_jobs"
    consumer_group: str = "ingest_workers"
    embed_model: str = "text-embedding-3-large"
    embed_dims: int = 3072

    # Splitter — mirrors rag_system/index_pdf.py
    chunk_size: int = 1500
    chunk_overlap: int = 300

    # Stream read loop
    read_batch: int = 4
    block_ms: int = 5000

    # Status hash TTL (seconds)
    status_ttl: int = 86400


settings = Settings()
