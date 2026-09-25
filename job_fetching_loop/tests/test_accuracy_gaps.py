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
    # Beat 111: Hybrid cloud = private+public infra coupling — drop for PK remote.
    assert is_hybrid_work("Hybrid Cloud Engineer")
    assert is_worldwide_remote(
        "Worldwide",
        description="Our platform uses a hybrid of monorepo and polyrepo. Fully remote.",
    )
    # Real RTO hybrid still rejected
    assert is_hybrid_work("Hybrid schedule: 3 days in the office")
    assert is_hybrid_work("This role is hybrid — 2 days per week in the office")
    assert is_hybrid_work("Work model: hybrid")
    assert is_hybrid_work("Hybrid work arrangement required")
    # Hybrid cloud e2e must not pass as worldwide remote
    assert not is_remotely_workable(
        LOCATION_REMOTE, "Worldwide", source="linkedin",
        description="Build hybrid cloud platforms. Fully remote worldwide.",
        title="Hybrid Cloud Engineer",
    )


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


# ── Beat 108: bare "worldwide" marketing must NOT override foreign location ──

def test_bare_worldwide_marketing_does_not_override_foreign_location():
    # BairesDev boilerplate (live FP Sep 23–24): "impact worldwide" ≠ eligibility.
    marketing = (
        "At BairesDev® we deliver solutions to giants. Our diverse team works "
        "remotely on roles that drive significant impact worldwide."
    )
    assert not is_worldwide_remote("Germany", source="linkedin", description=marketing)
    assert not is_worldwide_remote("Chile", source="linkedin", description=marketing)
    assert not is_worldwide_remote("Greater Rio de Janeiro", source="linkedin", description=marketing)
    assert not is_remotely_workable(
        LOCATION_REMOTE, "Greater Rio de Janeiro", source="linkedin",
        description=marketing, title="Senior AI Engineer - Remote Work",
    )
    # Strong eligibility phrasing still overrides a foreign HQ label (Rule 11).
    strong = "Fully remote — work from anywhere in the world, no location requirements."
    assert is_worldwide_remote("Germany", source="linkedin", description=strong)
    assert is_remotely_workable(
        LOCATION_REMOTE, "Germany", source="linkedin",
        description=strong, title="AI Engineer",
    )


def test_foreign_metro_without_country_token():
    # "Greater Rio de Janeiro" never matches \bbrazil\b — needs the metro list.
    assert is_foreign_country_restricted("Greater Rio de Janeiro")
    assert is_foreign_country_restricted("Rio de Janeiro")
    assert is_foreign_country_restricted("São Paulo")
    assert not is_foreign_country_restricted("Pakistan")
    assert not is_foreign_country_restricted("Singapore")


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


# ── Beat 110: residual Rule-11 leak hunt ─────────────────────────────────────

def test_strong_eligibility_rejects_remote_worldwide_marketing():
    from src.models import _has_strong_worldwide_eligibility
    # Marketing "remote worldwide clients" must NOT unlock a foreign city.
    assert not _has_strong_worldwide_eligibility("remote worldwide clients")
    assert not _has_strong_worldwide_eligibility("remote worldwide")
    # Explicit eligibility phrasing still qualifies.
    assert _has_strong_worldwide_eligibility("worldwide remote team")
    assert _has_strong_worldwide_eligibility("100% remote worldwide team")
    assert _has_strong_worldwide_eligibility("Fully remote worldwide.")
    assert _has_strong_worldwide_eligibility("Work from anywhere in the world")
    assert _has_strong_worldwide_eligibility("remote worldwide opportunity")
    assert _has_strong_worldwide_eligibility("remote, worldwide")
    assert _has_strong_worldwide_eligibility("We hire remotely worldwide")
    assert _has_strong_worldwide_eligibility("This role is remote worldwide")
    assert _has_strong_worldwide_eligibility("The position is remote worldwide")
    # R4: marketing subjects must NOT unlock foreign cities via "is remote worldwide".
    assert not _has_strong_worldwide_eligibility("tooling is remote worldwide")
    assert not _has_strong_worldwide_eligibility(
        "Our platform is remote worldwide for enterprises"
    )


