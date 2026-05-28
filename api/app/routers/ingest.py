import os
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ..config import settings
from ..deps import get_valkey

router = APIRouter(prefix="/ingest", tags=["ingest"])


def _status_key(job_id: str) -> str:
    return f"job:{job_id}"


@router.post("")
async def ingest_pdf(
    file: UploadFile = File(...),
    metadata: str | None = Form(default=None),
):
    """Accept a PDF, drop it on the shared volume, enqueue a job on the Valkey stream."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="only .pdf files are accepted")

    job_id = uuid.uuid4().hex
    dest_dir = Path(settings.ingest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"{job_id}.pdf"

    with dest_path.open("wb") as f:
        while chunk := await file.read(1 << 20):  # 1 MiB
            f.write(chunk)

    job = {
        "job_id": job_id,
        "path": str(dest_path),
        "filename": file.filename,
        "metadata": metadata or "{}",
    }

    valkey = get_valkey()
    msg_id = valkey.xadd(settings.ingest_stream, job)

    valkey.hset(
        _status_key(job_id),
        mapping={
            "status": "queued",
            "filename": file.filename,
            "stream_id": msg_id,
            "enqueued_at": str(int(time.time())),
        },
    )
    valkey.expire(_status_key(job_id), settings.status_ttl)

    return {
        "job_id": job_id,
        "stream_id": msg_id,
        "path": str(dest_path),
        "size_bytes": os.path.getsize(dest_path),
        "status": "queued",
    }


@router.get("/status/{job_id}")
def ingest_status(job_id: str):
    data = get_valkey().hgetall(_status_key(job_id))
    if not data:
        raise HTTPException(status_code=404, detail="job not found or expired")
    return {"job_id": job_id, **data}
