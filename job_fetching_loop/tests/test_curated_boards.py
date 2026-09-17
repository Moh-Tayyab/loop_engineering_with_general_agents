"""Unit tests for curated remote board scrapers — parsers, registry, and
config default-off wiring. No live network; tests exercise the parsing
logic against realistic fixture data sampled from the live API payloads
(verified 2026-09-15).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

import pytest

import src.config as cfg
from src.scrapers import all_scrapers, load_all_scrapers
from src.scrapers.curated_boards import (
    HimalayasScraper,
    JustRemoteScraper,
    RemotiveScraper,
    WellfoundScraper,
    _extract_apollo_jobs,
    _justremote_card_to_raw,
    _justremote_tag,
    _unix_to_date,
    _wellfound_href_map,
)


# ── Realistic fixture data (field sets + value shapes from live API) ──────────

REMOTIVE_ITEM: dict[str, Any] = {
    "id": 1680495,
    "url": "https://remotive.com/remote-jobs/marketing/remote-office-assistant-1680495",
    "title": "Remote Office Assistant",
    "company_name": "Coalition Technologies ",
    "candidate_required_location": "Worldwide",
    "publication_date": "2026-09-11T20:16:48",
    "salary": "$31,2k- $52k",
    "job_type": "full_time",
    "tags": ["CSS", "excel", "frontend"],
    "description": "<p>Coalition Technologies is seeking a reliable assistant...</p>",
    "category": "Marketing",
}

HIMALAYAS_WORLDWIDE: dict[str, Any] = {
    "title": "Machine Learning Engineer",
    "companyName": "micro1",
    "applicationLink": "https://himalayas.app/companies/micro1/jobs/machine-learning-engineer-1234567890",
    "guid": "https://himalayas.app/companies/micro1/jobs/machine-learning-engineer-1234567890",
    "pubDate": 1780000000,
    "locationRestrictions": [],
    "employmentType": "Full Time",
    "excerpt": "Build ML systems that power...",
    "description": "<p>Build ML systems...</p>",
    "minSalary": None,
    "maxSalary": None,
    "currency": "USD",
    "salaryPeriod": "annual",
}

HIMALAYAS_RESTRICTED: dict[str, Any] = {
    "title": "Senior React Native Developer",
    "companyName": "lemon.io",
    "applicationLink": "https://himalayas.app/companies/lemon-io/jobs/senior-react-native-developer-5236230554",
    "guid": "https://himalayas.app/companies/lemon-io/jobs/senior-react-native-developer-5236230554",
    "pubDate": 1789127040,
    "locationRestrictions": ["United States", "Germany", "Japan"],
    "employmentType": "Contractor",
    "excerpt": "Are you a talented Senior Developer...",
    "description": "<p>Are you a talented Senior Developer...",
    "minSalary": 130000,
    "maxSalary": 200000,
    "currency": "USD",
    "salaryPeriod": "annual",
}


# ── Remotive parser tests ────────────────────────────────────────────────────

def test_remotive_parses_full_item():
    raw = RemotiveScraper()._parse_item(REMOTIVE_ITEM, "AI")
    assert raw is not None
    assert raw.source == "remotive"
    assert raw.title == "Remote Office Assistant"
    assert raw.company == "Coalition Technologies"  # trailing space stripped
    assert raw.url.startswith("https://remotive.com/remote-jobs/")
    assert raw.location == "Worldwide"
    assert raw.salary == "$31,2k- $52k"
    assert raw.posted_date == "2026-09-11"
    assert raw.tags == ["AI"]


def test_remotive_missing_title_returns_none():
    item = {**REMOTIVE_ITEM, "title": ""}
    assert RemotiveScraper()._parse_item(item, "AI") is None


def test_remotive_missing_url_returns_none():
    item = {**REMOTIVE_ITEM, "url": ""}
    assert RemotiveScraper()._parse_item(item, "AI") is None


def test_remotive_missing_location_defaults_remote():
    item = {**REMOTIVE_ITEM, "candidate_required_location": ""}
    raw = RemotiveScraper()._parse_item(item, "AI")
    assert raw.location == "Remote"


def test_remotive_missing_salary_returns_none():
    item = {**REMOTIVE_ITEM, "salary": ""}
    raw = RemotiveScraper()._parse_item(item, "AI")
    assert raw.salary is None


# ── Himalayas parser tests ───────────────────────────────────────────────────

def test_himalayas_worldwide_empty_restrictions():
    raw = HimalayasScraper()._parse_item(HIMALAYAS_WORLDWIDE, "ML")
    assert raw is not None
    assert raw.source == "himalayas"
    assert raw.title == "Machine Learning Engineer"
    assert raw.company == "micro1"
    assert raw.location == "Remote"  # empty list -> worldwide -> Remote
    assert raw.job_type == "Full Time"
    assert raw.posted_date is not None  # unix 1780000000 -> valid date


def test_himalayas_restricted_country_list():
    raw = HimalayasScraper()._parse_item(HIMALAYAS_RESTRICTED, "React")
    assert raw is not None
    assert "United States" in raw.location
    assert "Germany" in raw.location
    assert raw.salary is not None and "130000" in raw.salary
    assert raw.job_type == "Contractor"


def test_himalayas_missing_title_returns_none():
    item = {**HIMALAYAS_WORLDWIDE, "title": ""}
    assert HimalayasScraper()._parse_item(item, "AI") is None


def test_himalayas_missing_applicationLink_returns_none():
    item = {**HIMALAYAS_WORLDWIDE, "applicationLink": "", "guid": ""}
    assert HimalayasScraper()._parse_item(item, "AI") is None


def test_unix_to_date_normal():
    assert _unix_to_date(1789127040) is not None


def test_unix_to_date_zero_returns_none():
    assert _unix_to_date(0) is None


def test_unix_to_date_invalid_returns_none():
    assert _unix_to_date("not-a-number") is None


# ── Wellfound parser tests ───────────────────────────────────────────────────

WELLFOUND_ITEM: dict[str, Any] = {
    "__typename": "JobListing",
    "id": "4717777",
    "slug": "junior-frontend-developer-us-based",
    "title": "Junior Frontend Developer-US Based",
    "compensation": "$45k – $60k",
    "locationNames": ["Anchorage"],
    "acceptedRemoteLocationNames": [],
    "remote": True,
    "liveStartAt": 1789436130,
    "primaryRole": {"__typename": "Role", "slug": "frontend-developer"},
    "startup": {"__ref": "Startup:11225857"},
    "_company": "Zorqiva",
    "_url": "https://wellfound.com/jobs/4717777-junior-frontend-developer-us-based",
}

WELLFOUND_RESTRICTED: dict[str, Any] = {
    **WELLFOUND_ITEM,
    "id": "4302193",
    "title": "Senior Product Manager",
    "acceptedRemoteLocationNames": ["United States", "Canada"],
    "_url": "https://wellfound.com/jobs/4302193-sr-product-manager",
}


def test_wellfound_parses_worldwide_item():
    raw = WellfoundScraper()._parse_item(WELLFOUND_ITEM, "AI")
    assert raw is not None
    assert raw.source == "wellfound"
    assert raw.title == "Junior Frontend Developer-US Based"
    assert raw.company == "Zorqiva"
    assert raw.location == "Remote"  # empty acceptedRemoteLocationNames -> worldwide
    assert raw.salary == "$45k – $60k"
    assert raw.posted_date is not None
    assert raw.job_type == "Remote"


def test_wellfound_restricted_country_list_is_not_remote():
    raw = WellfoundScraper()._parse_item(WELLFOUND_RESTRICTED, "AI")
    assert raw is not None
    assert "United States" in raw.location
    assert raw.location != "Remote"  # downstream classify_location drops this


def test_wellfound_missing_title_returns_none():
    item = {**WELLFOUND_ITEM, "title": ""}
    assert WellfoundScraper()._parse_item(item, "AI") is None


def test_wellfound_missing_url_returns_none():
    item = {**WELLFOUND_ITEM, "_url": ""}
    assert WellfoundScraper()._parse_item(item, "AI") is None


def test_wellfound_get_extracts_apollo_state(monkeypatch):
    import requests

    apollo_data = {
        "JobListing:4717777": {**WELLFOUND_ITEM},
        "Startup:11225857": {"__typename": "Startup", "id": "11225857", "name": "Zorqiva"},
    }
    payload = {"props": {"pageProps": {"apolloState": {"data": apollo_data}}}}
    html = (
        '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(payload) + "</script>"
        '<a href="/jobs/4717777-junior-frontend-developer-us-based">x</a>'
    )

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        @property
        def text(self) -> str:
            return html

    def fake_get(*a, **kw):
        return FakeResponse()

    monkeypatch.setattr(requests, "get", fake_get)
    jobs = WellfoundScraper()._get("AI")
    assert len(jobs) == 1
    assert jobs[0]["_company"] == "Zorqiva"
    assert jobs[0]["_url"] == "https://wellfound.com/jobs/4717777-junior-frontend-developer-us-based"


def test_wellfound_href_map_extracts_real_urls():
    html = '<a href="/jobs/3538367-2-gtm">x</a><a href="/jobs/1-some-role">y</a>'
    hrefs = _wellfound_href_map(html)
    assert hrefs["3538367"] == "https://wellfound.com/jobs/3538367-2-gtm"
    assert hrefs["1"] == "https://wellfound.com/jobs/1-some-role"


def test_wellfound_get_raises_on_network_error(monkeypatch):
    import pytest
    import requests

    def fail(*a, **kw):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(requests, "get", fail)
    with pytest.raises(requests.ConnectionError):
        WellfoundScraper()._get("AI")


def test_extract_apollo_nullsafe_returns_empty_list():
    assert _extract_apollo_jobs({"props": None}) == []
    assert _extract_apollo_jobs({"props": {"pageProps": None}}) == []
    assert _extract_apollo_jobs({"props": {"pageProps": {"apolloState": None}}}) == []
    assert _extract_apollo_jobs(None) == []
    assert _extract_apollo_jobs({}) == []
    assert _extract_apollo_jobs({"props": {"pageProps": {"apolloState": {"data": "not-a-dict"}}}}) == []


# ── JustRemote parser tests ──────────────────────────────────────────────────

def test_justremote_card_to_raw():
    card = {
        "href": "https://justremote.co/remote-manager-exec-jobs/strategic-account-executive-east-launchdarkly",
        "title": "Strategic Account Executive - East",
        "company": "LaunchDarkly",
    }
    raw = _justremote_card_to_raw(card, "AI")
    assert raw is not None
    assert raw.source == "justremote"
    assert raw.title == "Strategic Account Executive - East"
    assert raw.company == "LaunchDarkly"
    assert raw.location == "Remote"
    assert raw.tags == ["AI"]


def test_justremote_card_requires_href_and_title():
    assert _justremote_card_to_raw({"href": "", "title": "X"}, "AI") is None
    assert _justremote_card_to_raw({"href": "https://justremote.co/remote-x-jobs/y", "title": ""}, "AI") is None


def test_justremote_card_rejects_non_job_href():
    card = {"href": "https://justremote.co/remote-jobs/new", "title": "List your position"}
    assert _justremote_card_to_raw(card, "AI") is None


def test_justremote_card_missing_company_unknown():
    card = {"href": "https://justremote.co/remote-developer-jobs/senior-backend-engineer-h", "title": "Senior Backend Engineer"}
    raw = _justremote_card_to_raw(card, "ML")
    assert raw.company == "Unknown"
    assert raw.tags == ["ML"]


def test_justremote_tag_is_string_always():
    assert _justremote_tag(["AI"]) == "AI"
    assert _justremote_tag(["AI", "ML"]) == "AI"
    assert _justremote_tag([]) == "AI"  # default fallback
    assert isinstance(_justremote_tag(["AI"]), str)


# ── Shared _get failure path ─────────────────────────────────────────────────

def test_remotive_get_raises_on_network_error(monkeypatch):
    import pytest
    import requests

    def fail(*a, **kw):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(requests, "get", fail)
    with pytest.raises(requests.ConnectionError):
        RemotiveScraper()._get("AI")

    # fetch() must also propagate when all keywords fail (outage honesty)
    with pytest.raises(requests.ConnectionError):
        list(RemotiveScraper().fetch(["AI"], datetime.now(timezone.utc)))


# ── fetch dedup across keywords ──────────────────────────────────────────────

def test_curated_fetch_deduplicates_same_url_across_keywords(monkeypatch):
    url = "https://example.com/job-123"
    item1 = {**REMOTIVE_ITEM, "url": url}
    item2 = {**REMOTIVE_ITEM, "title": "Duplicate", "url": url}
    calls: list[str] = []

    def fake_get(kw):
        calls.append(kw)
        return [item1] if kw == "AI" else [item2]

    scraper = RemotiveScraper()
    monkeypatch.setattr(scraper, "_get", fake_get)
    jobs = list(scraper.fetch(["AI", "ML"], datetime.now(timezone.utc)))
    assert len(jobs) == 1
    assert calls == ["AI", "ML"]


# ── Registry: all 8 curated boards are registered ───────────────────────────

CURATED_SOURCE_NAMES = [
    "remotive", "himalayas", "wellfound", "justremote",
    "remoteok", "weworkremotely", "jobicy", "nodesk",
    "arbeitnow", "python_org",
]

@pytest.mark.parametrize("name", CURATED_SOURCE_NAMES)
def test_curated_source_is_registered(name):
    load_all_scrapers()
    assert name in all_scrapers(), f"{name} not in registry"


# ── Config default-off wiring ────────────────────────────────────────────────

# ── RemoteOK tests ─────────────────────────────────────────────────────────

def test_remoteok_parse_item():
    from src.scrapers.curated_boards import RemoteokScraper
    item = {
        "id": "1137309",
        "position": "AI Response Analyst",
        "company": "iMerit Technology",
        "url": "https://remoteOK.com/remote-jobs/remote-ai-response-analyst-1137309",
        "location": "",
        "salary_min": 50000,
        "salary_max": 80000,
        "tags": ["content writing", "ai"],
        "date": "2026-09-06T03:47:24+00:00",
        "description": "Evaluate AI responses.",
    }
    job = RemoteokScraper()._parse_item(item, "AI")
    assert job is not None
    assert job.title == "AI Response Analyst"
    assert job.company == "iMerit Technology"
    assert job.location == "Worldwide"
    assert job.salary == "$50000 - $80000"
    assert job.posted_date == "2026-09-06"
    assert "AI" in job.tags


def test_remoteok_skips_legal_notice():
    from src.scrapers.curated_boards import RemoteokScraper
    legal = {"legal": "Please don't scrape."}
    assert RemoteokScraper()._parse_item(legal, "AI") is None


def test_remoteok_missing_url():
    from src.scrapers.curated_boards import RemoteokScraper
    item = {"id": "123", "position": "AI Dev", "url": ""}
    assert RemoteokScraper()._parse_item(item, "AI") is None


LIVE_CURATED = (
    "remotive", "himalayas", "wellfound", "justremote", "remoteok",
    "weworkremotely", "jobicy", "nodesk",
    "arbeitnow", "python_org",
)

@pytest.mark.parametrize("name", LIVE_CURATED)
def test_live_curated_sources_default_enabled(name):
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.delenv(f"SOURCE_{name.upper()}", raising=False)
    assert cfg.source_enabled(name)

def test_live_source_can_be_disabled_via_env():
    import os
    os.environ["SOURCE_REMOTIVE"] = "0"
    assert not cfg.source_enabled("remotive")
    del os.environ["SOURCE_REMOTIVE"]



def test_weworkremotely_feed_parse(monkeypatch):
    from unittest.mock import MagicMock
    from src.scrapers.curated_boards import WeWorkRemotelyScraper
    import requests

    sample_rss = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <item>
          <title>A.Team: Senior Independent AI Engineer</title>
          <link>https://weworkremotely.com/remote-jobs/a-team-ai-engineer</link>
          <region>Anywhere in the World</region>
          <description>Build agentic AI workflows.</description>
          <pubDate>Tue, 15 Sep 2026 12:00:00 +0000</pubDate>
        </item>
      </channel>
    </rss>"""

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = sample_rss
    monkeypatch.setattr(requests, "get", lambda *a, **k: mock_resp)

    scraper = WeWorkRemotelyScraper()
    jobs = list(scraper.fetch(["AI"], datetime(2026, 9, 14, tzinfo=timezone.utc)))
    assert len(jobs) >= 1
    j = jobs[0]
    assert j.source == "weworkremotely"
    assert j.company == "A.Team"
    assert j.title == "Senior Independent AI Engineer"
    assert j.location == "Anywhere in the World"
    assert j.posted_date == "2026-09-15"


