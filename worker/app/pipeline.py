import json
from functools import lru_cache
from pathlib import Path

from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from .chunker import load_and_chunk
from .config import settings
from .ingest_checks import validate_documents
from .quality_store import store_quality_report


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


def _filename_from_job(job: dict, path: str) -> str | None:
    filename = job.get("filename")

    if filename:
        return filename

    try:
        return Path(path).name
    except Exception:
        return None


def process_job(job: dict) -> dict:
    """
    Chunk → quality check → embed → upsert.

    Quality report is stored in SQLite so admin can view ingestion quality
    history from the web dashboard.
    """

    path = job["path"]
    job_id = job.get("job_id", "unknown")
    filename = _filename_from_job(job, path)

    extra_meta = json.loads(job.get("metadata") or "{}")

    chunks = load_and_chunk(path)

    if not chunks:
        empty_report = {
            "checked": 0,
            "kept": 0,
            "rejected": 0,
            "duplicates": 0,
            "issues": {"no chunks created": 1},
            "sample_issues": [],
        }

        store_quality_report(
            job_id=job_id,
            filename=filename,
            original_chunks=0,
            report=empty_report,
        )

        return {
            "job_id": job_id,
            "chunks": 0,
            "skipped": True,
            "reason": "no chunks created",
            "quality": empty_report,
        }

    if extra_meta:
        for c in chunks:
            c.metadata.update(extra_meta)

    for c in chunks:
        c.metadata.setdefault("job_id", job_id)
        c.metadata.setdefault("filename", filename)

    max_len = settings.chunk_size + settings.chunk_overlap

    valid_chunks, quality_report = validate_documents(
        chunks,
        min_len=settings.quality_min_len,
        max_len=max_len,
        drop_bad=settings.quality_drop_bad,
        dedupe=settings.quality_dedupe,
        enable_ascii_noise_check=settings.quality_enable_ascii_noise_check,
    )

    store_quality_report(
        job_id=job_id,
        filename=filename,
        original_chunks=len(chunks),
        report=quality_report,
    )

    if not valid_chunks:
        return {
            "job_id": job_id,
            "chunks": 0,
            "original_chunks": len(chunks),
            "skipped": True,
            "reason": "all chunks failed quality checks",
            "quality": quality_report,
        }

    # add_documents handles embedding + upsert.
    # This means only valid chunks consume OpenAI embedding cost.
    _vector_store().add_documents(valid_chunks)

    return {
        "job_id": job_id,
        "chunks": len(valid_chunks),
        "original_chunks": len(chunks),
        "quality": quality_report,
    }