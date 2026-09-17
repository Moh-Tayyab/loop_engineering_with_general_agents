"""Tests for deduplication: exact hash + fuzzy matching."""
from __future__ import annotations

from src.dedup import compute_job_hash, dedup_job, is_fuzzy_duplicate
from src.models import RawJob, normalize_text
from src.state import SeenStore


def _raw(title="ML Engineer", company="OpenAI", url="https://x.com/job/1"):
    return RawJob(source="test", title=title, company=company, url=url)


def test_exact_hash_stable():
    a = compute_job_hash("https://x.com/job/1", "ML Engineer", "OpenAI")
    b = compute_job_hash("https://x.com/job/1", "ML Engineer", "OpenAI")
    assert a == b
    assert len(a) == 16


def test_exact_hash_differs_for_company():
    a = compute_job_hash("https://x.com/job/1", "ML Engineer", "OpenAI")
    b = compute_job_hash("https://x.com/job/1", "ML Engineer", "Anthropic")
    assert a != b


def test_exact_dup_detected(tmp_slc):
    seen = SeenStore()
    job = _raw()
    is_new, reason = dedup_job(job, seen)
    assert is_new and reason == "new"
    seen.mark_exact(job_id := compute_job_hash(job.url, job.title, job.company))
    is_new_2, reason_2 = dedup_job(_raw(), seen)
    assert not is_new_2
    assert reason_2 == "exact"


def test_fuzzy_dup_detected(tmp_slc):
    existing = {
        "title_normalized": normalize_text("Machine Learning Engineer"),
        "company_normalized": normalize_text("OpenAI"),
        "source": "linkedin",
    }
    dup = _raw(title="ML Engineer", company="OpenAI")
    assert is_fuzzy_duplicate(dup, [existing], threshold=0.85)


def test_fuzzy_no_false_positive(tmp_slc):
    existing = {
        "title_normalized": normalize_text("Data Analyst"),
        "company_normalized": normalize_text("OpenAI"),
        "source": "linkedin",
    }
    other = _raw(title="ML Engineer", company="Google")
    assert not is_fuzzy_duplicate(other, [existing], threshold=0.85)


def test_normalize_text():
    assert normalize_text("  Machine   Learning  Engineer!!! ") == "machine learning engineer"


def test_seen_store_roundtrip(tmp_slc):
    from pathlib import Path
    seen = SeenStore()
    seen.mark_exact("abc123")
    seen.push_recent({"id": "abc123", "title_normalized": "x", "company_normalized": "y"})
    seen.save()

    seen2 = SeenStore()
    assert "abc123" in seen2.seen_hashes
    assert len(seen2.recent) == 1


def test_indeed_url_exact_dedup_matches_across_tracking_variants(tmp_slc):
    """Verify that different tracking URLs for the same Indeed job ID (jk=...)

    produce the exact same canonical ID and trigger exact deduplication.
    """
    from src.dedup import accept_and_record
    from src.main import normalize_raw

    seen = SeenStore()

    raw_search = RawJob(
        source="indeed",
        title="AI Engineer",
        company="GoodLeap",
        url="https://www.indeed.com/jobs?q=ai&l=remote&vjs=3&jk=096fd4aa5f21fe38",
    )
    norm_search = normalize_raw(raw_search)

    # First time seen: new
    is_new, reason = dedup_job(norm_search, seen)
    assert is_new
    assert reason == "new"

    # Accept and record into seen
    accept_and_record(norm_search, seen)
    assert seen.has_exact(norm_search.id)

    # Subsequent appearance via a different tracking click URL with same jk
    raw_click = RawJob(
        source="indeed",
        title="AI Engineer",
        company="GoodLeap",
        url="https://www.indeed.com/rc/clk?jk=096fd4aa5f21fe38&bb=xyz&xkcb=123",
    )
    norm_click = normalize_raw(raw_click)

    # Exact dedup must match!
    assert norm_click.id == norm_search.id
    is_dup, reason = dedup_job(norm_click, seen)
    assert not is_dup
    assert reason == "exact"

    # Raw job check must also match exact dedup via canonical URL hashing
    is_dup_raw, reason_raw = dedup_job(raw_click, seen)
    assert not is_dup_raw
    assert reason_raw == "exact"