def test_jobicy_api_parse(monkeypatch):
    from unittest.mock import MagicMock
    from src.scrapers.curated_boards import JobicyScraper
    import requests

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "jobs": [
            {
                "url": "https://jobicy.com/jobs/153321-postgres-engineer",
                "jobTitle": "Staff AI Systems Engineer",
                "companyName": "Supabase",
                "jobGeo": "Anywhere",
                "pubDate": "2026-09-15T14:25:05+00:00",
                "jobExcerpt": "Design and build AI infrastructure",
                "jobType": ["Full-Time"],
            }
        ]
    }
    monkeypatch.setattr(requests, "get", lambda *a, **k: mock_resp)

    scraper = JobicyScraper()
    jobs = list(scraper.fetch(["AI"], datetime(2026, 9, 14, tzinfo=timezone.utc)))
    assert len(jobs) >= 1
    j = jobs[0]
    assert j.source == "jobicy"
    assert j.company == "Supabase"
    assert j.title == "Staff AI Systems Engineer"
    assert j.location == "Anywhere"
    assert j.posted_date == "2026-09-15"


def test_nodesk_feed_parse(monkeypatch):
    from unittest.mock import MagicMock
    from src.scrapers.curated_boards import NoDeskScraper
    import requests

    sample_xml = """<?xml version="1.0" encoding="utf-8" standalone="yes"?>
    <rss version="2.0">
      <channel>
        <title>NoDesk Remote Jobs</title>
        <item>
          <title>Senior AI Engineer &amp; Researcher at Anthropic</title>
          <link>https://nodesk.co/remote-jobs/anthropic-senior-ai-engineer/</link>
          <pubDate>Sun, 14 Sep 2026 12:00:00 GMT</pubDate>
          <description>Build alignment and foundational AI models &amp; tools.</description>
        </item>
      </channel>
    </rss>
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = sample_xml
    monkeypatch.setattr(requests, "get", lambda *a, **k: mock_resp)

    scraper = NoDeskScraper()
    jobs = list(scraper.fetch(["AI"], datetime(2026, 9, 10, tzinfo=timezone.utc)))
    assert len(jobs) == 1
    j = jobs[0]
    assert j.source == "nodesk"
    assert j.title == "Senior AI Engineer & Researcher"
    assert j.company == "Anthropic"
    assert j.location == "Worldwide"
    assert j.posted_date == "2026-09-14"
    assert j.url == "https://nodesk.co/remote-jobs/anthropic-senior-ai-engineer/"
    assert "alignment" in j.description


def test_arbeitnow_api_parse(monkeypatch):
    from unittest.mock import MagicMock
    from src.scrapers.curated_boards import ArbeitnowScraper
    import requests

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": [
            {
                "slug": "senior-ai-engineer",
                "company_name": "DeepScale AI",
                "title": "Senior AI &amp; MLOps Engineer",
                "description": "Lead LLM infrastructure and fine-tuning pipelines.",
                "remote": True,
                "url": "https://www.arbeitnow.com/jobs/deepscale-senior-ai-engineer-101",
                "tags": ["python", "ai", "machine-learning"],
                "job_types": ["Full Time"],
                "created_at": 1780000000,
            },
            {
                "slug": "office-manager",
                "company_name": "Local Corp",
                "title": "On-site Office Manager",
                "description": "Onsite office support",
                "remote": False,
                "url": "https://www.arbeitnow.com/jobs/onsite-office-manager",
            },
        ]
    }
    monkeypatch.setattr(requests, "get", lambda *a, **k: mock_resp)

    scraper = ArbeitnowScraper()
    jobs = list(scraper.fetch(["AI"], datetime(2026, 9, 10, tzinfo=timezone.utc)))
    assert len(jobs) == 1
    j = jobs[0]
    assert j.source == "arbeitnow"
    assert j.title == "Senior AI & MLOps Engineer"
    assert j.company == "DeepScale AI"
    assert j.location == "Worldwide"
    assert j.url == "https://www.arbeitnow.com/jobs/deepscale-senior-ai-engineer-101"
    assert "python" in j.tags


def test_python_org_rss_parse(monkeypatch):
    from unittest.mock import MagicMock
    from src.scrapers.curated_boards import PythonOrgScraper
    import requests

    sample_rss = """<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0">
      <channel>
        <title>Python Jobs</title>
        <item>
          <title>Agentic Python Engineer, Evaboot</title>
          <link>https://www.python.org/jobs/8133/</link>
          <pubDate>Sun, 14 Sep 2026 12:00:00 GMT</pubDate>
          <description>Build agentic AI workflows with Python and FastAPI.</description>
        </item>
      </channel>
    </rss>
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = sample_rss
    monkeypatch.setattr(requests, "get", lambda *a, **k: mock_resp)

    scraper = PythonOrgScraper()
    jobs = list(scraper.fetch(["AI"], datetime(2026, 9, 10, tzinfo=timezone.utc)))
    assert len(jobs) == 1
    j = jobs[0]
    assert j.source == "python_org"
    assert j.title == "Agentic Python Engineer"
    assert j.company == "Evaboot"
    assert j.location == "Worldwide"
    assert j.posted_date == "2026-09-14"
    assert "FastAPI" in j.description


