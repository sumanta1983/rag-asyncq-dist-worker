import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..auth.deps import require_admin
from ..db import get_db
from ..models import IngestionQualityLog, User


router = APIRouter(
    prefix="/admin/ingestion-quality",
    tags=["admin-ingestion-quality"],
)


def _safe_json_loads(value: str | None, fallback):
    if not value:
        return fallback

    try:
        return json.loads(value)
    except Exception:
        return fallback


def _serialize_quality_log(row: IngestionQualityLog) -> dict:
    return {
        "id": row.id,
        "job_id": row.job_id,
        "filename": row.filename,
        "original_chunks": row.original_chunks,
        "checked_chunks": row.checked_chunks,
        "kept_chunks": row.kept_chunks,
        "rejected_chunks": row.rejected_chunks,
        "duplicate_chunks": row.duplicate_chunks,
        "quality_passed": row.quality_passed,
        "issues": _safe_json_loads(row.issues_json, {}),
        "sample_issues": _safe_json_loads(row.sample_issues_json, []),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("")
def list_ingestion_quality(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    only_failed: bool = Query(default=False),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    stmt = select(IngestionQualityLog)

    if only_failed:
        stmt = stmt.where(IngestionQualityLog.quality_passed == False)  # noqa: E712

    stmt = (
        stmt.order_by(desc(IngestionQualityLog.created_at))
        .offset(offset)
        .limit(limit)
    )

    rows = db.scalars(stmt).all()

    return {
        "items": [_serialize_quality_log(row) for row in rows],
        "limit": limit,
        "offset": offset,
        "only_failed": only_failed,
    }


@router.get("/{job_id}")
def get_ingestion_quality_by_job(
    job_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    rows = db.scalars(
        select(IngestionQualityLog)
        .where(IngestionQualityLog.job_id == job_id)
        .order_by(desc(IngestionQualityLog.created_at))
    ).all()

    return {
        "job_id": job_id,
        "items": [_serialize_quality_log(row) for row in rows],
    }