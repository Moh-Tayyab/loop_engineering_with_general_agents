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
    assert url.startswith("https://www.linkedin.com/search/results/content/")
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


def test_feed_post_educational_content_rejected():
    raw = _feed_post_to_raw(_post(text="What is the difference between AI vs machine learning? A simple explanation."), "ML")
    assert raw is None


def test_feed_post_career_commentary_rejected():
    raw = _feed_post_to_raw(_post(text="The biggest threat to your career isn't the technology itself."), "ML")
    assert raw is None


def test_feed_post_hiring_intent_accepted():
    raw = _feed_post_to_raw(
        _post(text="We are looking for a senior Machine Learning engineer — apply now. Fully remote worldwide."),
        "ML",
    )
    assert raw is not None


def test_feed_post_missing_text_rejected():
    assert _feed_post_to_raw(_post(text=""), "ML") is None


def test_feed_post_body_capture_length():
    """Regression: feed post must carry a non-trivial description body
    (Beat 100b empty-body blinded Rule 11; snippet now caps at 2000)."""
    raw = _feed_post_to_raw(_post(), "ML")
    assert raw is not None
    assert raw.description is not None
    assert len(raw.description) >= 50
    assert "remote team" in raw.description.lower()


def test_post_location_remote_markers():
    assert _post_location("We are hiring, fully remote, worldwide.") == "Remote"
    assert _post_location("WFH ok, work from home allowed") == "Remote"


def test_post_location_explicit_onsite_hybrid():
    assert _post_location("On-site in Lahore, 5 days a week.") == "Hybrid"
    assert _post_location("Hybrid role in the Karachi office.") == "Hybrid"


def test_post_location_defaults_fail_closed():
    """Beat 105 / A1: no location signal → empty string (caller drops), never invented Remote."""
    assert _post_location("Looking for an ML engineer to grow our team") == ""
    assert _post_location("") == ""


def test_post_location_surfaces_foreign_markers():
    """Strict-location law: a post naming a restricted foreign country or region
    must NOT masquerade as worldwide bare "Remote" (which the gate passes)."""
    assert _post_location("We're hiring a remote AI engineer, UK-based.") == "UK (Remote)"
    assert _post_location("Join our team in Poland! Remote OK.") == "Poland (Remote)"
    assert _post_location("Remote role with our Latin America team.") == "Latin America (Remote)"


def test_post_location_foreign_marker_overridden_by_in_scope():
    """Worldwide / APAC / B2B qualifiers keep the post in-scope as Remote."""
    assert _post_location("Remote ML engineer, worldwide. ") == "Remote"
    assert _post_location("Hiring in APAC — AI engineer, fully remote.") == "Remote"
    assert _post_location("B2B contractor, remote from anywhere.") == "Remote"


def test_post_location_physical_gulf_city_rejected():
    """Rule 11: naming a physical Gulf/Middle East city without an explicit
    anywhere-remote marker is on-site → must be surfaced as Hybrid, never Remote."""
    assert _post_location("We're hiring across AI in Dammam, Saudi Arabia.") == "Hybrid"
    assert _post_location("Looking for engineers based in Riyadh.") == "Hybrid"
    assert _post_location("Join our Dubai office, AI team.") == "Hybrid"


def test_post_location_physical_apac_city_rejected():
    """Beat 105 / A1: non-Gulf APAC metros must not fall through to Remote."""
    assert _post_location("Hiring ML Engineer - must be based in Karachi.") == "Hybrid"
    assert _post_location("Looking for engineers based in Lahore.") == "Hybrid"
    assert _post_location("Join our Dhaka office, AI team.") == "Hybrid"
    assert _post_location("Remote role based in Manila only.") == "Hybrid"


def test_post_location_remote_gulf_stays_remote():
    """Explicit remote qualifier keeps an otherwise-city post in-scope."""
    assert _post_location("Remote in Dubai, worldwide OK.") == "Remote"


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
    from datetime import datetime, timedelta, timezone
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
    from datetime import datetime, timedelta, timezone
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
    monkeypatch.setenv("LINKEDIN_FEED_EVERYDAY", "1")
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


