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
        company="OpenAI",
        company_normalized="openai",
        url=f"https://x.com/{idx}",
        source="indeed" if idx % 2 else "linkedin",
        location="Remote",
        location_type="remote",
        salary_min=150_000,
        salary_max=200_000,
        salary_currency="$",
        job_type="full-time",
        posted_date=None,
        fetched_at=datetime.now(timezone.utc),
        tags=["ai"],
        description_snippet="desc",
    )


def test_generate_digest_stats():
    jobs = [_sample_job(i) for i in range(4)]
    d = generate_digest(jobs)
    assert d["total"] == 4
    assert "indeed" in d["by_source"]
    assert "linkedin" in d["by_source"]
    assert d["by_source"]["indeed"] == 2
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