def test_foreign_metros_with_remote_worldwide_marketing_rejected():
    # Physical foreign cities reject bare "remote worldwide" marketing via
    # fallthrough + tightened B3 (no foreign-set entry required — Beat 110).
    for loc in (
        "São Paulo", "London", "Toronto", "Mexico City", "Bogotá",
        "Warsaw", "Chile", "Buenos Aires", "Lima", "Cape Town", "Lagos",
        "Istanbul",
    ):
        assert not is_remotely_workable(
            LOCATION_REMOTE, loc, source="linkedin",
            description="remote worldwide clients", title="AI Engineer",
        ), loc
        assert not is_remotely_workable(
            LOCATION_REMOTE, loc, source="linkedin",
            description="remote worldwide", title="AI Engineer",
        ), loc
    # Strong eligibility still allows an HQ city when the body proves WFA.
    assert is_remotely_workable(
        LOCATION_REMOTE, "São Paulo", source="linkedin",
        description="Work from anywhere — worldwide remote team", title="AI Engineer",
    )
    assert is_remotely_workable(
        LOCATION_REMOTE, "São Paulo", source="linkedin",
        description="This role is remote worldwide", title="AI Engineer",
    )
    # R4 MAJOR: marketing "tooling is remote worldwide" must not unlock São Paulo.
    assert not is_remotely_workable(
        LOCATION_REMOTE, "São Paulo", source="linkedin",
        description="tooling is remote worldwide", title="AI Engineer",
    )
    assert not is_remotely_workable(
        LOCATION_REMOTE, "São Paulo", source="linkedin",
        description="Our platform is remote worldwide for enterprises", title="AI Engineer",
    )
    # Bare physical cities with a normal body stay rejected.
    for loc in ("Cape Town", "Lagos", "Dhaka", "Istanbul"):
        assert not is_remotely_workable(
            LOCATION_REMOTE, loc, source="linkedin",
            description="Great role", title="AI Engineer",
        ), loc


def test_title_hybrid_and_recruiter_rejected():
    assert is_title_restricted("ML Engineer (Hybrid)")
    assert is_title_restricted("ML Engineer - Hybrid")
    assert is_title_restricted("Software Engineer - Hybrid (NYC)")
    assert is_title_restricted("Hybrid ML Engineer")
    assert is_title_restricted("Hybrid - ML Engineer")
    assert is_title_restricted("ML Engineer Hybrid")
    assert is_title_restricted("ML Engineer: Hybrid")
    assert is_title_restricted("Technical Recruiter")
    assert is_title_restricted("Senior Recruiter")
    assert is_title_restricted("Talent Acquisition Specialist")
    assert is_title_restricted("DevOps Recruiter")
    assert is_title_restricted("MLOps Recruiter")
    assert is_title_restricted("SRE Recruiter")
    assert is_title_restricted("Talent Acquisition Analyst")
    assert is_title_restricted("Recruiting Analyst")
    assert is_title_restricted("ML Engineer_Hybrid")
    assert is_title_restricted("DevOps_Recruiter")
    assert is_title_restricted("Talent_Acquisition_Analyst")
    # R4: underscore on-site titles must restrict (t_norm used for onsite gate).
    assert is_title_restricted("AI_Engineer_Onsite")
    assert is_title_restricted("Onsite_AI_Engineer")
    # R4: discipline+Recruiter compounds are talent titles, not eng roles.
    assert is_title_restricted("Engineering Recruiter")
    assert is_title_restricted("Developer Recruiter")
    # Beat 111: Hybrid Cloud dropped (private infra coupling); Search/RAG/AI stack open.
    assert is_title_restricted("Hybrid Cloud Engineer")
    assert is_title_restricted("Staff Hybrid Cloud Architect")
    assert not is_title_restricted("Senior ML Engineer - Hybrid Search")
    assert not is_title_restricted("AI Engineer - Hybrid RAG")
    assert not is_title_restricted("Staff Engineer - Hybrid AI")
    assert not is_title_restricted("ML Engineer - Hybrid Models")
    assert not is_title_restricted("Senior Machine Learning Engineer")
    # HR-tech engineering titles stay open (recruiter word is the product domain).
    assert not is_title_restricted("Software Engineer, Talent Acquisition Platform")
    assert not is_title_restricted("Software Engineer - Recruiting Solutions")
    assert not is_title_restricted("Recruiting Software Engineer")
    assert not is_title_restricted("Engineering Manager - Recruiting Solutions")
    assert not is_title_restricted("Senior Engineering Manager, Talent Acquisition Platform")
    assert not is_title_restricted("Data Engineering Lead - Recruiting Solutions")
    assert not is_title_restricted("Software_Engineer_Recruiting_Solutions")
    # F2: recruiter/talent head + separator + discipline is a talent title.
    assert is_title_restricted("Technical Recruiter - Engineering")
    assert is_title_restricted("Recruiter, Engineering")
    assert is_title_restricted("Senior Recruiter - Software Engineering")
    assert is_title_restricted("Talent Acquisition - Cloud Engineering")
    # F3: underscore country-only forms match t_norm.
    assert is_title_restricted("AI_Engineer_India_Only")
    assert is_title_restricted("ML_Engineer_US_Only")
    assert not is_remotely_workable(
        LOCATION_REMOTE, "Remote", source="linkedin",
        description="Great role", title="Technical Recruiter",
    )


