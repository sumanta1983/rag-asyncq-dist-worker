from fastapi import APIRouter, Depends, HTTPException
from openai import OpenAIError
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import circuit
from ..auth.deps import get_current_user
from ..config import settings
from ..db import get_db
from ..deps import get_valkey, get_vector_store
from ..models import QueryLog, User

router = APIRouter(prefix="/query", tags=["query"])


class QueryRequest(BaseModel):
    query: str = Field(min_length=1)
    k: int = Field(default=0, ge=0, le=50)
    fetch_k: int = Field(default=0, ge=0, le=200)


@router.post("")
def query(
    req: QueryRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
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

    db.add(QueryLog(user_id=user.id, endpoint="/query", query=req.query, answer=None, model=None))
    db.commit()

    return {
        "query": req.query,
        "k": k,
        "fetch_k": fetch_k,
        "results": [
            {"page_content": doc.page_content, "metadata": doc.metadata}
            for doc in results
        ],
    }