# ── Outage honesty tests ─────────────────────────────────────────────────────

def test_curated_scrapers_raise_on_all_endpoints_failing(monkeypatch):
    import pytest
    import requests
    from src.scrapers.curated_boards import (
        WeWorkRemotelyScraper,
        JobicyScraper,
        NoDeskScraper,
        ArbeitnowScraper,
        RemoteokScraper,
    )

    def fail(*a, **kw):
        raise requests.ConnectionError("network down")

    monkeypatch.setattr(requests, "get", fail)
    now = datetime.now(timezone.utc)

    with pytest.raises(requests.ConnectionError):
        list(WeWorkRemotelyScraper().fetch(["AI"], now))

    with pytest.raises(requests.ConnectionError):
        list(JobicyScraper().fetch(["AI"], now))

    with pytest.raises(requests.ConnectionError):
        list(NoDeskScraper().fetch(["AI"], now))

    with pytest.raises(requests.ConnectionError):
        list(ArbeitnowScraper().fetch(["AI"], now))

    with pytest.raises(requests.ConnectionError):
        list(RemoteokScraper().fetch(["AI"], now))


def test_weworkremotely_partial_success_yields_jobs(monkeypatch):
    from unittest.mock import MagicMock
    from src.scrapers.curated_boards import WeWorkRemotelyScraper
    import requests

    sample_rss = """<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0">
      <channel>
        <item>
          <title>Company: AI Engineer</title>
          <link>https://weworkremotely.com/jobs/123</link>
          <region>Worldwide</region>
          <pubDate>Wed, 16 Sep 2026 12:00:00 GMT</pubDate>
          <description>AI dev</description>
        </item>
      </channel>
    </rss>
    """
    call_count = 0

    def mock_get(url, *a, **k):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise requests.ConnectionError("first feed failed")
        resp = MagicMock()
        resp.status_code = 200
        resp.text = sample_rss
        return resp

    monkeypatch.setattr(requests, "get", mock_get)
    jobs = list(WeWorkRemotelyScraper().fetch(["AI"], datetime(2026, 9, 10, tzinfo=timezone.utc)))
    assert len(jobs) == 1
    assert jobs[0].title == "AI Engineer"