def test_description_residency_preference_and_us_person():
    assert is_description_restricted("UK based candidates only")
    assert is_description_restricted("Must be a US person")
    assert is_description_restricted("US person only")
    assert is_description_restricted("US persons only")
    assert is_description_restricted("U.S. persons only")
    assert is_description_restricted("Must be US persons")
    assert is_description_restricted("export-controlled US persons only")
    # Title-case / uppercase trailing words still restrict (US token is case-sensitive).
    assert is_description_restricted("U.S. Persons only")
    assert is_description_restricted("U.S. persons only")
    assert is_description_restricted("US Persons only")
    assert is_description_restricted("US PERSONS ONLY")
    assert is_description_restricted("US Business Hours EST")
    assert is_description_restricted("Must Work US Business Hours")
    # Zone-trailing pin without US prefix (lowered-text pattern).
    assert is_description_restricted("Must work business hours EST")
    assert is_description_restricted("Flexible within business hours EST")
    assert is_description_restricted("Based in India preferred")
    assert is_description_restricted("Preferably based in Poland")
    assert is_description_restricted("US business hours EST")
    assert is_description_restricted("Must work US business hours")
    # Lowercase "us" is the English pronoun — must NOT restrict.
    assert not is_description_restricted("Give us person-hours estimate")
    assert not is_description_restricted("Show us personnel are friendly")
    assert not is_description_restricted("Contact us business hours")
    # Polarity / open-to-all phrasing must NOT restrict (R3).
    assert not is_description_restricted("US person status is not required")
    assert not is_description_restricted("No US person requirement")
    assert not is_description_restricted("This role does not require US person status")
    assert not is_description_restricted("open to non-US persons")
    assert not is_description_restricted("US and non-US persons welcome")
    assert not is_description_restricted("US business hours not required")
    # R4: negation synonyms.
    assert not is_description_restricted("US person status is not a requirement")
    assert not is_description_restricted("US person status isn't required")
    assert not is_description_restricted("US person requirement: none")
    assert not is_description_restricted("US person is not mandatory")
    assert not is_description_restricted("US person status shall not be required")
    # R4 MAJOR: sentence-scoped polarity — other-sentence negation must not
    # suppress a hard US pin later in the description.
    assert is_description_restricted("No agencies please. US PERSONS ONLY.")
    assert is_description_restricted(
        "We do not require prior experience. US PERSONS ONLY."
    )
    assert is_description_restricted("No degree required. Must work US business hours.")
    assert is_description_restricted("Free of charge training. US persons only.")
    assert is_description_restricted(
        "This role does not require a degree. US persons only."
    )
    assert is_description_restricted(
        "US person status is not required, but US PERSONS ONLY may apply"
    )
    # F1: same-clause open-neg must not suppress a different hard pin.
    assert is_description_restricted(
        "US person status is not required; candidates must work US business hours"
    )
    assert is_description_restricted(
        "US person status is not required, and must work US business hours"
    )
    assert is_description_restricted(
        "US person status isn't required; role requires US business hours"
    )
    # Pure open-neg (no second hard pin) stays open — including "does not require".
    assert not is_description_restricted("This role does not require US person status")
    assert not is_description_restricted("US person status is not required")
    # F1 residual (Checker R1 + R2): bare "only" after strip must not fire on
    # "not only" / "the only thing"; non-US persons strip must not leave a
    # bare "persons only" pin. Only a US-token persons-ONLY pin counts.
    assert not is_description_restricted(
        "US person status is not required; not only US persons may apply"
    )
    assert not is_description_restricted(
        "US person status is the only thing not required"
    )
    assert not is_description_restricted(
        "Open to non-US persons only for global roles"
    )
    assert not is_description_restricted("open to non US persons only")
    # Pakistan / global remote body stays open.
    assert not is_description_restricted("Open to candidates in Pakistan only.")
    assert not is_description_restricted(
        "We are an all-remote global team building AI tools."
    )
    assert not is_remotely_workable(
        LOCATION_REMOTE, "Remote", source="linkedin",
        description="UK based candidates only", title="AI Engineer",
    )
    assert not is_remotely_workable(
        LOCATION_REMOTE, "Remote", source="linkedin",
        description="US business hours EST", title="AI Engineer",
    )
    assert not is_remotely_workable(
        LOCATION_REMOTE, "Remote", source="linkedin",
        description="US PERSONS ONLY", title="AI Engineer",
    )


