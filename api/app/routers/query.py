from fastapi import APIRouter, HTTPException
from openai import OpenAIError
from pydantic import BaseModel, Field

from .. import circuit
from ..config import settings
from ..deps import get_valkey, get_vector_store

router = APIRouter(prefix="/query", tags=["query"])


class QueryRequest(BaseModel):
    query: str = Field(min_length=1)
    k: int = Field(default=0, ge=0, le=50)            # 0 => use server default
    fetch_k: int = Field(default=0, ge=0, le=200)     # 0 => use server default


@router.post("")
def query(req: QueryRequest):
    """MMR retrieval — same algorithm as the sync chat_pdf.py."""
    r = get_valkey()
    if circuit.is_open(r):
        retry_after = circuit.seconds_until_close(r) or settings.circuit_cooldown_s
        raise HTTPException(
            status_code=503,
            detail="OpenAI temporarily unavailable (circuit open)",
            headers={"Retry-After": str(max(retry_after, 1))},
        )

    k = req.k or settings.mmr_k
    fetch_k = req.fetch_k or settings.mmr_fetch_k

    try:
        results = get_vector_store().max_marginal_relevance_search(
            query=req.query, k=k, fetch_k=fetch_k
        )
    except OpenAIError as e:
        circuit.record_failure(
            r,
            threshold=settings.circuit_fail_threshold,
            cooldown_s=settings.circuit_cooldown_s,
        )
        raise HTTPException(status_code=502, detail=f"upstream OpenAI error: {e}")

    circuit.record_success(r)
    return {
        "query": req.query,
        "k": k,
        "fetch_k": fetch_k,
        "results": [
            {"page_content": doc.page_content, "metadata": doc.metadata}
            for doc in results
        ],
    }
