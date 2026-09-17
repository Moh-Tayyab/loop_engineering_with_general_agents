"""Tests for the LinkedIn scraper's hiring-feed-post mapping (pure helpers).
The DOM extraction itself is guarded and can't be exercised offline; these
tests lock the mapping heuristics that turn a scraped post dict into a Job.
"""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote_plus

from src.scrapers.linkedin import _feed_post_to_raw, _post_location, _feed_queries, LinkedInScraper

AWS = timezone.utc


def _post(**over):
    base = {
        "author": "Sara Ali",
        "headline": "Sara Ali is hiring an ML Engineer",
        "text": "We are looking for a senior Machine Learning engineer to join our remote team. "
                "Full-time, flexible. DM me or apply below.",
        "url": "https://www.linkedin.com/feed/update/urn:li:activity:7123456789",
        "posted": "2026-09-14T08:00:00+00:00",
    }
    base.update(over)
    return base


def test_feed_url_encodes_keyword():
    url = LinkedInScraper._FEED.format(kw="machine+learning")
    assert url.startswith("https://www.linkedin.com/search/content/all/")
    assert "machine+learning" in url


def test_feed_post_maps_to_raw_job():
    raw = _feed_post_to_raw(_post(), "ML")
    assert raw is not None
    assert raw.source == "linkedin"
    assert raw.company == "Sara Ali"
    assert "ML Engineer" in raw.title
    assert raw.url.startswith("https://www.linkedin.com/feed/update/")
    assert raw.location == "Remote"
    assert raw.posted_date == "2026-09-14"
    assert "machine learning" in (raw.description or "").lower()
    assert raw.tags == ["ML"]


def test_feed_post_uses_headline_as_title():
    raw = _feed_post_to_raw(_post(), "ML")
    assert raw is not None
    assert raw.title == "Sara Ali is hiring an ML Engineer"


def test_feed_post_title_falls_back_to_first_sentence():
    no_headline = _post(headline="")
    raw = _feed_post_to_raw(no_headline, "ML")
    assert raw is not None
    assert raw.title.startswith("We are looking for a senior Machine Learning engineer")


def test_feed_post_skips_old_post_outside_window():
    posted_after = datetime(2026, 9, 15, 9, 0, tzinfo=AWS)
    raw = _feed_post_to_raw(_post(), "ML", posted_after)
    assert raw is None


def test_feed_post_keeps_post_inside_window():
    posted_after = datetime(2026, 9, 13, 0, 0, tzinfo=AWS)
    raw = _feed_post_to_raw(_post(), "ML", posted_after)
    assert raw is not None


def test_feed_post_missing_url_rejected():
    assert _feed_post_to_raw(_post(url=""), "ML") is None


def test_feed_post_missing_text_rejected():
    assert _feed_post_to_raw(_post(text=""), "ML") is None


def test_post_location_remote_markers():
    assert _post_location("We are hiring, fully remote, worldwide.") == "Remote"
    assert _post_location("WFH ok, work from home allowed") == "Remote"


def test_post_location_explicit_onsite_hybrid():
    assert _post_location("On-site in Lahore, 5 days a week.") == "Hybrid"
    assert _post_location("Hybrid role in the Karachi office.") == "Hybrid"


def test_post_location_defaults_remote():
    assert _post_location("Looking for an ML engineer to grow our team") == "Remote"
    assert _post_location("") == "Remote"


# ── _feed_queries: Friday "we are hiring" scene phrasing ─────────────────────

def test_feed_queries_non_friday_single_query_per_keyword():
    """Mon-Thu: plain keyword only (no extra hiring-scene phrasing)."""
    queries = _feed_queries(["AI", "Machine Learning"], weekday=0)  # Monday
    assert queries == ["AI", "Machine Learning"]


def test_feed_queries_friday_adds_hiring_scenes():
    """Friday: + two extra hiring-scene phrases per keyword (spec'd feed day)."""
    queries = _feed_queries(["AI"], weekday=4)  # Friday
    assert len(queries) == 3
    assert queries[0] == "AI"
    assert "#hiring AI" in queries
    assert '"we are hiring" AI' in queries


def test_feed_queries_friday_preserves_keyword_order():
    queries = _feed_queries(["AI", "LLM"], weekday=4)
    # plain query first for each kw, then scene variants interleaved
    assert queries[0] == "AI"
    assert queries[3] == "LLM"


def test_feed_url_uses_quote_plus_for_hiring_phrase():
    """Hiring-scene phrases must be URL-encoded (spaces + quotes) via quote_plus."""
    queries = _feed_queries(["AI"], weekday=4)
    for q in queries:
        url = LinkedInScraper._FEED.format(kw=quote_plus(q))
        assert " " not in url
        if '"we are hiring"' in q:
            assert "%22" in url  # double-quote encoded


# ── Outage honesty tests ─────────────────────────────────────────────────────

def test_linkedin_guest_public_outage_raises_on_failure(monkeypatch):
    import pytest
    import requests
    from datetime import datetime, timezone
    from src.scrapers.linkedin import LinkedInScraper

    def fail(*a, **kw):
        raise requests.ConnectionError("LinkedIn blocked or offline")

    monkeypatch.setattr(requests, "get", fail)
    scraper = LinkedInScraper()
    with pytest.raises(requests.ConnectionError):
        list(scraper.fetch(["AI"], datetime.now(timezone.utc)))