def test_usa_person_open_negation_not_us_restricted():
    # R4 residual: bare U.S.A. token in _is_us_restricted must honor polarity
    # so daily (_is_us_restricted) and digest do not re-reject an open description.
    open_desc = "U.S.A. person status is not required"
    assert not _is_us_restricted(open_desc)
    assert not is_description_restricted(open_desc)
    assert is_remotely_workable(
        LOCATION_REMOTE, "Remote", source="linkedin",
        description=open_desc, title="AI Engineer",
    )
    # Hard / geo forms still restricted via the same token.
    assert _is_us_restricted("U.S.A. persons only")
    assert _is_us_restricted("Must reside in the United States")
    assert _is_us_restricted("Remote (U.S.A. only)")
    assert not is_remotely_workable(
        LOCATION_REMOTE, "Remote", source="linkedin",
        description="U.S.A. persons only", title="AI Engineer",
    )


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


# ── PR #13 finding 1: desc-level US-city over-match must not drop Worldwide ──

def test_pr13_worldwide_desc_us_office_mentions_stay_open():
    # Reviewer repros: casual US-office prose on a Worldwide role must pass.
    assert not _is_us_restricted("Remote-first, hubs in Austin and Berlin")
    assert not _is_us_restricted("Remote engineers welcome; offices in Seattle and London")
    assert not _is_us_restricted("Remote role; we also have an office in Boston")
    # Residual MEDIUM (re-review): hyphen/period forms must not walk cities
    # inside the greedy _US_RESTRICTED_RE group either.
    assert not _is_us_restricted("Remote-first team with offices in Seattle and London")
    assert not _is_us_restricted("Remote-first hubs in Austin and Berlin")
    assert not _is_us_restricted("We are remote-first. Offices in New York, London, Singapore.")
    # Same class: state name / abbr in casual office prose must stay open.
    assert not _is_us_restricted("hubs in Austin, TX and Berlin")
    assert not _is_us_restricted("offices in Seattle, WA and London")
    assert is_remotely_workable(
        LOCATION_REMOTE, "Worldwide", source="linkedin",
        description="Remote-first, hubs in Austin and Berlin", title="AI Engineer",
    )
    assert is_remotely_workable(
        LOCATION_REMOTE, "Worldwide", source="linkedin",
        description="Remote engineers welcome; offices in Seattle and London",
        title="AI Engineer",
    )
    assert is_remotely_workable(
        LOCATION_REMOTE, "Worldwide", source="linkedin",
        description="Remote-first team with offices in Seattle and London",
        title="AI Engineer",
    )
    assert is_remotely_workable(
        LOCATION_REMOTE, "Worldwide", source="linkedin",
        description="Remote-first hubs in Austin and Berlin", title="AI Engineer",
    )
    assert is_remotely_workable(
        LOCATION_REMOTE, "Worldwide", source="linkedin",
        description="We are remote-first. Offices in New York, London, Singapore.",
        title="AI Engineer",
    )


