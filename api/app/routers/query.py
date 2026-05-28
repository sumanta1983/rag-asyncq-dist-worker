from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..config import settings
from ..deps import get_vector_store

router = APIRouter(prefix="/query", tags=["query"])


class QueryRequest(BaseModel):
    query: str = Field(min_length=1)
    k: int = Field(default=0, ge=0, le=50)            # 0 => use server default
    fetch_k: int = Field(default=0, ge=0, le=200)     # 0 => use server default


@router.post("")
def query(req: QueryRequest):
    """MMR retrieval — same algorithm as the sync chat_pdf.py."""
    k = req.k or settings.mmr_k
    fetch_k = req.fetch_k or settings.mmr_fetch_k

    results = get_vector_store().max_marginal_relevance_search(
        query=req.query, k=k, fetch_k=fetch_k
    )

    return {
        "query": req.query,
        "k": k,
        "fetch_k": fetch_k,
        "results": [
            {
                "page_content": r.page_content,
                "metadata": r.metadata,
            }
            for r in results
        ],
    }