def test_linkedin_feed_pass_skipped_on_monday(monkeypatch):
    """On Monday, feed pass is skipped even if session exists (Jobs section only)."""
    from src.scrapers.linkedin import LinkedInScraper

    monkeypatch.setenv("SOURCE_LINKEDIN_FEED", "1")
    monkeypatch.delenv("LINKEDIN_FEED_EVERYDAY", raising=False)
    scraper = LinkedInScraper()

    # Mock Monday
    monkeypatch.setattr("src.scrapers.linkedin.utc_now", lambda: datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(scraper, "has_authenticated_session", lambda: True)
    monkeypatch.setattr(scraper, "_fetch_guest_public", lambda kw, dt: iter([]))

    gather_called = False

    async def mock_gather(kw, dt):
        nonlocal gather_called
        gather_called = True
        return []

    monkeypatch.setattr(scraper, "_gather", mock_gather)

    list(scraper.fetch(["AI"], datetime.now(timezone.utc)))
    assert gather_called is False


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


def test_linkedin_guest_search_easy_apply_and_exp_level(monkeypatch):
    """Verify that easy_apply_only adds f_AL=true and exp_levels adds f_E=2,3,4 to search URL."""
    import requests
    from src import config as cfg

    captured_urls = []

    class MockResponse:
        def __init__(self, text, status_code=200):
            self.text = text
            self.status_code = status_code
            self.url = "https://linkedin.com"

    def mock_get(url, **kwargs):
        captured_urls.append(url)
        return MockResponse("", status_code=200)

    monkeypatch.setattr(requests, "get", mock_get)
    monkeypatch.setenv("EASY_APPLY_ONLY", "1")
    monkeypatch.setenv("LINKEDIN_EXPERIENCE_LEVELS", "2,3,4")

    scraper = LinkedInScraper()
    list(scraper._fetch_guest_public(["AI"], datetime(2026, 9, 1, tzinfo=timezone.utc)))

    assert len(captured_urls) > 0
    first_search = captured_urls[0]
    assert "f_AL=true" in first_search
    assert "f_E=2,3,4" in first_search
    assert "f_WT=2" in first_search


def test_linkedin_guest_search_omits_exp_level_by_default(monkeypatch):
    """Verify that by default f_E is not appended to the search URL."""
    import requests

    captured_urls = []

    class MockResponse:
        def __init__(self, text, status_code=200):
            self.text = text
            self.status_code = status_code
            self.url = "https://linkedin.com"

    def mock_get(url, **kwargs):
        captured_urls.append(url)
        return MockResponse("", status_code=200)

    monkeypatch.setattr(requests, "get", mock_get)
    monkeypatch.delenv("LINKEDIN_EXPERIENCE_LEVELS", raising=False)

    scraper = LinkedInScraper()
    list(scraper._fetch_guest_public(["AI"], datetime(2026, 9, 1, tzinfo=timezone.utc)))

    assert len(captured_urls) > 0
    first_search = captured_urls[0]
    assert "f_E=" not in first_search


def test_post_location_onsite_and_us_restrictions():
    from src.scrapers.linkedin import _post_location, _feed_post_to_raw

    # Onsite in Lahore with #RemoteJobs hashtag spam must be detected as Hybrid/Onsite
    t_lahore = (
        "📢 Career Opportunity – Junior AI Engineer | Quality Resource (PVT) LTD\n"
        "💼 Junior AI Engineer\n"
        "📍 Gulberg, Lahore | Onsite\n"
        "💰 PKR 50,000 – 65,000/month\n"
        "#Hiring #AIML #SoftwareEngineer #RemoteJobs"
    )
    assert _post_location(t_lahore) == "Hybrid"
    assert _feed_post_to_raw({"text": t_lahore, "url": "https://linkedin.com/jobs/view/123"}, "AI") is None

    # US Domestic location
    t_us = "Hiring: AI/ML Software Engineer\nRemote — Tampa, FL, USA\n#Hiring #AIML #RemoteJobs"
    assert _post_location(t_us) == "USA (Remote)"

    # Profile URLs must be rejected
    assert _feed_post_to_raw({
        "text": "We are hiring Senior ML Engineer, 100% remote worldwide. Apply: hr@doux.com",
        "url": "https://www.linkedin.com/in/some-person/",
    }, "AI") is None

    # India remote feed posts must be rejected
    t_india = "We are hiring: AI Trainer / Agentic AI Trainer\nLocation: Bangalore, India (Remote)\n#Hiring #AIML"
    assert _feed_post_to_raw({
        "text": t_india,
        "url": "https://www.linkedin.com/feed/update/urn:li:activity:987654321/",
    }, "AI") is None

    # Valid Worldwide remote post with activity permalink must be accepted
    t_world = "We are hiring a Lead AI Engineer! 100% Remote - Worldwide. Apply here: jobs@domain.com"
    raw_world = _feed_post_to_raw({
        "text": t_world,
        "url": "https://www.linkedin.com/feed/update/urn:li:activity:123456789/",
    }, "AI")
    assert raw_world is not None
    assert raw_world.url == "https://www.linkedin.com/feed/update/urn:li:activity:123456789/"

# ── Beat 172: board search carries the guest-pass worldwide filters ───────────

def test_linkedin_board_url_worldwide_remote_recency():
    """Authenticated board URL must mirror guest filters: remote-only (f_WT=2),
    Worldwide, newest-first, past-24h TPR — no Easy Apply unless opted in."""
    from datetime import datetime, timedelta, timezone
    from src.scrapers.linkedin import LinkedInScraper

    now = datetime.now(timezone.utc)
    url = LinkedInScraper._board_url("AI Engineer", now - timedelta(hours=12))
    assert "keywords=AI+Engineer" in url
    assert "f_WT=2" in url
    assert "location=Worldwide" in url
    assert "sortBy=DD" in url
    assert "f_TPR=r86400" in url  # clamped to 24h minimum
    assert "f_AL" not in url


def test_linkedin_board_url_tpr_scales_with_window():
    from datetime import datetime, timedelta, timezone
    from src.scrapers.linkedin import LinkedInScraper

    now = datetime.now(timezone.utc)
    url = LinkedInScraper._board_url("AI Engineer", now - timedelta(days=3))
    assert "f_TPR=r259200" in url


# ── Beat 178: card pre-filter skips detail HTTP + hub-first location order ───

def test_linkedin_guest_prefilter_skips_detail_fetch(monkeypatch):
    """A title-hit card (Onsite) must never trigger its detail HTTP — the
    verdict is identical with or without the JD body."""
    from src.scrapers.linkedin import LinkedInScraper

    search_html = """
    <div class="base-card">
      <h3 class="base-search-card__title">AI Engineer (Onsite)</h3>
      <h4 class="base-search-card__subtitle"><a href="#">Avanza</a></h4>
      <span class="job-search-card__location">Pakistan</span>
      <a class="base-card__full-link" href="https://pk.linkedin.com/jobs/view/avanza-4467000001"></a>
      <time datetime="2026-10-08"></time>
    </div>
    <div class="base-card">
      <h3 class="base-search-card__title">Senior AI Engineer (Remote)</h3>
      <h4 class="base-search-card__subtitle"><a href="#">Acme AI</a></h4>
      <span class="job-search-card__location">Pakistan</span>
      <a class="base-card__full-link" href="https://pk.linkedin.com/jobs/view/acme-4467999999"></a>
      <time datetime="2026-10-08"></time>
    </div>
    """

    class MockResponse:
        def __init__(self, text, status_code=200):
            self.text = text
            self.status_code = status_code
            self.url = "https://linkedin.com"

    detail_urls = []

    def mock_get(url, **kwargs):
        if "seeMoreJobPostings" in url:
            return MockResponse(search_html)
        if "jobPosting" in url:
            detail_urls.append(url)
            return MockResponse('<div class="show-more-less-html__markup">100% remote work from home</div>')
        return MockResponse("", status_code=404)

    import requests
    monkeypatch.setattr(requests, "get", mock_get)
    scraper = LinkedInScraper()
    jobs = list(scraper._fetch_guest_public(["AI"], datetime(2026, 10, 7, tzinfo=timezone.utc)))

    assert not any("4467000001" in u for u in detail_urls), "onsite card must skip detail HTTP"
    assert any("4467999999" in u for u in detail_urls), "clean card still verified live"
    assert [j.title for j in jobs] == ["Senior AI Engineer (Remote)"]


def test_linkedin_guest_location_priority_hubs_before_worldwide(monkeypatch):
    """Scarce guest budget goes to Pakistan + ME hubs first, Worldwide last."""
    import requests
    from urllib.parse import parse_qsl, urlparse
    from src.scrapers.linkedin import LinkedInScraper

    seen_locs = []

    class MockResponse:
        def __init__(self, text, status_code=200):
            self.text = text
            self.status_code = status_code
            self.url = "https://linkedin.com"

    def mock_get(url, **kwargs):
        if "seeMoreJobPostings" in url:
            loc = dict(parse_qsl(urlparse(url).query)).get("location", "")
            if loc not in seen_locs:
                seen_locs.append(loc)
            return MockResponse("", status_code=200)
        return MockResponse("", status_code=404)

    monkeypatch.setattr(requests, "get", mock_get)
    scraper = LinkedInScraper()
    list(scraper._fetch_guest_public(["AI"], datetime(2026, 10, 7, tzinfo=timezone.utc)))

    assert seen_locs[0] == "Pakistan"
    assert seen_locs[-1] == "Worldwide"
    assert {"United Arab Emirates", "Saudi Arabia", "Qatar"} <= set(seen_locs)


# ── Beat 180: owner's 4 mismatch cases — line-by-line proof, all 4 stages ────

def _stage_verdicts(title, loc, desc):
    """(prefilter_ok, helper_ok, helper_reason, daily_ok, digest_ok)."""
    from src.location_law import (
        DIGEST_DISQUALIFY,
        GUEST_PREFILTER_DISQUALIFY,
        evaluate,
    )
    from src.main import is_remotely_workable
    from src.models import LOCATION_REMOTE
    from src.scrapers.linkedin import _passes_guest_detail_filters

    pre = evaluate(loc, "linkedin", None, title, disqualify=GUEST_PREFILTER_DISQUALIFY)
    ok, why = _passes_guest_detail_filters(title, loc, desc)
    daily = is_remotely_workable(LOCATION_REMOTE, loc, "linkedin", desc, title)
    digest = evaluate(loc, "linkedin", desc, title, disqualify=DIGEST_DISQUALIFY)
    return pre.ok, ok, why, daily, digest.ok


def test_owner_mismatch_systems_karachi_lahore_offices():
    ok = _stage_verdicts(
        "Forward Deployed Engineer - GenAI", "Karachi / Lahore",
        "We are hiring for our Karachi and Lahore offices. Office-based position.",
    )
    assert ok == (True, False, "worldwide", False, False), ok


def test_owner_mismatch_melior_onsite_position():
    ok = _stage_verdicts(
        "Lead AI/ML Engineer", "Islamabad",
        "THIS IS AN ONSITE POSITION. Work from our Islamabad office.",
    )
    assert ok[0] is True and ok[1] is False and ok[3] is False and ok[4] is False, ok
    assert ok[2] in ("description", "onsite", "worldwide"), ok


def test_owner_mismatch_avanza_onsite_title_prefiltered():
    ok = _stage_verdicts(
        "AI Copilot Architect (Java/Python) (Onsite)", "Pakistan",
        "Join our team. Office based role.",
    )
    assert ok[0] is False, ok  # prefilter kills it: no detail HTTP at all
    assert ok[1] is False and ok[3] is False and ok[4] is False, ok


def test_owner_mismatch_codeninja_lahore_office_no_marker():
    ok = _stage_verdicts(
        "Senior AI Engineer / Agentic AI Architect", "Lahore, Pakistan",
        "Join our Lahore office team. Great culture, on-site collaboration.",
    )
    assert ok == (True, False, "worldwide", False, False), ok


def test_owner_controls_genuine_remote_still_pass():
    ok = _stage_verdicts(
        "Lead Asp.NET Core 8.0 Fullstack Engineer - Remote (Australian Startup)",
        "Pakistan (Remote)",
        "100% remote worldwide contractor role. B2B contract, work from anywhere in Pakistan.",
    )
    assert ok == (True, True, "", True, True), ok
    ok = _stage_verdicts(
        "Applied AI Engineering, Lead", "Turkiye (Global Remote)",
        "Globally distributed remote team. 100% remote, work from anywhere.",
    )
    assert ok == (True, True, "", True, True), ok