def test_pr13_short_mixed_locality_clauses_stay_open():
    # PR #13 human-gate fix (a): short ≤4-word clauses mixing a US locality
    # with a FOREIGN one are multi-locality prose, not US residency pins.
    # Beat 120: comma enumerations + APAC/ME siblings are the same class.
    short_mixed = [
        "Remote - Austin and Berlin",
        "Remote (New York, London)",
        "Remote - Seattle & London",
        "Remote - Texas and Germany",
        "Remote - California or Ireland",
        "Remote - France vs Texas",
        "Remote - UK or California",
        # Beat 120 MEDIUM-1a: comma must join the clause, not cut it.
        "Remote - Austin, Berlin",
        "Remote - Seattle, London",
        # Beat 120 MEDIUM-1b: in-scope APAC/ME localities are non-US too.
        "Remote - Austin and Singapore",
        "Remote - Seattle and Dubai",
    ]
    for clause in short_mixed:
        assert not _is_us_restricted(clause), clause
        assert is_remotely_workable(
            LOCATION_REMOTE, "Worldwide", source="linkedin",
            description=clause, title="AI Engineer",
        ), clause


def test_pr13_mixed_first_pin_second_still_restricts():
    """Beat 120 MEDIUM-2: a skipped mixed clause must not mask a LATER US-only
    pin — fail-closed Rule 11 demands every match is walked (finditer)."""
    # mixed clause first, hard pin second
    assert _is_us_restricted("Remote - Austin and Berlin; Remote - Dallas")
    # greedy-group trap: without the tempered stop the first match would
    # swallow "Remote" and the Dallas pin would never be examined.
    assert _is_us_restricted(
        "Remote-first hubs in Austin and Berlin. This role is Remote - Dallas."
    )
    # pin only in a later paren/hyphen clause after mixed prose
    assert _is_us_restricted("Remote (Austin, Berlin). Remote - Houston")
    assert not is_remotely_workable(
        LOCATION_REMOTE, "Worldwide", source="linkedin",
        description="Remote-first hubs in Austin and Berlin. This role is Remote - Dallas.",
        title="AI Engineer",
    )


def test_pr13_target_markers_do_not_bypass_hard_pins():
    """Beat 122 MEDIUM-A: worldwide/APAC markers must not short-circuit hard
    US residency pins — Rule 11 zero tolerance, daily AND weekly gates."""
    from src.digest import is_valid_digest_job
    from src.models import NormalizedJob, utc_now

    def make(desc: str) -> NormalizedJob:
        return NormalizedJob(
            id="x", title="AI Engineer", title_normalized="ai engineer",
            company="Acme", company_normalized="acme",
            url="https://example.com/jobs/view/1", source="linkedin",
            location="Worldwide", location_type=LOCATION_REMOTE,
            salary_min=None, salary_max=None, salary_currency=None,
            job_type="full-time", posted_date=None, fetched_at=utc_now(),
            tags=[], description_snippet=desc, cv_match_score=90,
            raw={"description": desc},
        )

    pin_descs = [
        "Worldwide role; must be based in Austin",
        "APAC team; Remote - Dallas only",
        "APAC role. Candidates in NY only.",
        "Worldwide role. Remote - Dallas (APAC)",
    ]
    for desc in pin_descs:
        assert _is_us_restricted(desc), desc
        assert not is_remotely_workable(
            LOCATION_REMOTE, "Worldwide", source="linkedin",
            description=desc, title="AI Engineer",
        ), desc
        assert not is_valid_digest_job(make(desc)), desc
    # Recall: marker'd casual multi-region prose still stays open.
    assert not _is_us_restricted("Europe, LATAM, APAC, the U.S., Canada")
    assert is_remotely_workable(
        LOCATION_REMOTE, "Worldwide", source="linkedin",
        description="Worldwide; hubs in Austin and Berlin", title="AI Engineer",
    )


