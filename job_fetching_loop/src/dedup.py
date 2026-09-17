"""Deduplication: Layer 1 (exact URL hash) + Layer 2 (fuzzy title+company).

The two layers serve different purposes:
  L1: fast, O(1) skip of exact same job (hash in seen set) — never re-notify.
  L2: slow, O(n) fuzzy match — catches 'ML Engineer' vs 'Machine Learning Engineer'
      at the same company on a different site. Uses SequenceMatcher with a
      configurable threshold (default 0.85).
"""
from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from src.models import RawJob, NormalizedJob, job_id, normalize_text
from src.state import SeenStore


def compute_job_hash(url: str, title: str, company: str) -> str:
    return job_id(url, title, company)


# Common AI/ML abbreviations expansion for fuzzy title matching. SequenceMatcher
# alone scores "ML Engineer" vs "Machine Learning Engineer" too low; expanding
# abbreviations before comparing is the standard industry fix.
_ABBREVIATIONS = {
    "ml": "machine learning",
    "ai": "artificial intelligence",
    "nlp": "natural language processing",
    "llm": "large language model",
    "llms": "large language models",
    "cv": "computer vision",
    "ds": "data science",
    "mle": "machine learning engineer",
    "sde": "software development engineer",
    "swe": "software engineer",
}


def _expand_abbreviations(text: str) -> str:
    """Replace known abbreviations (as whole tokens) in a lowercase string."""
    words = text.split()
    expanded = []
    for word in words:
        expanded.append(_ABBREVIATIONS.get(word, word))
    return " ".join(expanded)


def _title_similarity(a: str, b: str) -> float:
    """Best-effort title similarity: SequenceMatcher ratio, then bonus for
    token-set overlap (handles reordered words and abbreviations)."""
    text_a = normalize_text(a)
    text_b = normalize_text(b)
    if not text_a or not text_b:
        return 0.0

    # Attempt 1: plain normalized comparison.
    ratio = SequenceMatcher(None, text_a, text_b).ratio()

    # Attempt 2: expand abbreviations, then re-compare.
    expanded_a = _expand_abbreviations(text_a)
    expanded_b = _expand_abbreviations(text_b)
    expanded_ratio = SequenceMatcher(None, expanded_a, expanded_b).ratio()

    # Attempt 3: token-set Jaccard overlap (order-independent).
    set_a = set(expanded_a.split())
    set_b = set(expanded_b.split())
    if set_a and set_b:
        jaccard = len(set_a & set_b) / len(set_a | set_b)
    else:
        jaccard = 0.0

    return max(ratio, expanded_ratio, jaccard)


def is_fuzzy_duplicate(
    job: RawJob | NormalizedJob,
    existing_jobs: list[dict[str, Any]],
    threshold: float = 0.85,
) -> bool:
    """Compare against a window of recent normalized jobs.

    Returns True if a match is found (same title + company above threshold).
    """
    new_company = normalize_text(job.company)
    if not new_company:
        return False
    for prev in existing_jobs:
        prev_title = prev.get("title_normalized", "")
        prev_company = prev.get("company_normalized", "")
        if not prev_title or not prev_company:
            continue
        title_sim = _title_similarity(job.title, prev_title)
        company_sim = SequenceMatcher(
            None, new_company, normalize_text(prev_company)
        ).ratio()
        if title_sim >= threshold and company_sim >= threshold:
            return True
    return False


def dedup_job(
    job: RawJob | NormalizedJob,
    seen: SeenStore,
    threshold: float = 0.85,
    extra_ids: set[str] | None = None,
    extra_recent: list[dict] | None = None,
) -> tuple[bool, str]:
    """Return (is_new, reason) — True when job passes both dedup layers.

    reasons: 'new', 'exact', 'fuzzy'
    Supports checking extra in-batch IDs and recent jobs without mutating seen.
    """
    jid = job_id(job.url, job.title, job.company)
    if (extra_ids and jid in extra_ids) or seen.has_exact(jid):
        return False, "exact"
    recent = seen.recent_jobs()
    if extra_recent:
        recent = recent + extra_recent
    if is_fuzzy_duplicate(job, recent, threshold=threshold):
        return False, "fuzzy"
    return True, "new"


def accept_and_record(
    first: RawJob | NormalizedJob,
    second: NormalizedJob | SeenStore,
    third: SeenStore | None = None,
) -> None:
    """Record a validated job in the dedup store (after normalization + filtering).

    Supports both:
      accept_and_record(normalized, seen)
      accept_and_record(raw, normalized, seen)
    """
    if third is not None:
        normalized: NormalizedJob = second  # type: ignore[assignment]
        seen: SeenStore = third
    elif isinstance(first, NormalizedJob) and isinstance(second, SeenStore):
        normalized = first
        seen = second
    else:
        normalized = second  # type: ignore[assignment]
        seen = first  # type: ignore[assignment]
    seen.mark_exact(normalized.id)
    seen.push_recent(normalized.to_dict())