def test_working_nomads_api_success(monkeypatch):
    from unittest.mock import MagicMock
    from src.scrapers.working_nomads import WorkingNomadsScraper
    import requests

    sample_api_data = [
        {
            "title": "Senior AI Engineer",
            "company_name": "NomadAI",
            "url": "https://example.com/job/456",
            "location": "Worldwide",
            "date": "2026-09-16",
            "description": "Agentic workflows and Python",
            "tags": "ai,python",
        }
    ]
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = sample_api_data
    monkeypatch.setattr(requests, "get", lambda *a, **k: mock_resp)

    jobs = list(WorkingNomadsScraper().fetch(["AI"], datetime(2026, 9, 10, tzinfo=timezone.utc)))
    assert len(jobs) == 1
    assert jobs[0].title == "Senior AI Engineer"
    assert jobs[0].company == "NomadAI"


def test_working_nomads_api_failure_raises_when_browser_disabled(monkeypatch):
    import pytest
    import requests
    from src.scrapers.working_nomads import WorkingNomadsScraper
    import src.config as cfg

    def fail(*a, **kw):
        raise requests.ConnectionError("api down")

    monkeypatch.setattr(requests, "get", fail)
    monkeypatch.setattr(cfg, "allow_browser_scrapers", lambda: False)

    with pytest.raises(requests.ConnectionError):
        list(WorkingNomadsScraper().fetch(["AI"], datetime.now(timezone.utc)))




