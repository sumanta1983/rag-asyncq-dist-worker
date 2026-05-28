from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "learning_langchain"
    valkey_url: str = "redis://valkey:6379/0"
    ingest_dir: str = "/data/ingest"
    ingest_stream: str = "ingest_jobs"
    embed_model: str = "text-embedding-3-large"
    embed_dims: int = 3072
    chat_model: str = "gpt-5"

    # Retrieval
    mmr_k: int = 6
    mmr_fetch_k: int = 20

    # Status hash TTL (seconds)
    status_ttl: int = 86400


settings = Settings()
