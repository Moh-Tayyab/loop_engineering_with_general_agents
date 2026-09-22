"""Beat 105–107 accuracy-gap regression tests (audit A1–C5).

Locks every fix so a future refactor cannot silently reopen the gap.
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.main import is_remotely_workable
from src.models import (
    LOCATION_REMOTE,
    is_description_restricted,
    is_foreign_country_restricted,
    is_hybrid_work,
    is_language_restricted,
    is_title_restricted,
    is_worldwide_remote,
    _is_us_restricted,
)


# ── A3: US cities without a state name ───────────────────────────────────────

def test_us_city_without_state_rejected():
    assert not is_worldwide_remote("Remote - Austin")
    assert not is_worldwide_remote("Remote - Chicago")
    assert not is_worldwide_remote("Remote, Seattle")
    assert not is_worldwide_remote("Chicago - Remote")
    assert is_worldwide_remote("Remote - Dallas, Texas") is False


# ── A4: title country-only restrictions ──────────────────────────────────────

def test_title_country_only_apac_me():
    assert is_title_restricted("AI Engineer - India Only")
    assert is_title_restricted("ML Engineer - Japan Only")
    assert is_title_restricted("LLM Engineer (Singapore Only)")
    assert is_title_restricted("Data Scientist - Australia Only")
    assert not is_title_restricted("AI Engineer - Pakistan Only")
    assert not is_title_restricted("Senior Machine Learning Engineer")


# ── A5: description residency / "X only" ─────────────────────────────────────

def test_description_residency_only_patterns():
    assert is_description_restricted("Applicants in Germany only please.")
    assert is_description_restricted("Open to candidates in India only.")
    assert is_description_restricted("Only candidates based in Japan will be considered.")
    assert is_description_restricted("Candidates in Singapore only.")
    assert is_description_restricted("Must be based in Dubai.")
    # Pakistan residency is in-scope — must NOT be restricted
    assert not is_description_restricted("Open to candidates in Pakistan only.")
    assert not is_description_restricted(
        "We are an all-remote global team building AI tools in Python. Anyone anywhere can apply."
    )


# ── A6: local-language requirements ──────────────────────────────────────────

def test_language_restriction_broadened():
    assert is_language_restricted("Native Arabic speaker required")
    assert is_language_restricted("Arabic is a must")
    assert is_language_restricted("Portuguese required")
    assert is_language_restricted("Turkish required")
    assert is_language_restricted("Thai fluency required")
    assert is_language_restricted("Hindi language required")
    assert is_language_restricted("Professional Portuguese (C1) required")
    assert is_language_restricted("Fluent in Vietnamese")
    assert not is_language_restricted("Build LLMs for a global remote team.")


# ── A7: daily/weekly gate parity on description-level US pins ────────────────

def test_daily_gate_matches_weekly_on_us_description():
    # Weekly (digest) rejects these via _is_us_restricted(desc); daily must too.
    assert not is_remotely_workable(
        LOCATION_REMOTE, "Remote", source="linkedin",
        description="Candidates based in California preferred",
    )
    assert not is_remotely_workable(
        LOCATION_REMOTE, "Remote", source="linkedin",
        description="Must be based in New York City",
    )


def test_digest_and_daily_agree_on_us_description():
    from src.digest import is_valid_digest_job
    from src.models import NormalizedJob, utc_now

    def make(desc: str) -> NormalizedJob:
        return NormalizedJob(
            id="x", title="AI Engineer", title_normalized="ai engineer",
            company="Acme", company_normalized="acme",
            url="https://example.com/jobs/view/1", source="linkedin",
            location="Remote", location_type=LOCATION_REMOTE,
            salary_min=None, salary_max=None, salary_currency=None,
            job_type="full-time", posted_date=None, fetched_at=utc_now(),
            tags=[], description_snippet=desc, cv_match_score=90,
            raw={"description": desc},
        )

    assert not is_valid_digest_job(make("Candidates based in California preferred"))
    assert not is_remotely_workable(
        LOCATION_REMOTE, "Remote", source="linkedin",
        description="Candidates based in California preferred",
    )


# ── A8: US timezone overlap ──────────────────────────────────────────────────

def test_us_timezone_overlap_restricted():
    assert is_description_restricted(
        "Must overlap at least 4 hours with US Eastern (EST) business hours"
    )
    assert is_description_restricted("Overlap with Eastern Time business hours")
    assert is_description_restricted("Must work PST hours")
    assert is_description_restricted("Within 3 hours of EST")
    assert not is_description_restricted(
        "Flexible hours across a global remote team."
    )


# ── A10: weak hiring markers ─────────────────────────────────────────────────

def test_hiring_marker_requires_colon_for_position():
    from src.scrapers.linkedin import _is_hiring_post
    # Bare "position" no longer qualifies (educational commentary)
    assert not _is_hiring_post("The position of power in modern ML systems explained.")
    # Colon form and strong markers still qualify
    assert _is_hiring_post("Position: Senior AI Engineer")
    assert _is_hiring_post("We are hiring an ML engineer")
    assert _is_hiring_post("Role: LLM Engineer — apply now")


# ── B1: hybrid precision (false negatives) ───────────────────────────────────

def test_hybrid_figurative_not_rto():
    # Worldwide role whose body says "hybrid of monorepo and polyrepo" must KEEP
    assert not is_hybrid_work("Our platform uses a hybrid of monorepo and polyrepo.")
    assert not is_hybrid_work("Hybrid Cloud Engineer")
    assert is_worldwide_remote(
        "Worldwide",
        description="Our platform uses a hybrid of monorepo and polyrepo. Fully remote.",
    )
    # Real RTO hybrid still rejected
    assert is_hybrid_work("Hybrid schedule: 3 days in the office")
    assert is_hybrid_work("This role is hybrid — 2 days per week in the office")
    assert is_hybrid_work("Work model: hybrid")
    assert is_hybrid_work("Hybrid work arrangement required")


# ── B2: Israel market mention vs Israel role ─────────────────────────────────

def test_israel_market_mention_keeps_worldwide():
    assert is_worldwide_remote(
        "Worldwide",
        description="We sell to teams in Israel and Europe. Fully remote worldwide role.",
    )
    # Israel residency / Israel-only still rejected
    assert is_description_restricted("Based in Tel Aviv office")
    assert is_description_restricted("Israel only")
    assert is_description_restricted("Must reside in Israel")
    assert not is_worldwide_remote("Tel Aviv, Israel")


# ── B3: worldwide description overrides physical city label ──────────────────

def test_worldwide_desc_overrides_city_location():
    assert is_worldwide_remote(
        "Berlin",
        description="Work from anywhere — worldwide remote team, 100% remote.",
    )
    assert is_worldwide_remote(
        "Germany (Remote)",
        description="Hiring worldwide. Work from anywhere in the world.",
    )


# ── A1/A2: fail-closed location (scraper level) ──────────────────────────────

def test_post_location_fail_closed_empty():
    from src.scrapers.linkedin import _post_location
    assert _post_location("") == ""
    assert _post_location("Just chatting about AI careers, no job.") == ""


def test_feed_worldwide_marker_beats_city():
    from src.scrapers.linkedin import _feed_post_to_raw
    raw = _feed_post_to_raw({
        "text": "We're hiring a remote AI engineer. Worldwide, work from anywhere. "
                "Our HQ is in Berlin but the role is global remote. Apply: jobs@x.com",
        "url": "https://www.linkedin.com/feed/update/urn:li:activity:1/",
    }, "AI")
    assert raw is not None
    assert raw.location in ("Worldwide", "Remote")


# ── A12: digest sees full description beyond snippet ─────────────────────────

def test_digest_restriction_beyond_2000_chars():
    from src.digest import is_valid_digest_job
    from src.models import NormalizedJob, utc_now

    filler = "x" * 2100
    desc = filler + " Must reside in the United States."
    job = NormalizedJob(
        id="y", title="AI Engineer", title_normalized="ai engineer",
        company="Acme", company_normalized="acme",
        url="https://example.com/jobs/view/2", source="linkedin",
        location="Remote", location_type=LOCATION_REMOTE,
        salary_min=None, salary_max=None, salary_currency=None,
        job_type="full-time", posted_date=None, fetched_at=utc_now(),
        tags=[], description_snippet=desc[:2000], cv_match_score=90,
        raw={"description": desc},
    )
    assert not is_valid_digest_job(job)


# ── C4: daily top-5 sorted by CV score ───────────────────────────────────────

def test_daily_top5_sorted_by_cv_score():
    from src.models import NormalizedJob, utc_now
    from src.notifier import TelegramNotifier

    def job(title: str, score: int) -> NormalizedJob:
        return NormalizedJob(
            id=title, title=title, title_normalized=title.lower(),
            company="C", company_normalized="c",
            url="https://example.com/j/1", source="linkedin",
            location="Remote", location_type=LOCATION_REMOTE,
            salary_min=None, salary_max=None, salary_currency=None,
            job_type="full-time", posted_date=None, fetched_at=utc_now(),
            tags=[], description_snippet="", cv_match_score=score,
        )

    n = TelegramNotifier("tok", "chat")
    # scrape order: low score first; formatter must promote high score
    text = n._format_daily([job("Low", 70), job("High", 99), job("Mid", 85)], {"total_this_week": 3})
    assert text.index("High") < text.index("Mid") < text.index("Low")


# ── C3: .env.example matches code defaults ───────────────────────────────────

def test_env_example_timeouts_match_config_defaults():
    from pathlib import Path
    import src.config as cfg

    example = Path(__file__).resolve().parents[1] / ".env.example"
    text = example.read_text(encoding="utf-8")
    guest = cfg.linkedin_guest_timeout_s()
    browser = cfg.linkedin_browser_timeout_s()
    assert f"LINKEDIN_GUEST_TIMEOUT_S={int(guest)}" in text
    assert f"LINKEDIN_BROWSER_TIMEOUT_S={int(browser)}" in text


# ── C5: reject sink helper ───────────────────────────────────────────────────

def test_record_reject_appends_row():
    from src.main import _record_reject

    sink: list[dict] = []
    _record_reject(sink, "linkedin", "AI Engineer", "rule11", "not remote")
    assert sink == [{
        "source": "linkedin",
        "title": "AI Engineer",
        "gate": "rule11",
        "reason": "not remote",
        "ts": sink[0]["ts"],
    }]
    _record_reject(None, "x", "y", "z", "w")  # no-op


# ── B6: pagination params present in guest URL ───────────────────────────────

def test_linkedin_guest_url_includes_start_param(monkeypatch):
    import requests as requests_mod
    from src.scrapers.linkedin import LinkedInScraper

    captured: list[str] = []

    class MockResponse:
        def __init__(self):
            self.text = ""
            self.status_code = 200
            self.url = "https://linkedin.com"

    def mock_get(url, **kwargs):
        captured.append(url)
        return MockResponse()

    monkeypatch.setattr(requests_mod, "get", mock_get)
    list(LinkedInScraper()._fetch_guest_public(
        ["AI"], datetime(2026, 9, 1, tzinfo=timezone.utc),
    ))
    assert captured, "no guest requests captured"
    assert any("start=" in u for u in captured)