def test_pr13_description_foreign_geo_pins_restrict():
    """Beat 122 MEDIUM-B: description-level bare foreign geography pins the
    country-alt forms missed ("Remote - Berlin only", "Germany only")."""
    # repros
    assert is_description_restricted("Remote - Berlin only")
    assert is_description_restricted("Germany only")
    assert is_description_restricted("Remote - Warsaw only")
    # a worldwide marker in the same description must not suppress the pin
    assert is_description_restricted("Worldwide role. Remote - Berlin only")
    # foreign-only enumerations restrict (both localities foreign)
    assert is_description_restricted("Remote - Berlin, Germany")
    assert is_description_restricted("Remote - Warsaw and Berlin")
    # ...but mixed US+foreign clauses stay open (recall-first policy)
    assert not is_description_restricted("Remote - France vs Texas")
    assert not is_description_restricted("Remote - UK or California")
    assert not is_description_restricted("Remote - Texas and Germany")
    assert not is_description_restricted("Remote - Austin, Berlin")
    assert not is_description_restricted("Remote - Austin and Singapore")
    # daily gate drops the pin form end-to-end
    assert not is_remotely_workable(
        LOCATION_REMOTE, "Worldwide", source="linkedin",
        description="Remote - Berlin only", title="AI Engineer",
    )


def test_pr13_mixed_locality_tradeoffs_pinned():
    """PR #13 human-gate (b): documented, tested sacrifice + kept precision.

    1. Recall-first tradeoff (accepted leak): a mixed enumeration is treated
       as multi-locality even when the poster may have meant a US-only pin
       ("Remote - Austin or Berlin" could be offering Austin as one option).
       We accept that leak so Worldwide roles naming a US office survive.
    2. Kept precision: all-US enumerations still restrict.
    3. US-person / USA tokens are unaffected by the foreign-locality skip.
    """
    # (1) accepted leak — pinned so a future change is a conscious decision
    assert not _is_us_restricted("Remote - Austin or Berlin")
    assert not _is_us_restricted("Remote (Boston, Dublin)")
    # (2) all-US enumeration still restricts
    assert _is_us_restricted("Remote - Austin and Dallas")
    assert _is_us_restricted("Remote (New York, Seattle)")
    # (3) USA/US-person tokens stay unconditional
    assert _is_us_restricted("Remote - US or Germany only")
    assert _is_us_restricted("U.S.A. persons only")


def test_pr13_residency_pins_still_restrict_us_cities():
    # Residency-pin constructions remain restricted (no recall leak).
    assert _is_us_restricted("Remote - Austin")            # _US_RESTRICTED_RE
    assert _is_us_restricted("Chicago - Remote")
    assert _is_us_restricted("Remote in Austin")
    assert _is_us_restricted("Must be based in Austin")
    assert _is_us_restricted("Austin only")
    assert _is_us_restricted("Austin-based team")
    assert _is_us_restricted("Candidates based in New York City")
    # Short qualifier groups still geo-walk (≤4 words).
    assert _is_us_restricted("Remote - Austin, TX")
    assert _is_us_restricted("Remote (New York)")
    assert _is_us_restricted("Remote - California")
    # State / abbr pins still restrict (full-text residency pins).
    assert _is_us_restricted("Must reside in California")
    assert _is_us_restricted("Candidates based in Texas preferred")
    assert _is_us_restricted("Must be in CA")
    assert _is_us_restricted("Candidates in NY only")
    assert not is_remotely_workable(
        LOCATION_REMOTE, "Remote", source="linkedin",
        description="Must be based in Austin", title="AI Engineer",
    )


def test_pr13_link_health_timeout_default_is_budget_sized():
    import inspect
    from src.models import check_link_health
    sig = inspect.signature(check_link_health)
    assert sig.parameters["timeout_s"].default <= 1.5
