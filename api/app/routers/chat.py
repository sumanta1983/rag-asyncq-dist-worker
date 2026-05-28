from fastapi import APIRouter, HTTPException
from openai import OpenAIError
from pydantic import BaseModel, Field

from .. import circuit
from ..config import settings
from ..deps import get_openai, get_valkey, get_vector_store

router = APIRouter(prefix="/chat", tags=["chat"])


SYSTEM_PROMPT_TEMPLATE = """
You are Baymax, an AI assistant that answers questions strictly from the provided PDF context.
Rules:
- Answer the question directly and in detail using ONLY the context below.
- Quote or paraphrase the relevant content — do not just point to a page.
- After your answer, cite the page numbers you used like: (see page X).
- If the context does not contain the answer, say: "I couldn't find this in the document."

Context: {context}
"""


class ChatRequest(BaseModel):
    query: str = Field(min_length=1)
    k: int = Field(default=0, ge=0, le=50)
    fetch_k: int = Field(default=0, ge=0, le=200)
    model: str | None = None


def _format_page(meta: dict) -> str:
    page = meta.get("page", "N/A")
    if isinstance(page, int):
        return str(page + 1)  # PyMuPDF is 0-indexed; humans expect 1-indexed
    return str(page)


def _build_context(results) -> str:
    parts = []
    for r in results:
        parts.append(
            f"Page Number: {_format_page(r.metadata)}\n"
            f"Page Content: {r.page_content}\n"
            f"File Location: {r.metadata.get('source', 'N/A')}"
        )
    return "\n\n\n".join(parts)


@router.post("")
def chat(req: ChatRequest):
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
        context = _build_context(results)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_TEMPLATE.format(context=context)},
            {"role": "user", "content": req.query},
        ]
        model = req.model or settings.chat_model
        completion = get_openai().chat.completions.create(model=model, messages=messages)
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
        "model": model,
        "answer": completion.choices[0].message.content,
        "sources": [
            {
                "page": _format_page(doc.metadata),
                "source": doc.metadata.get("source", "N/A"),
            }
            for doc in results
        ],
    }
