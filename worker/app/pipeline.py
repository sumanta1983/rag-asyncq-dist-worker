import json
from functools import lru_cache

from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from .chunker import load_and_chunk
from .config import settings


@lru_cache(maxsize=1)
def _qdrant_client() -> QdrantClient:
    return QdrantClient(url=settings.qdrant_url)


@lru_cache(maxsize=1)
def _embedder() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=settings.embed_model,
        api_key=settings.openai_api_key,
    )


def _ensure_collection() -> None:
    client = _qdrant_client()
    existing = {c.name for c in client.get_collections().collections}
    if settings.qdrant_collection not in existing:
        client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=qmodels.VectorParams(
                size=settings.embed_dims,
                distance=qmodels.Distance.COSINE,
            ),
        )


@lru_cache(maxsize=1)
def _vector_store() -> QdrantVectorStore:
    _ensure_collection()
    return QdrantVectorStore.from_existing_collection(
        url=settings.qdrant_url,
        collection_name=settings.qdrant_collection,
        embedding=_embedder(),
    )


def process_job(job: dict) -> dict:
    """Chunk → embed → upsert. Returns a summary for logging."""
    path = job["path"]
    job_id = job.get("job_id", "unknown")
    extra_meta = json.loads(job.get("metadata") or "{}")

    chunks = load_and_chunk(path)
    if not chunks:
        return {"job_id": job_id, "chunks": 0, "skipped": True}

    if extra_meta:
        for c in chunks:
            c.metadata.update(extra_meta)
        for c in chunks:
            c.metadata.setdefault("job_id", job_id)

    # add_documents handles embedding + upsert in one call, matching the
    # style of rag_system/index_pdf.py's QdrantVectorStore.from_documents.
    _vector_store().add_documents(chunks)

    return {"job_id": job_id, "chunks": len(chunks)}
