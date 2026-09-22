"""Tests for Indeed and Glassdoor scrapers — DOM card parsing, relative date extraction,
canonical URL generation, and source registry verification.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
import pytest

from src.models import (
    RawJob,
    canonical_job_url,
    parse_posted_date,
    utc_now,
)
from src.scrapers import all_scrapers, get_scraper, load_all_scrapers
from src.scrapers.indeed import IndeedScraper
from src.scrapers.glassdoor import GlassdoorScraper


# ── Registry Verification ─────────────────────────────────────────────────────

def test_only_three_scrapers_registered():
    """Verify that only linkedin, indeed, and glassdoor are registered."""
    load_all_scrapers()
    scrapers = all_scrapers()
    assert set(scrapers.keys()) == {"linkedin", "indeed", "glassdoor"}


def test_scraper_instances():
    """Verify all 3 scrapers can be instantiated cleanly."""
    for name in ("linkedin", "indeed", "glassdoor"):
        scraper = get_scraper(name)
        assert scraper.name == name
        assert scraper.is_available() is True


# ── Mock Element for Async Playwright Card Testing ───────────────────────────

class MockElement:
    def __init__(self, text: str = "", attrs: dict[str, str] | None = None, children: dict[str, MockElement] | None = None):
        self._text = text
        self._attrs = attrs or {}
        self._children = children or {}

    async def inner_text(self) -> str:
        return self._text

    async def get_attribute(self, name: str) -> str | None:
        return self._attrs.get(name)

    async def query_selector(self, selector: str) -> MockElement | None:
        for sel, el in self._children.items():
            if any(s.strip() in selector for s in sel.split(",")):
                return el
        return None


# ── Indeed Scraper Tests ──────────────────────────────────────────────────────

def test_indeed_parse_card_full_data():
    scraper = IndeedScraper()
    mock_title = MockElement(text="AI Engineer", attrs={"href": "/rc/clk?jk=abc1234567890def&f=1", "title": "AI Engineer"})
    mock_company = MockElement(text="Anthropic")
    mock_location = MockElement(text="Remote")
    mock_desc = MockElement(text="Building frontier LLMs and AI agent systems.")
    mock_salary = MockElement(text="$180,000 - $240,000 a year")
    mock_date = MockElement(text="Posted 1 day ago")

    card = MockElement(
        attrs={"data-jk": "abc1234567890def"},
        children={
            "h2.jobTitle a": mock_title,
            "span[data-testid='company-name']": mock_company,
            "div[data-testid='text-location']": mock_location,
            "div.job-snippet": mock_desc,
            "div.salary-snippet-container": mock_salary,
            "span.date": mock_date,
        },
    )

    job = asyncio.run(scraper._parse_card(card, "AI"))
    assert job is not None
    assert job.source == "indeed"
    assert job.title == "AI Engineer"
    assert job.company == "Anthropic"
    assert job.url == "https://pk.indeed.com/viewjob?jk=abc1234567890def"
    assert job.location == "Remote"
    assert job.salary == "$180,000 - $240,000 a year"
    assert "Building frontier" in job.description
    assert job.posted_date == "1 day ago"


def test_indeed_parse_card_missing_title_returns_none():
    scraper = IndeedScraper()
    card = MockElement(children={})
    job = asyncio.run(scraper._parse_card(card, "AI"))
    assert job is None


def test_indeed_parse_card_relative_dates():
    scraper = IndeedScraper()
    for raw_date_text in ("Just posted", "Active today", "Employer Active 2 days ago"):
        mock_title = MockElement(text="ML Specialist", attrs={"href": "/viewjob?jk=123"})
        mock_date = MockElement(text=raw_date_text)
        card = MockElement(
            children={
                "h2.jobTitle a": mock_title,
                "span.date": mock_date,
            }
        )
        job = asyncio.run(scraper._parse_card(card, "ML"))
        assert job is not None
        # Verify parse_posted_date converts it cleanly
        parsed = parse_posted_date(job.posted_date)
        assert parsed is not None
        assert isinstance(parsed, date)


def test_indeed_missing_location_not_fabricated():
    """Beat 105 / A2: missing location element must stay None (fail-closed), never 'Pakistan (Remote)'."""
    scraper = IndeedScraper()
    mock_title = MockElement(text="AI Engineer", attrs={"href": "/viewjob?jk=abc", "title": "AI Engineer"})
    mock_desc = MockElement(text="Fully remote role for our global team.")
    mock_date = MockElement(text="Just posted")
    card = MockElement(
        children={
            "h2.jobTitle a": mock_title,
            "div.job-snippet": mock_desc,
            "span.date": mock_date,
        },
    )
    job = asyncio.run(scraper._parse_card(card, "AI"))
    assert job is not None
    assert job.location is None
    from src.models import is_worldwide_remote
    assert not is_worldwide_remote(job.location, source="indeed", description=job.description)


def test_indeed_missing_date_fail_closed():
    """Beat 105 / A11: no date badge → posted_date is None (strict recency), not fabricated."""
    scraper = IndeedScraper()
    mock_title = MockElement(text="AI Engineer", attrs={"href": "/viewjob?jk=abc", "title": "AI Engineer"})
    card = MockElement(children={"h2.jobTitle a": mock_title})
    job = asyncio.run(scraper._parse_card(card, "AI"))
    assert job is not None
    assert job.posted_date is None


# ── Glassdoor Scraper Tests ───────────────────────────────────────────────────

def test_glassdoor_parse_card_full_data():
    scraper = GlassdoorScraper()
    mock_title = MockElement(text="Senior Computer Vision Engineer", attrs={"href": "/partner/jobListing.htm?jobListingId=1009876543&pos=101"})
    mock_company = MockElement(text="OpenAI")
    mock_location = MockElement(text="Remote")
    mock_desc = MockElement(text="Developing multimodal vision models.")
    mock_salary = MockElement(text="$200K - $280K (Employer est.)")
    mock_date = MockElement(text="24h")

    card = MockElement(
        children={
            "a[data-test='job-title']": mock_title,
            "span[data-test='employer-short-name']": mock_company,
            "div[data-test='emp-location']": mock_location,
            "div.JobCard_jobDescription__v_1k2": mock_desc,
            "div.JobCard_salaryEstimate__arV5J": mock_salary,
            "div[data-test='job-age']": mock_date,
        },
    )

    job = asyncio.run(scraper._parse_card(card, "Computer Vision"))
    assert job is not None
    assert job.source == "glassdoor"
    assert job.title == "Senior Computer Vision Engineer"
    assert job.company == "OpenAI"
    assert job.url == "https://www.glassdoor.com/job-listing/?jl=1009876543"
    assert job.location == "Remote"
    assert job.salary == "$200K - $280K (Employer est.)"
    assert "Developing multimodal" in job.description
    assert job.posted_date == "24h"

    # Verify 24h resolves to today's date
    parsed = parse_posted_date(job.posted_date)
    assert parsed == utc_now().date()

    # Glassdoor bare 'Remote' without worldwide/APAC/ME/B2B marker is dropped as domestic US
    from src.models import is_worldwide_remote
    assert not is_worldwide_remote(job.location, source=job.source, description=job.description)
    # But Glassdoor with explicit worldwide/B2B/APAC/ME is accepted
    assert is_worldwide_remote("Remote (Worldwide)", source=job.source, description=job.description)
    assert is_worldwide_remote("Middle East (Remote)", source=job.source, description=job.description)
    assert is_worldwide_remote("Remote", source=job.source, description="Worldwide remote team hiring B2B.")


def test_glassdoor_relative_date_variations():
    today = date(2026, 9, 17)
    assert parse_posted_date("24h", today=today) == today
    assert parse_posted_date("12h", today=today) == today
    assert parse_posted_date("1d", today=today) == today - timedelta(days=1)
    assert parse_posted_date("2d", today=today) == today - timedelta(days=2)
    assert parse_posted_date("30d+", today=today) == today - timedelta(days=30)
    assert parse_posted_date("Just now", today=today) == today


def test_canonical_job_urls():
    # Indeed jk
    assert canonical_job_url("https://www.indeed.com/rc/clk?jk=fa12345678&from=vjs", source="indeed") == "https://www.indeed.com/viewjob?jk=fa12345678"
    # Glassdoor jl & jobListingId
    assert canonical_job_url("https://www.glassdoor.com/Job/jobs.htm?jl=123456789&guid=abc", source="glassdoor") == "https://www.glassdoor.com/job-listing/?jl=123456789"
    assert canonical_job_url("https://www.glassdoor.com/partner/jobListing.htm?jobListingId=987654321&pos=101", source="glassdoor") == "https://www.glassdoor.com/job-listing/?jl=987654321"
