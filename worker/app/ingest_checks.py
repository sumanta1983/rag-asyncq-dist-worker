import hashlib
import re
from collections import Counter
from typing import Any

from langchain_core.documents import Document


def normalize_text(text: str) -> str:
    """
    Normalize whitespace so quality checks and hashing are stable.
    """
    return re.sub(r"\s+", " ", text or "").strip()


def make_content_hash(text: str) -> str:
    """
    Create a stable hash from cleaned text.
    Used for duplicate detection.
    """
    clean = normalize_text(text)
    return hashlib.md5(clean.encode("utf-8")).hexdigest()


def check_chunk(
    text: str,
    *,
    min_len: int = 50,
    max_len: int = 1800,
    min_unique_ratio: float = 0.35,
    enable_ascii_noise_check: bool = False,
    max_non_ascii_ratio: float = 0.30,
) -> dict[str, Any]:
    """
    Check one chunk's text quality.

    Important:
    - Keep non-ASCII check disabled by default.
    - Bengali/Hindi documents naturally contain many non-ASCII characters.
    """

    issues: list[str] = []
    clean = normalize_text(text)

    if len(clean) < min_len:
        issues.append(f"too short ({len(clean)} chars)")

    if len(clean) > max_len:
        issues.append(f"too long ({len(clean)} chars)")

    if len(clean) < 30:
        issues.append("effectively empty after cleaning")

    words = clean.split()

    # Only check lexical diversity if enough words exist.
    # Otherwise short text will be unfairly marked as repetitive.
    if len(words) >= 20:
        unique_ratio = len(set(words)) / max(len(words), 1)
        if unique_ratio < min_unique_ratio:
            issues.append(f"low lexical diversity ({unique_ratio:.0%})")

    # Optional OCR/encoding noise check.
    # Disabled by default because Indian language text can be valid non-ASCII.
    if enable_ascii_noise_check and clean:
        non_ascii_ratio = sum(1 for c in clean if ord(c) > 127) / len(clean)
        if non_ascii_ratio > max_non_ascii_ratio:
            issues.append(f"high non-ascii ratio ({non_ascii_ratio:.0%})")

    return {
        "ok": len(issues) == 0,
        "issues": issues,
        "hash": make_content_hash(clean),
        "chars": len(clean),
    }


def validate_documents(
    docs: list[Document],
    *,
    min_len: int = 50,
    max_len: int = 1800,
    drop_bad: bool = True,
    dedupe: bool = True,
    enable_ascii_noise_check: bool = False,
    sample_limit: int = 5,
) -> tuple[list[Document], dict[str, Any]]:
    """
    Validate LangChain Document chunks before embedding/upserting.

    Returns:
        valid_docs:
            The documents that should continue to embedding/Qdrant.

        report:
            A summary that can be stored in SQLite and shown in admin panel.
    """

    valid_docs: list[Document] = []
    seen_hashes: set[str] = set()

    checked = 0
    rejected = 0
    duplicates = 0
    issue_counter: Counter[str] = Counter()
    sample_issues: list[dict[str, Any]] = []

    for doc in docs:
        checked += 1

        result = check_chunk(
            doc.page_content,
            min_len=min_len,
            max_len=max_len,
            enable_ascii_noise_check=enable_ascii_noise_check,
        )

        # Store useful debugging metadata in the chunk payload.
        doc.metadata["quality_ok"] = result["ok"]
        doc.metadata["quality_issues"] = result["issues"]
        doc.metadata["content_hash"] = result["hash"]
        doc.metadata["chunk_chars"] = result["chars"]

        for issue in result["issues"]:
            issue_counter[issue] += 1

        if not result["ok"] and len(sample_issues) < sample_limit:
            sample_issues.append(
                {
                    "page": doc.metadata.get("page"),
                    "source": doc.metadata.get("source"),
                    "issues": result["issues"],
                    "preview": normalize_text(doc.page_content)[:250],
                }
            )

        if dedupe and result["hash"] in seen_hashes:
            duplicates += 1
            continue

        if dedupe:
            seen_hashes.add(result["hash"])

        if drop_bad and not result["ok"]:
            rejected += 1
            continue

        valid_docs.append(doc)

    report = {
        "checked": checked,
        "kept": len(valid_docs),
        "rejected": rejected,
        "duplicates": duplicates,
        "issues": dict(issue_counter),
        "sample_issues": sample_issues,
    }

    return valid_docs, report