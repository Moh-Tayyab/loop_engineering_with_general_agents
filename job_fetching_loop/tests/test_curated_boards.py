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


def test_wellfound_get_returns_empty_on_network_error(monkeypatch):
    import requests

    def fail(*a, **kw):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(requests, "get", fail)
    assert WellfoundScraper()._get("AI") == []


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

def test_remotive_get_returns_empty_on_network_error(monkeypatch):
    import requests

    def fail(*a, **kw):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(requests, "get", fail)
    assert RemotiveScraper()._get("AI") == []


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


# ── Registry: all 10 curated boards are registered ───────────────────────────

CURATED_SOURCE_NAMES = [
    "remotive", "himalayas", "wellfound", "justremote",
    "feedcoyote", "jobboardsearch",
    "flexjobs", "dynamitejobs", "virtual_vocations", "nodesk",
]

@pytest.mark.parametrize("name", CURATED_SOURCE_NAMES)
def test_curated_source_is_registered(name):
    load_all_scrapers()
    assert name in all_scrapers(), f"{name} not in registry"


# ── Config default-off wiring ────────────────────────────────────────────────

LIVE_CURATED = ("remotive", "himalayas", "wellfound", "justremote")
SCAFFOLDS = (
    "feedcoyote", "jobboardsearch",
    "flexjobs", "dynamitejobs", "virtual_vocations", "nodesk",
)

@pytest.mark.parametrize("name", LIVE_CURATED)
def test_live_curated_sources_default_enabled(name):
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.delenv(f"SOURCE_{name.upper()}", raising=False)
    assert cfg.source_enabled(name)

@pytest.mark.parametrize("name", SCAFFOLDS)
def test_scaffold_sources_default_disabled(name):
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.delenv(f"SOURCE_{name.upper()}", raising=False)
    assert not cfg.source_enabled(name)

@pytest.mark.parametrize("name", SCAFFOLDS)
def test_scaffold_source_optin_via_env(name):
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv(f"SOURCE_{name.upper()}", "1")
    assert cfg.source_enabled(name)

def test_live_source_can_be_disabled_via_env():
    import os
    os.environ["SOURCE_REMOTIVE"] = "0"
    assert not cfg.source_enabled("remotive")
    del os.environ["SOURCE_REMOTIVE"]


# ── Scaffold fetch returns empty, not raise ──────────────────────────────────

def test_scaffold_fetch_yields_nothing():
    load_all_scrapers()
    cls = all_scrapers()["feedcoyote"]
    jobs = list(cls().fetch(["AI"], datetime.now(timezone.utc)))
    assert jobs == []
