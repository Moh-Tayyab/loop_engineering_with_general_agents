"""Tests for Indeed and Glassdoor scrapers — DOM card parsing, relative date extraction,
canonical URL generation, and source registry verification.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
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


# ── Beat 159: full-JD pane must open for ANY pilot profile (not AI-only) ─────

async def _noop_click(*args, **kwargs):
    return None


async def _noop_pause(*args, **kwargs):
    return None


def _odi_card(title_text: str, desc_sel: str):
    mock_title = MockElement(text=title_text, attrs={"href": "/viewjob?jk=odi123", "title": title_text})
    mock_company = MockElement(text="Bank")
    mock_location = MockElement(text="Remote")
    mock_desc = MockElement(text="ODI ETL role.")
    mock_date = MockElement(text="Just posted")
    return MockElement(
        attrs={"data-jk": "odi123"},
        children={
            "h2.jobTitle a": mock_title,
            "span[data-testid='company-name']": mock_company,
            "div[data-testid='text-location']": mock_location,
            desc_sel: mock_desc,
            "span.date": mock_date,
        },
    )


def test_indeed_full_desc_opens_for_odi_profile(monkeypatch):
    """ODI title must trigger the right-pane full-JD read (was AI-only gate)."""
    import src.scrapers.indeed as indeed_mod
    monkeypatch.setattr(indeed_mod, "human_click", _noop_click)
    monkeypatch.setattr(indeed_mod, "human_read_pause", _noop_pause)
    full = "ODI mappings, FSDM data model, FCCM AML monitoring, ETL batches. " * 20
    page = MockElement(children={"#jobDescriptionText": MockElement(text=full)})
    scraper = IndeedScraper()
    job = asyncio.run(scraper._parse_card(_odi_card("Oracle ODI Developer", "div.job-snippet"), "ODI", page=page))
    assert job is not None
    assert "FCCM AML monitoring" in (job.description or "")
    assert len(job.description or "") > len("ODI ETL role.")


def test_glassdoor_full_desc_opens_for_odi_profile(monkeypatch):
    """Same any-profile gate on the Glassdoor right-pane read."""
    import src.scrapers.glassdoor as gd_mod
    monkeypatch.setattr(gd_mod, "human_click", _noop_click)
    monkeypatch.setattr(gd_mod, "human_read_pause", _noop_pause)
    full = "OFSAA FCCM implementation, KYC scenarios, Oracle Mantas support. " * 20
    page = MockElement(children={"div#JobDescriptionContainer": MockElement(text=full)})
    mock_title = MockElement(text="FCCM Consultant", attrs={"href": "/job-listing/?jl=777"})
    mock_desc = MockElement(text="FCCM role.")
    mock_date = MockElement(text="24h")
    card = MockElement(children={
        "a[data-test='job-title']": mock_title,
        "div.JobCard_jobDescription__v_1k2": mock_desc,
        "div[data-test='job-age']": mock_date,
    })
    scraper = GlassdoorScraper()
    job = asyncio.run(scraper._parse_card(card, "FCCM", page=page))
    assert job is not None
    assert "Oracle Mantas" in (job.description or "")


# ── Glassdoor Scraper Tests ───────────────────────────────────────────────────

def test_glassdoor_missing_location_not_fabricated():
    """PR #13 nit / A2: missing location element must stay None, never 'Remote'."""
    scraper = GlassdoorScraper()
    mock_title = MockElement(text="AI Engineer", attrs={"href": "/partner/jobListing.htm?jobListingId=555", "title": "AI Engineer"})
    mock_desc = MockElement(text="Fully remote role for our global team.")
    mock_date = MockElement(text="24h")
    card = MockElement(
        children={
            "a[data-test='job-title']": mock_title,
            "div.JobCard_jobDescription__v_1k2": mock_desc,
            "div[data-test='job-age']": mock_date,
        },
    )
    job = asyncio.run(scraper._parse_card(card, "AI"))
    assert job is not None
    assert job.location is None
    from src.models import is_worldwide_remote
    assert not is_worldwide_remote(job.location, source="glassdoor", description=job.description)


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


# ── Beat 164: Glassdoor URL backstop + UI filters + full-JD per card ──────────

def test_glassdoor_search_url_backstop_no_easy_apply_by_default(monkeypatch):
    """Owner removed the Easy Apply filter: default URL has fromAge + Remote,
    and NO easyApplyOnly unless EASY_APPLY_ONLY=1."""
    monkeypatch.delenv("EASY_APPLY_ONLY", raising=False)
    s = GlassdoorScraper()
    url = s._search_url("AI Engineer", 1, 2)
    assert "fromAge=1" in url
    assert "locKeyword=Remote" in url
    assert "sc.keyword=AI+Engineer" in url
    assert "page=2" in url
    assert "easyApplyOnly" not in url


