"""Tests for weekly digest generation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.digest import collect_weekly_jobs, generate_digest, week_key, write_digest
from src.models import NormalizedJob


def test_week_key_format():
    w = week_key()
    assert w.startswith("20")
    assert "-W" in w


def _sample_job(idx: int) -> NormalizedJob:
    from datetime import datetime, timezone
    return NormalizedJob(
        id=f"id-{idx}",
        title="ML Engineer",
        title_normalized="ml engineer",
        company=f"Company {idx}",
        company_normalized=f"company {idx}",
        url=f"https://pk.linkedin.com/jobs/view/ml-engineer-{idx}",
        source="linkedin",
        location="Pakistan (Remote)",
        location_type="remote",
        salary_min=150_000,
        salary_max=200_000,
        salary_currency="$",
        job_type="full-time",
        posted_date=None,
        fetched_at=datetime.now(timezone.utc),
        tags=["ai"],
        description_snippet="100% remote work from home position.",
        cv_match_score=90,
        cv_match_label="Machine Learning (90%)",
    )


def test_generate_digest_stats():
    jobs = [_sample_job(i) for i in range(4)]
    d = generate_digest(jobs)
    assert d["total"] == 4
    assert "linkedin" in d["by_source"]
    assert d["by_location"]["remote"] == 4
    assert len(d["top_jobs"]) <= 20


def test_write_digest_files(tmp_path):
    jobs = [_sample_job(i) for i in range(3)]
    d = generate_digest(jobs)
    json_p, md_p = write_digest(d, tmp_path)
    assert json_p.exists()
    assert md_p.exists()
    parsed = json.loads(json_p.read_text(encoding="utf-8"))
    assert parsed["total"] == 3
    assert "Weekly Digest" in md_p.read_text(encoding="utf-8")


def test_collect_weekly_jobs(tmp_path, monkeypatch, tmp_slc):
    import src.digest as digest
    from datetime import timedelta

    today = digest.utc_now().date()
    day_file = tmp_path / f"jobs_{today.isoformat()}.json"
    day_file.write_text(json.dumps([_sample_job(1).to_dict(), _sample_job(2).to_dict()]), encoding="utf-8")

    raw = digest.collect_weekly_jobs(tmp_path)
    assert len(raw) == 2


def test_collect_weekly_jobs_fallback_to_seen_store(tmp_slc):
    """Cloud runner digests must not come back empty when `output/` is missing:
    jobs are merged back from the durable seen-store snapshot."""
    import src.digest as digest
    from datetime import timedelta
    from src.state import SeenStore

    today = digest.utc_now().date()
    a = _sample_job(1)  # present in both output file and seen store
    b = _sample_job(2)  # only in seen store, within the week window
    c = _sample_job(3)  # only in seen store, but older than the 7-day window
    c.fetched_at = c.fetched_at - timedelta(days=20)

    (tmp_slc / f"jobs_{today.isoformat()}.json").write_text(
        json.dumps([a.to_dict()]), encoding="utf-8")

    store = SeenStore()
    store.push_recent(a.to_dict())
    store.push_recent(b.to_dict())
    store.push_recent(c.to_dict())
    store.save()

    out = digest.collect_weekly_jobs(tmp_slc)
    ids = {j.id for j in out}
    assert ids == {"id-1", "id-2"}


def test_collect_weekly_jobs_drops_hallucinations(tmp_path, tmp_slc):
    """Ensure weekly digest drops recruiter /in/ profile URLs, on-site, JLPT, and foreign domestic roles."""
    import src.digest as digest
    from datetime import datetime, timezone

    today = digest.utc_now().date()
    valid_job = _sample_job(1)

    # 1. Recruiter profile URL (/in/)
    bad_profile = _sample_job(2)
    bad_profile.url = "https://www.linkedin.com/in/recruiter-profile-123/"

    # 2. On-site role in description
    bad_onsite = _sample_job(3)
    bad_onsite.description_snippet = "📍 Gulberg, Lahore | Onsite position at office"

    # 3. Language restricted (Japanese JLPT)
    bad_lang = _sample_job(4)
    bad_lang.title = "AI Engineer JLPT N1 Level"
    bad_lang.description_snippet = "Business Level Japanese Required"

    # 4. Foreign domestic (EU only)
    bad_eu = _sample_job(5)
    bad_eu.description_snippet = "This is a fully remote role in EU."

    # 5. Low CV match score
    bad_score = _sample_job(6)
    bad_score.cv_match_score = 40

    day_file = tmp_path / f"jobs_{today.isoformat()}.json"
    day_file.write_text(json.dumps([
        valid_job.to_dict(),
        bad_profile.to_dict(),
        bad_onsite.to_dict(),
        bad_lang.to_dict(),
        bad_eu.to_dict(),
        bad_score.to_dict(),
    ]), encoding="utf-8")

    collected = digest.collect_weekly_jobs(tmp_path)
    assert len(collected) == 1
    assert collected[0].id == valid_job.id