def test_linkedin_guest_public_http_error_raises_when_all_fail(monkeypatch):
    import pytest
    import requests
    from unittest.mock import MagicMock
    from datetime import datetime, timezone
    from src.scrapers.linkedin import LinkedInScraper

    mock_resp = MagicMock()
    mock_resp.status_code = 429
    monkeypatch.setattr(requests, "get", lambda *a, **k: mock_resp)

    scraper = LinkedInScraper()
    with pytest.raises(requests.HTTPError):
        list(scraper.fetch(["AI"], datetime.now(timezone.utc)))


def test_linkedin_feed_pass_runs_when_session_and_feed_enabled(monkeypatch):
    """When an authenticated session exists and SOURCE_LINKEDIN_FEED=1,

    the feed pass (_gather) must execute.
    """
    from unittest.mock import MagicMock
    from src.scrapers.linkedin import LinkedInScraper

    monkeypatch.setenv("SOURCE_LINKEDIN_FEED", "1")
    scraper = LinkedInScraper()

    # Mock authenticated session
    monkeypatch.setattr(scraper, "has_authenticated_session", lambda: True)
    monkeypatch.setattr(scraper, "_fetch_guest_public", lambda kw, dt: iter([]))

    gather_called = False

    async def mock_gather(kw, dt):
        nonlocal gather_called
        gather_called = True
        return []

    monkeypatch.setattr(scraper, "_gather", mock_gather)

    list(scraper.fetch(["AI"], datetime.now(timezone.utc)))
    assert gather_called is True


def test_linkedin_feed_pass_skipped_when_disabled_or_no_session(monkeypatch):
    """When SOURCE_LINKEDIN_FEED=0 or no session exists, _gather must not be called."""
    from src.scrapers.linkedin import LinkedInScraper

    scraper = LinkedInScraper()
    monkeypatch.setattr(scraper, "_fetch_guest_public", lambda kw, dt: iter([]))

    gather_called = False

    async def mock_gather(kw, dt):
        nonlocal gather_called
        gather_called = True
        return []

    monkeypatch.setattr(scraper, "_gather", mock_gather)

    # 1. No session, but feed enabled
    monkeypatch.setenv("SOURCE_LINKEDIN_FEED", "1")
    monkeypatch.setattr(scraper, "has_authenticated_session", lambda: False)
    list(scraper.fetch(["AI"], datetime.now(timezone.utc)))
    assert gather_called is False

    # 2. Session exists, but feed disabled
    monkeypatch.setenv("SOURCE_LINKEDIN_FEED", "0")
    monkeypatch.setattr(scraper, "has_authenticated_session", lambda: True)
    list(scraper.fetch(["AI"], datetime.now(timezone.utc)))
    assert gather_called is False


def test_linkedin_guest_search_drops_onsite_and_keeps_remote(monkeypatch):
    """Verify that LinkedIn search drops physical city postings without remote marker in title/loc."""
    from src.scrapers.linkedin import LinkedInScraper
    import requests

    search_html = """
    <div class="base-card">
      <h3 class="base-search-card__title">Senior Data Engineer</h3>
      <h4 class="base-search-card__subtitle"><a href="#">Smart Working</a></h4>
      <span class="job-search-card__location">Islamabad, Islāmābād, Pakistan</span>
      <a class="base-card__full-link" href="https://pk.linkedin.com/jobs/view/smart-working-4467172677"></a>
      <time datetime="2026-09-17"></time>
    </div>
    <div class="base-card">
      <h3 class="base-search-card__title">Senior Software Engineer</h3>
      <h4 class="base-search-card__subtitle"><a href="#">Trellions</a></h4>
      <span class="job-search-card__location">Pakistan</span>
      <a class="base-card__full-link" href="https://pk.linkedin.com/jobs/view/trellions-4467121181"></a>
      <time datetime="2026-09-17"></time>
    </div>
    <div class="base-card">
      <h3 class="base-search-card__title">Senior AI Engineer (Remote)</h3>
      <h4 class="base-search-card__subtitle"><a href="#">Acme AI</a></h4>
      <span class="job-search-card__location">Pakistan</span>
      <a class="base-card__full-link" href="https://pk.linkedin.com/jobs/view/acme-4467999999"></a>
      <time datetime="2026-09-17"></time>
    </div>
    """

    class MockResponse:
        def __init__(self, text, status_code=200):
            self.text = text
            self.status_code = status_code
            self.url = "https://linkedin.com"

    def mock_get(url, **kwargs):
        if "seeMoreJobPostings" in url:
            return MockResponse(search_html)
        if "4467172677" in url:
            return MockResponse('<div class="show-more-less-html__markup">Work in our team in a remote-first world</div>')
        if "4467121181" in url:
            return MockResponse('<div class="show-more-less-html__markup">Work remotely with US clients</div>')
        if "4467999999" in url:
            return MockResponse('<div class="show-more-less-html__markup">100% remote work from home</div>')
        return MockResponse("", status_code=404)

    monkeypatch.setattr(requests, "get", mock_get)
    scraper = LinkedInScraper()
    jobs = list(scraper._fetch_guest_public(["AI"], datetime(2026, 9, 1, tzinfo=timezone.utc)))

    # Only the genuine remote job (with (Remote) in title) must be yielded
    titles = [j.title for j in jobs]
    assert "Senior Data Engineer" not in titles
    assert "Senior Software Engineer" not in titles
    assert "Senior AI Engineer (Remote)" in titles