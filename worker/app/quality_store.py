import json
import logging
from typing import Any

from .db import session_scope
from .models import IngestionQualityLog

log = logging.getLogger("worker.quality_store")


def store_quality_report(
    *,
    job_id: str,
    filename: str | None,
    original_chunks: int,
    report: dict[str, Any],
) -> None:
    """
    Store ingestion quality report in SQLite.

    This should not break ingestion if DB logging fails.
    But during development, you may choose to raise the exception instead.
    """

    checked = int(report.get("checked", 0))
    kept = int(report.get("kept", 0))
    rejected = int(report.get("rejected", 0))
    duplicates = int(report.get("duplicates", 0))
    issues = report.get("issues", {})
    sample_issues = report.get("sample_issues", [])

    quality_passed = rejected == 0 and duplicates == 0

    row = IngestionQualityLog(
        job_id=job_id,
        filename=filename,
        original_chunks=original_chunks,
        checked_chunks=checked,
        kept_chunks=kept,
        rejected_chunks=rejected,
        duplicate_chunks=duplicates,
        quality_passed=quality_passed,
        issues_json=json.dumps(issues, ensure_ascii=False),
        sample_issues_json=json.dumps(sample_issues, ensure_ascii=False),
    )

    try:
        with session_scope() as db:
            db.add(row)

        log.info(
            "stored quality report job_id=%s checked=%s kept=%s rejected=%s duplicates=%s",
            job_id,
            checked,
            kept,
            rejected,
            duplicates,
        )

    except Exception:
        log.exception("failed to store quality report for job_id=%s", job_id)