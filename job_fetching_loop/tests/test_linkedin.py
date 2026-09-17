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