def test_glassdoor_search_url_easy_apply_opt_in(monkeypatch):
    monkeypatch.setenv("EASY_APPLY_ONLY", "1")
    s = GlassdoorScraper()
    assert "easyApplyOnly=true" in s._search_url("AI Engineer", 1, 1)


def test_glassdoor_ui_filters_best_effort_nothing_found():
    """No filter buttons on the page → no raise, URL backstop holds."""
    s = GlassdoorScraper()
    page = AsyncMock()
    page.query_selector = AsyncMock(return_value=None)
    asyncio.run(s._apply_search_filters_ui(page, 1))
    assert page.query_selector.await_count >= 1


def test_glassdoor_ui_filters_clicks_remote_and_apply(monkeypatch):
    """Remote-only chip + Apply filters get clicked when visible."""
    import src.scrapers.glassdoor as gd_mod
    s = GlassdoorScraper()

    class FakeEl:
        async def is_visible(self):
            return True

    page = AsyncMock()
    page.query_selector = AsyncMock(return_value=FakeEl())
    clicks = []
    monkeypatch.setattr(gd_mod, "human_click", AsyncMock(side_effect=lambda p, e: clicks.append(e)))
    asyncio.run(s._apply_search_filters_ui(page, 1))
    # date-filter btn + date option + remote chip + apply button
    assert len(clicks) >= 3


def test_glassdoor_parse_card_reads_full_desc_unconditionally(monkeypatch):
    """Every card's right-pane JD is read — no profile/snippet gate. A junior
    off-profile title still gets its full description attached."""
    import src.scrapers.glassdoor as gd_mod
    s = GlassdoorScraper()
    full = "COMPLETE job description. " * 50  # 1250 chars, beats any snippet

    title_el = MockElement(text="Junior Office Assistant", attrs={"href": "/job-listing/?jl=555"})
    card = MockElement(
        text="Junior Office Assistant\nUnknown\nSnippet short",
        children={"a[data-test='job-title']": title_el},
    )

    class FakePane:
        async def inner_text(self):
            return full
        async def is_visible(self):
            return True

    page = AsyncMock()
    async def fake_qs(sel):
        if "Show more" in sel:
            return None
        if "JobDetails_jobDescription" in sel or "job-description" in sel or "JobDescriptionContainer" in sel:
            return FakePane()
        return None
    page.query_selector = fake_qs
    monkeypatch.setattr(gd_mod, "human_click", AsyncMock())
    monkeypatch.setattr(gd_mod, "human_read_pause", AsyncMock())
    job = asyncio.run(s._parse_card(card, "AI Engineer", 1, page=page))
    assert job is not None
    assert job.description is not None and job.description.startswith("COMPLETE job description.")
    assert len(job.description) > 1000


# ── Beat 165: Indeed URL backstop + UI filters + full-JD per card ─────────────

def test_indeed_search_url_backstop_no_easy_apply_by_default(monkeypatch):
    """Owner removed the Easy Apply filter: default URL has fromage + Remote
    + remote-only facet, and NO iaFilter unless EASY_APPLY_ONLY=1."""
    monkeypatch.delenv("EASY_APPLY_ONLY", raising=False)
    s = IndeedScraper()
    url = s._search_url("AI Engineer", 1, 10)
    assert "fromage=1" in url
    assert "l=Remote" in url
    assert "DSQF7" in url
    assert "start=10" in url
    assert "iaFilter" not in url


def test_indeed_search_url_easy_apply_opt_in(monkeypatch):
    monkeypatch.setenv("EASY_APPLY_ONLY", "1")
    s = IndeedScraper()
    assert "iaFilter=1" in s._search_url("AI Engineer", 1, 0)


def test_indeed_ui_filters_best_effort_nothing_found():
    """No filter controls on the page → no raise, URL backstop holds."""
    s = IndeedScraper()
    page = AsyncMock()
    page.query_selector = AsyncMock(return_value=None)
    asyncio.run(s._apply_search_filters_ui(page, 1))
    assert page.query_selector.await_count >= 1


