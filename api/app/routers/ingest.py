import json
import os
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..auth.deps import require_admin
from ..config import settings
from ..db import get_db
from ..deps import get_valkey
from ..models import JobLog, User

router = APIRouter(prefix="/ingest", tags=["ingest"])


def _status_key(job_id: str) -> str:
    return f"job:{job_id}"


@router.post("")
async def ingest_pdf(
    file: UploadFile = File(...),
    metadata: str | None = Form(default=None),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Admin-only. Save PDF, enqueue job, persist a JobLog row."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="only .pdf files are accepted")

    job_id = uuid.uuid4().hex
    dest_dir = Path(settings.ingest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"{job_id}.pdf"

    with dest_path.open("wb") as f:
        while chunk := await file.read(1 << 20):  # 1 MiB
            f.write(chunk)

    # Stamp user_id into the job so the worker propagates it to Qdrant payload
    extra = json.loads(metadata) if metadata else {}
    extra["uploaded_by_user_id"] = admin.id
    extra["uploaded_by_name"] = admin.name

    job = {
        "job_id": job_id,
        "path": str(dest_path),
        "filename": file.filename,
        "metadata": json.dumps(extra),
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
            "uploaded_by_user_id": str(admin.id),
        },
    )
    valkey.expire(_status_key(job_id), settings.status_ttl)

    db.add(JobLog(
        job_id=job_id,
        user_id=admin.id,
        filename=file.filename,
        stream_id=msg_id,
    ))
    db.commit()

    return {
        "job_id": job_id,
        "stream_id": msg_id,
        "path": str(dest_path),
        "size_bytes": os.path.getsize(dest_path),
        "status": "queued",
    }


@router.get("/status/{job_id}")
def ingest_status(job_id: str, _user: User = Depends(require_admin)):
    data = get_valkey().hgetall(_status_key(job_id))
    if not data:
        raise HTTPException(status_code=404, detail="job not found or expired")
    return {"job_id": job_id, **data}
