"""Tests for normalization pipeline (RawJob -> NormalizedJob)."""
from __future__ import annotations

from src.main import normalize_raw
from src.models import RawJob


def test_normalize_basic():
    raw = RawJob(
        source="indeed",
        title="ML Engineer",
        company="OpenAI",
        url="https://x.com/z",
        location="Remote",
        salary="$150k",
    )
    j = normalize_raw(raw)
    assert j.source == "indeed"
    assert j.location_type == "remote"
    assert j.salary_min == 150_000
    assert j.job_type == "unknown"


def test_normalize_title_normalized():
    raw = RawJob(source="t", title="  ML   Engineer  ", company="OpenAI", url="u")
    j = normalize_raw(raw)
    assert j.title == "  ML   Engineer  "
    assert j.title_normalized == "ml engineer"


def test_normalize_job_id():
    raw1 = RawJob(source="t", title="ML Engineer", company="OpenAI", url="u1")
    raw2 = RawJob(source="t", title="ML Engineer", company="OpenAI", url="u1")
    assert normalize_raw(raw1).id == normalize_raw(raw2).id


def test_normalize_snippet_capped():
    long_desc = "x" * 1000
    raw = RawJob(source="t", title="T", company="C", url="u", description=long_desc)
    j = normalize_raw(raw)
    assert len(j.description_snippet) <= 300


def test_normalize_roundtrip_through_dict():
    raw = RawJob(source="indeed", title="Data Scientist", company="Google", url="u",
                 salary="$120k-$160k", location="Remote")
    j = normalize_raw(raw)
    d = j.to_dict()
    from src.models import NormalizedJob
    j2 = NormalizedJob.from_dict(d)
    assert j2.id == j.id
    assert j2.salary_min == 120_000
    assert j2.location_type == "remote"


def test_normalize_preserves_posted_date_iso():
    raw = RawJob(source="linkedin", title="ML Engineer", company="OpenAI", url="u",
                 posted_date="2026-09-11")
    j = normalize_raw(raw)
    assert j.posted_date.isoformat() == "2026-09-11"


def test_normalize_preserves_posted_date_relative():
    raw = RawJob(source="indeed", title="ML Engineer", company="OpenAI", url="u",
                 posted_date="30+ days ago")
    j = normalize_raw(raw)
    assert j.posted_date is not None
    assert j.posted_date <= j.fetched_at.date()


def test_normalize_posted_date_none_default():
    raw = RawJob(source="indeed", title="ML Engineer", company="OpenAI", url="u")
    j = normalize_raw(raw)
    assert j.posted_date is None


def test_normalize_indeed_url_canonicalized():
    tracking_url = "https://www.indeed.com/rc/clk?jk=096fd4aa5f21fe38&bb=xyz&xkcb=123"
    raw = RawJob(source="indeed", title="AI Engineer", company="GoodLeap", url=tracking_url)
    j = normalize_raw(raw)
    assert j.url == "https://www.indeed.com/viewjob?jk=096fd4aa5f21fe38"