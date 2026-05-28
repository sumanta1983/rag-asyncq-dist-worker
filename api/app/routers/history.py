from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.deps import get_current_user, require_admin
from ..db import get_db
from ..models import JobLog, QueryLog, User

router = APIRouter(prefix="/history", tags=["history"])


class QueryItem(BaseModel):
    id: int
    endpoint: str
    query: str
    answer: str | None
    model: str | None
    created_at: str


class JobItem(BaseModel):
    id: int
    job_id: str
    filename: str
    stream_id: str | None
    user_id: int
    created_at: str


@router.get("/queries", response_model=list[QueryItem])
def my_queries(
    limit: int = Query(default=50, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(QueryLog)
        .where(QueryLog.user_id == user.id)
        .order_by(QueryLog.created_at.desc())
        .limit(limit)
    ).all()
    return [
        QueryItem(
            id=r.id,
            endpoint=r.endpoint,
            query=r.query,
            answer=r.answer,
            model=r.model,
            created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]


@router.get("/jobs", response_model=list[JobItem])
def all_jobs(
    limit: int = Query(default=100, ge=1, le=1000),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Admin-only: every ingest job logged in SQLite."""
    rows = db.scalars(select(JobLog).order_by(JobLog.created_at.desc()).limit(limit)).all()
    return [
        JobItem(
            id=r.id,
            job_id=r.job_id,
            filename=r.filename,
            stream_id=r.stream_id,
            user_id=r.user_id,
            created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]
