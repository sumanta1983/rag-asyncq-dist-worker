from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    mobile: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="user")  # "user" | "admin"
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    queries: Mapped[list["QueryLog"]] = relationship(back_populates="user", cascade="all,delete-orphan")
    jobs: Mapped[list["JobLog"]] = relationship(back_populates="user", cascade="all,delete-orphan")


class QueryLog(Base):
    __tablename__ = "query_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    endpoint: Mapped[str] = mapped_column(String(16))   # "/query" | "/chat"
    query: Mapped[str] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)

    user: Mapped[User] = relationship(back_populates="queries")


class JobLog(Base):
    """One row per ingest job, owned by the admin who uploaded the PDF."""

    __tablename__ = "job_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    stream_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)

    user: Mapped[User] = relationship(back_populates="jobs")

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

    # Store full issue summary as JSON string
    issues_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Optional: first few bad chunk examples/issues
    sample_issues_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)