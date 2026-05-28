from functools import lru_cache

import redis
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore

from .config import settings


@lru_cache(maxsize=1)
def get_valkey() -> redis.Redis:
    return redis.Redis.from_url(settings.valkey_url, decode_responses=True)


@lru_cache(maxsize=1)
def get_qdrant() -> QdrantClient:
    return QdrantClient(url=settings.qdrant_url)


@lru_cache(maxsize=1)
def get_embedder() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=settings.embed_model,
        api_key=settings.openai_api_key,
    )


@lru_cache(maxsize=1)
def get_openai() -> OpenAI:
    return OpenAI(api_key=settings.openai_api_key)


@lru_cache(maxsize=1)
def get_vector_store() -> QdrantVectorStore:
    """LangChain wrapper around the existing Qdrant collection.

    Matches the style of the original sync code (`chat_pdf.py`), which used
    `QdrantVectorStore.from_existing_collection(...)`. The collection must
    already exist — it's created in main.py's lifespan hook.
    """
    return QdrantVectorStore.from_existing_collection(
        url=settings.qdrant_url,
        collection_name=settings.qdrant_collection,
        embedding=get_embedder(),
    )


def ensure_collection() -> None:
    """Create the Qdrant collection on first boot if it doesn't already exist."""
    client = get_qdrant()
    existing = {c.name for c in client.get_collections().collections}
    if settings.qdrant_collection not in existing:
        client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=qmodels.VectorParams(
                size=settings.embed_dims,
                distance=qmodels.Distance.COSINE,
            ),
        )
