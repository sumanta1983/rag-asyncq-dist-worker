from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


class IngestionQualityLog(Base):
    __tablename__ = "ingestion_quality_log"

    id: Mapped[int] = mapped_column(primary_key=True)

    job_id: Mapped[str] = mapped_column(String(64), index=True)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)

    original_chunks: Mapped[int] = mapped_column(Integer, default=0)
    checked_chunks: Mapped[int] = mapped_column(Integer, default=0)
    kept_chunks: Mapped[int] = mapped_column(Integer, default=0)
    rejected_chunks: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_chunks: Mapped[int] = mapped_column(Integer, default=0)

    quality_passed: Mapped[bool] = mapped_column(Boolean, default=True)

    issues_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    sample_issues_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)