def test_indeed_ui_filters_clicks_date_and_remote(monkeypatch):
    """Date-posted button + option and the Remote chip get clicked."""
    import src.scrapers.indeed as in_mod
    s = IndeedScraper()

    class FakeEl:
        async def is_visible(self):
            return True

    page = AsyncMock()
    page.query_selector = AsyncMock(return_value=FakeEl())
    clicks = []
    monkeypatch.setattr(in_mod, "human_click", AsyncMock(side_effect=lambda p, e: clicks.append(e)))
    asyncio.run(s._apply_search_filters_ui(page, 1))
    # date button + date option + remote chip
    assert len(clicks) >= 3


def test_indeed_parse_card_reads_full_desc_unconditionally(monkeypatch):
    """Every card's right-pane JD is read — no profile/snippet gate."""
    import src.scrapers.indeed as in_mod
    s = IndeedScraper()
    full = "FULL Indeed job description. " * 50  # 1500 chars, beats any snippet

    title_el = MockElement(text="Junior Office Assistant", attrs={"href": "/rc/clk?jk=abc123"})
    card = MockElement(
        text="Junior Office Assistant\nUnknown\nJust posted\nSnippet short",
        attrs={"data-jk": "abc123"},
        children={"h2.jobTitle a": title_el},
    )

    class FakePane:
        async def inner_text(self):
            return full

    page = AsyncMock()
    page.query_selector = AsyncMock(return_value=FakePane())
    monkeypatch.setattr(in_mod, "human_click", AsyncMock())
    monkeypatch.setattr(in_mod, "human_read_pause", AsyncMock())
    job = asyncio.run(s._parse_card(card, "AI Engineer", 1, page=page))
    assert job is not None
    assert job.description is not None and job.description.startswith("FULL Indeed job description.")
    assert len(job.description) > 1000


# ── Beat 167: checker MINOR #1 — stable hooks first, no decoy clicks ──────────

def test_glassdoor_remote_hook_leads_and_no_bare_apply(monkeypatch):
    """`[data-test]` remote hook is tried before page-wide text selectors, and
    no substring 'Apply' selector can match a job 'Apply now' button."""
    import src.scrapers.glassdoor as gd_mod
    s = GlassdoorScraper()

    class FakeEl:
        async def is_visible(self):
            return False  # force full sweep so every selector is attempted

    seen: list[str] = []
    page = AsyncMock()
    async def fake_qs(sel):
        seen.append(sel)
        return FakeEl()
    page.query_selector = fake_qs
    monkeypatch.setattr(gd_mod, "human_click", AsyncMock())
    asyncio.run(s._apply_search_filters_ui(page, 1))
    remote_sels = [x for x in seen if "emote" in x]
    assert remote_sels, "expected remote-only selectors to be attempted"
    assert "data-test" in remote_sels[0], f"stable hook must lead, got: {remote_sels[0]}"
    assert "button:has-text('Apply')" not in seen, "bare substring Apply must be gone"
    assert any("text-is('Apply')" in x for x in seen), "exact-match Apply fallback expected"


def test_indeed_remote_hook_leads(monkeypatch):
    """`[data-testid]` remote hook is tried before page-wide text selectors."""
    import src.scrapers.indeed as in_mod
    s = IndeedScraper()

    class FakeEl:
        async def is_visible(self):
            return False

    seen: list[str] = []
    page = AsyncMock()
    async def fake_qs(sel):
        seen.append(sel)
        return FakeEl()
    page.query_selector = fake_qs
    monkeypatch.setattr(in_mod, "human_click", AsyncMock())
    asyncio.run(s._apply_search_filters_ui(page, 1))
    remote_sels = [x for x in seen if "emote" in x]
    assert remote_sels, "expected remote selectors to be attempted"
    assert "data-testid" in remote_sels[0], f"stable hook must lead, got: {remote_sels[0]}"


# ── Beat 171: deep pagination + worldwide-remote backstop ─────────────────────

def test_deep_pagination_depth_both_boards():
    """Owner (worldwide fully-remote MAXIMUM jobs): 5 pages/starts per keyword."""
    assert GlassdoorScraper._PAGES == (1, 2, 3, 4, 5)
    assert IndeedScraper._STARTS == (0, 10, 20, 30, 40)


def test_browser_source_timeout_default_900_for_deep_scrape(monkeypatch):
    """Deep fan-out (5 domains × 5 pages × full-JD) needs the 15min board cap."""
    import src.config as cfg

    monkeypatch.delenv("BROWSER_SOURCE_TIMEOUT_S", raising=False)
    monkeypatch.delenv("JOB_LOOP_CLOUD", raising=False)
    assert cfg.source_timeout_s("indeed") == 900.0
    assert cfg.source_timeout_s("glassdoor") == 900.0
    assert cfg.source_timeout_s("linkedin") != 900.0  # LinkedIn keeps its own caps
