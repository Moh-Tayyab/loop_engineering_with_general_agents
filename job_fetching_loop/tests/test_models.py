"""Tests for data models: normalization, salary parsing, location classification."""
from __future__ import annotations

from src.models import (
    classify_job_type,
    classify_location,
    is_expired_job,
    is_worldwide_remote,
    keyword_matches,
    parse_salary,
)


# ── salary parsing ──
def test_parse_salary_full_range():
    mn, mx, cur = parse_salary("$180k-$220k")
    assert mn == 180_000
    assert mx == 220_000
    assert cur == "$"


def test_parse_salary_range_omitted_first_suffix():
    """Ranges where the first value omits the multiplier (e.g. $150-200K)
    must propagate the multiplier to min, not parse min as $150."""
    mn, mx, cur = parse_salary("$150-200K")
    assert mn == 150_000
    assert mx == 200_000
    assert cur == "$"

    mn2, mx2, cur2 = parse_salary("150 - 200k")
    assert mn2 == 150_000
    assert mx2 == 200_000
    assert cur2 is None

    mn3, mx3, cur3 = parse_salary("₹25-30L")
    assert mn3 == 2_500_000
    assert mx3 == 3_000_000
    assert cur3 == "₹"

    mn4, mx4, cur4 = parse_salary("$1 - 1.5M")
    assert mn4 == 1_000_000
    assert mx4 == 1_500_000
    assert cur4 == "$"


def test_parse_salary_range_omitted_second_suffix():
    """Ranges where the second value omits the multiplier (e.g. $150K-200)
    must propagate the multiplier to max, not parse max as 200."""
    mn, mx, cur = parse_salary("$150K - 200")
    assert mn == 150_000
    assert mx == 200_000
    assert cur == "$"

    mn2, mx2, cur2 = parse_salary("₹25L - 30")
    assert mn2 == 2_500_000
    assert mx2 == 3_000_000
    assert cur2 == "₹"


def test_parse_salary_annual_and_hourly_indicators():
    """Explicit annual indicators should scale shorthand numbers, while
    hourly indicators preserve raw dollar values."""
    mn, mx, cur = parse_salary("$150 - $200 / year")
    assert mn == 150_000
    assert mx == 200_000
    assert cur == "$"

    mn2, mx2, cur2 = parse_salary("$120 / yr")
    assert mn2 == 120_000
    assert mx2 is None
    assert cur2 == "$"

    mn3, mx3, cur3 = parse_salary("$100 - $150 / hr")
    assert mn3 == 100
    assert mx3 == 150
    assert cur3 == "$"


def test_parse_salary_single():
    mn, mx, cur = parse_salary("£120k")
    assert mn == 120_000
    assert mx is None
    assert cur == "£"


def test_parse_salary_full_value():
    mn, mx, _ = parse_salary("150k - 200k")
    assert mn == 150_000
    assert mx == 200_000


def test_parse_salary_none():
    assert parse_salary(None) == (None, None, None)
    assert parse_salary("") == (None, None, None)


def test_parse_salary_garbage():
    mn, mx, cur = parse_salary("competitive")
    assert mn is None and mx is None


def test_parse_salary_comma_separated():
    mn, mx, cur = parse_salary("$150,000 - $200,000")
    assert mn == 150_000
    assert mx == 200_000
    assert cur == "$"

    mn2, mx2, cur2 = parse_salary("$120,000")
    assert mn2 == 120_000
    assert mx2 is None
    assert cur2 == "$"

    mn3, mx3, cur3 = parse_salary("£85,000+")
    assert mn3 == 85_000
    assert mx3 is None
    assert cur3 == "£"


# ── lakh / INR conventions (beat 65 audit) ───────────────────────────────────
def test_parse_salary_lakh():
    mn, mx, cur = parse_salary("₹25L-30L")
    assert mn == 2_500_000
    assert mx == 3_000_000
    assert cur == "₹"


def test_parse_salary_lakh_word():
    mn, mx, _ = parse_salary("3.5 LPA")
    assert mn == 350_000
    assert mx is None


def test_parse_salary_na_has_no_madeup_currency():
    """'N/A' / prose without digits must not invent a currency like 'N'."""
    assert parse_salary("N/A") == (None, None, None)
    assert parse_salary("Not specified") == (None, None, None)
    assert parse_salary("competitive") == (None, None, None)


def test_parse_posted_datetime():
    from src.models import parse_posted_datetime

    dt = parse_posted_datetime("2026-09-17T04:12:00Z")
    assert dt is not None
    assert dt.year == 2026 and dt.month == 9 and dt.day == 17 and dt.hour == 4
    assert dt.tzinfo is not None

    dt2 = parse_posted_datetime("2026-09-17 08:30:00")
    assert dt2 is not None
    assert dt2.hour == 8 and dt2.minute == 30

    # Date-only should return None so caller uses calendar date fallback
    assert parse_posted_datetime("2026-09-17") is None
    assert parse_posted_datetime("yesterday") is None



# ── location classification ──────────────────────────────────────────────────

def test_classify_remote():
    assert classify_location("Remote") == "remote"
    assert classify_location("Work from anywhere") == "remote"
    assert classify_location("Anywhere in the world") == "remote"
    assert classify_location("Worldwide") == "remote"
    assert classify_location("Work from Home") == "remote"
    assert classify_location("WFH") == "remote"


def test_classify_remote_city_name_is_not_remote():
    """'Remote, Oregon' / 'Remote, OR' are US city names, not remote jobs."""
    assert classify_location("Remote, OR") == "onsite"
    assert classify_location("Remote, Oregon") == "onsite"
    assert classify_location("Remote, CA") == "onsite"


def test_classify_remote_in_city_is_not_remote():
    """'Remote in Brooklyn, NY' is city-restricted, not worldwide-remote."""
    assert classify_location("Remote in Brooklyn, NY") == "onsite"
    assert classify_location("Remote in Windsor, CO 80550") == "onsite"


def test_classify_remote_with_parentheses():
    assert classify_location("Remote (US)") == "remote"
    assert classify_location("Remote (Worldwide)") == "remote"


def test_classify_hybrid():
    assert classify_location("Hybrid - New York") == "hybrid"


def test_classify_onsite():
    assert classify_location("Menlo Park, CA") == "onsite"
    assert classify_location("On-site") == "onsite"
    assert classify_location("London") == "onsite"


def test_classify_none():
    assert classify_location(None) == "unknown"


# ── worldwide remote detection ───────────────────────────────────────────────

def test_is_worldwide_remote_bare():
    assert is_worldwide_remote("Remote")
    assert is_worldwide_remote("REMOTE")


def test_is_worldwide_remote_worldwide():
    assert is_worldwide_remote("Worldwide")
    assert is_worldwide_remote("Work from anywhere")
    assert is_worldwide_remote("Anywhere in the world")
    assert is_worldwide_remote("Global")


def test_is_worldwide_remote_apac_and_multi_region():
    """Working Nomads & remote-native boards using 'Global' and multi-region APAC strings."""
    assert is_worldwide_remote("Europe, North America, Latin America, APAC")
    assert is_worldwide_remote("Europe, LATAM, APAC, the U.S., Canada")
    assert is_worldwide_remote("APAC")
    assert is_worldwide_remote("Asia Pacific")
    assert is_worldwide_remote("Remote (Worldwide) - Working East Coast Hours")
    # Region-restricted that does not include Pakistan
    assert not is_worldwide_remote("South Korea")
    assert not is_worldwide_remote("France")
    assert not is_worldwide_remote("Anywhere in India")
    assert not is_worldwide_remote("USA only")
    assert not is_worldwide_remote("Anywhere in the US")
    assert not is_worldwide_remote("Anywhere in the USA")
    assert not is_worldwide_remote("Remote - US")
    assert not is_worldwide_remote("Remote - USA")
    assert not is_worldwide_remote("Remote - United States")
    assert not is_worldwide_remote("US - Remote")
    assert not is_worldwide_remote("USA - Remote")
    assert not is_worldwide_remote("United States - Remote")
    assert not is_worldwide_remote("Remote / US")


def test_classify_location_global_and_apac():
    from src.models import classify_location, LOCATION_REMOTE
    assert classify_location("Global") == LOCATION_REMOTE
    assert classify_location("Europe, North America, Latin America, APAC") == LOCATION_REMOTE


def test_is_worldwide_remote_rejects_city_restricted():
    """'Remote in Brooklyn, NY' should NOT be treated as worldwide."""
    assert not is_worldwide_remote("Remote in Brooklyn, NY")
    assert not is_worldwide_remote("Remote in Windsor, CO 80550")


def test_is_worldwide_remote_rejects_city_names():
    """'Remote, Oregon' is a city name (Coos County, OR), not remote."""
    assert not is_worldwide_remote("Remote, OR")
    assert not is_worldwide_remote("Remote, Oregon")
    assert not is_worldwide_remote("Remote OR")
    assert not is_worldwide_remote("Remote Oregon")


def test_is_worldwide_remote_rejects_pakistan_onsite_and_hybrid():
    """On-site and hybrid office roles in Pakistan must be strictly rejected."""
    assert not is_worldwide_remote("Lahore, Punjab, Pakistan")
    assert not is_worldwide_remote("Karachi Division, Sindh, Pakistan")
    assert not is_worldwide_remote("Islamabad, Pakistan")
    assert not is_worldwide_remote("Karachi, Pakistan", description="Work in our Clifton office")
    assert not is_worldwide_remote("Karachi (Hybrid), Pakistan")
    assert not is_worldwide_remote("Lahore, Pakistan", description="Hybrid working model: 3 days in office, 2 days home")
    # But genuine remote in Pakistan is accepted:
    assert is_worldwide_remote("Pakistan (Remote)")
    assert is_worldwide_remote("Lahore (Remote), Pakistan")
    assert is_worldwide_remote("Lahore, Pakistan", description="This position is 100% remote work from home.")


def test_is_worldwide_remote_rejects_unverified_foreign_cities():
    """Cities without remote markers must never be assumed remote."""
    assert not is_worldwide_remote("Ümraniye, Istanbul, Türkiye")
    assert not is_worldwide_remote("Toronto, Ontario, Canada")
    assert not is_worldwide_remote("San Jose, CA")
    assert not is_worldwide_remote("London, England, United Kingdom")
    assert not is_worldwide_remote("Berlin, Germany")
    assert not is_worldwide_remote("Paris, France")
    assert not is_worldwide_remote("Tokyo, Japan")
    assert not is_worldwide_remote("Bangalore, India")
    assert not is_worldwide_remote("Dubai, UAE")
    assert not is_worldwide_remote("Austin, TX")
    assert not is_worldwide_remote("Dublin, OH")
    assert not is_worldwide_remote("Remote, Coos County, OR")
    assert not is_worldwide_remote("Remote OR 97458")


def test_is_worldwide_remote_allowed_tags():
    """Explicitly verify the allowed location tags: worldwide, anywhere, work from home, WFH, APAC, Pakistan remote."""
    assert is_worldwide_remote("Worldwide")
    assert is_worldwide_remote("Work from anywhere")
    assert is_worldwide_remote("Anywhere in the world")
    assert is_worldwide_remote("Anywhere")
    assert is_worldwide_remote("Work from home")
    assert is_worldwide_remote("WFH")
    assert is_worldwide_remote("APAC")
    assert is_worldwide_remote("Asia Pacific")
    assert is_worldwide_remote("Pakistan (Remote)")
    assert is_worldwide_remote("Remote in Pakistan")
    assert is_worldwide_remote("Global")
    assert is_worldwide_remote("Global Remote")


def test_is_worldwide_remote_us_domestic_boards_reject_bare_remote():
    """Indeed/Glassdoor bare 'Remote' is domestic US remote (e.g. GoodLeap) -> reject for Pakistan."""
    assert not is_worldwide_remote("Remote", source="indeed")
    assert not is_worldwide_remote("Remote", source="glassdoor")
    assert not is_worldwide_remote("Remote", source="indeed", description="Must reside in US.")


def test_is_worldwide_remote_us_domestic_boards_accept_worldwide_indicators():
    """Indeed/Glassdoor jobs qualifying explicitly for worldwide/global remote -> accept."""
    assert is_worldwide_remote("Remote (Worldwide)", source="indeed")
    assert is_worldwide_remote("Remote - Worldwide", source="indeed")
    assert is_worldwide_remote("Remote (Pakistan)", source="indeed")
    assert is_worldwide_remote("Remote", source="indeed", description="Role is open to candidates anywhere in the world.")
    assert is_worldwide_remote("Remote", source="glassdoor", description="Work from anywhere worldwide.")


def test_is_worldwide_remote_remote_native_boards_accept_bare_remote():
    """Remote-native boards (Remotive, Himalayas, Wellfound, JustRemote) bare 'Remote' is global."""
    assert is_worldwide_remote("Remote", source="himalayas")
    assert is_worldwide_remote("Remote", source="remotive")
    assert is_worldwide_remote("Remote", source="wellfound")
    assert is_worldwide_remote("Remote", source="justremote")


def test_is_remotely_workable_source_aware():
    from src.main import is_remotely_workable
    # Indeed bare Remote (e.g. GoodLeap) -> rejected
    assert not is_remotely_workable("remote", "Remote", source="indeed")
    # Himalayas bare Remote -> accepted
    assert is_remotely_workable("remote", "Remote", source="himalayas")
    # Indeed with worldwide -> accepted
    assert is_remotely_workable("remote", "Remote (Worldwide)", source="indeed")
    # Remote, Oregon -> rejected regardless
    assert not is_remotely_workable("remote", "Remote, OR", source="indeed")
    assert not is_remotely_workable("remote", "Remote, OR", source="himalayas")


def test_goodleap_indeed_bare_remote_rejected():
    """Verify the real-world GoodLeap Indeed job (bare 'Remote') is rejected for Pakistan candidates."""
    from src.main import is_remotely_workable
    assert not is_remotely_workable(
        location_type="remote",
        location="Remote",
        source="indeed",
        description="",
    )
    assert not is_worldwide_remote(
        location="Remote",
        source="indeed",
        description="",
    )


def test_is_worldwide_remote_rejects_region_restricted():
    """'Remote (US Only)' is region-restricted."""
    assert not is_worldwide_remote("Remote (US Only)")
    assert not is_worldwide_remote("Remote (EMEA)")


def test_is_worldwide_remote_rejects_none():
    assert not is_worldwide_remote(None)
    assert not is_worldwide_remote("")


# ── expired job detection ────────────────────────────────────────────────────

def test_is_expired_job_title_closed():
    from src.models import RawJob
    job = RawJob(source="t", title="AI Engineer (Closed)", company="X", url="u")
    assert is_expired_job(job)


def test_is_expired_job_title_expired():
    from src.models import RawJob
    job = RawJob(source="t", title="ML Engineer - Expired", company="X", url="u")
    assert is_expired_job(job)


def test_is_expired_job_title_filled():
    from src.models import RawJob
    job = RawJob(source="t", title="This Position Has Been Filled", company="X", url="u")
    assert is_expired_job(job)


def test_is_expired_job_desc_expired():
    from src.models import RawJob
    job = RawJob(source="t", title="AI Engineer", company="X", url="u",
                 description="This position has been filled by another candidate.")
    assert is_expired_job(job)


def test_is_not_expired_normal_job():
    from src.models import RawJob
    job = RawJob(source="t", title="Senior ML Engineer", company="X", url="u",
                 description="Build ML systems for our platform.")
    assert not is_expired_job(job)


def test_is_not_expired_keyword_partial_match():
    """'closed' inside 'Unclosed Issues' must NOT trigger expiry."""
    from src.models import RawJob
    job = RawJob(source="t", title="Software Engineer - Unclosed Issues Tracker", company="X", url="u")
    assert not is_expired_job(job)


# ── job type classification ──
def test_classify_job_type():
    assert classify_job_type("Full-time") == "full-time"
    assert classify_job_type("Contract") == "contract"
    assert classify_job_type("Freelance") == "contract"
    assert classify_job_type("Part-time") == "part-time"
    assert classify_job_type(None) == "unknown"


# ── keyword matching ──
def test_keyword_matches_title():
    from src.models import RawJob
    job = RawJob(source="t", title="Senior Machine Learning Engineer", company="X", url="u")
    assert keyword_matches(job, ["machine learning"])


def test_keyword_matches_description():
    from src.models import RawJob
    job = RawJob(source="t", title="Software Engineer", company="X", url="u",
                 description="We build LLM systems")
    assert keyword_matches(job, ["llm"])


def test_keyword_no_match():
    from src.models import RawJob
    job = RawJob(source="t", title="Account Manager", company="X", url="u",
                 description="Sales role")
    assert not keyword_matches(job, ["machine learning"])


def test_keyword_no_substring_false_positive():
    """'ai' must not match inside 'training' (word-boundary only)."""
    from src.models import RawJob
    job = RawJob(source="t", title="Training & Development Coordinator", company="X", url="u")
    assert not keyword_matches(job, ["AI"])
    job2 = RawJob(source="t", title="AI Engineer", company="X", url="u")
    assert keyword_matches(job2, ["AI"])


def test_keyword_phrase_match():
    from src.models import RawJob
    job = RawJob(source="t", title="Novel ML", company="X", url="u",
                 description="Senior Machine Learning Engineer role")
    assert keyword_matches(job, ["machine learning"])


# ── AI-domain gate (two-tier keywords) ──
def test_ai_gate_accepts_ai_ml_job():
    from src.models import RawJob, ai_keyword_matches
    ai = ["AI", "Machine Learning", "LLM", "NLP", "Data Science", "Computer Vision", "AI FDE"]
    roles = ["Engineer", "Developer"]
    job = RawJob(source="t", title="Machine Learning Engineer", company="X", url="u")
    assert ai_keyword_matches(job, ai, roles)


def test_ai_gate_rejects_plain_role_job():
    """Java Developer without any AI term must be rejected — roles alone never qualify."""
    from src.models import RawJob, ai_keyword_matches
    ai = ["AI", "Machine Learning", "LLM", "NLP", "Data Science", "Computer Vision", "AI FDE"]
    roles = ["Engineer", "Developer"]
    job = RawJob(source="t", title="Senior Java Developer", company="X", url="u",
                 description="Spring Boot microservices")
    assert not ai_keyword_matches(job, ai, roles)


def test_ai_gate_matches_ai_fde_title():
    from src.models import RawJob, ai_keyword_matches
    ai = ["AI", "Machine Learning", "LLM"]
    job = RawJob(source="t", title="AI FDE", company="X", url="u")
    assert ai_keyword_matches(job, ai, ["Engineer", "Developer"])


# ── remote-only gate ─────────────────────────────────────────────────────────

def test_remote_only_drops_onsite_hybrid_unknown():
    from src.main import is_remotely_workable
    assert not is_remotely_workable("onsite")
    assert not is_remotely_workable("hybrid")
    assert not is_remotely_workable("unknown")


def test_remote_only_keeps_remote():
    from src.main import is_remotely_workable
    assert is_remotely_workable("remote")


def test_remote_only_uses_location_text():
    """When location text is available, is_worldwide_remote takes precedence."""
    from src.main import is_remotely_workable
    assert is_remotely_workable("remote", "Remote")
    assert is_remotely_workable("remote", "Worldwide")
    assert not is_remotely_workable("remote", "Remote in Brooklyn, NY")
    assert not is_remotely_workable("remote", "Remote, Oregon")


# ── posted_date parsing ───────────────────────────────────────────────────────

def test_parse_posted_date_iso():
    from datetime import date
    from src.models import parse_posted_date
    assert parse_posted_date("2026-09-11") == date(2026, 9, 11)


def test_parse_posted_date_iso_datetime_truncates():
    from datetime import date
    from src.models import parse_posted_date
    assert parse_posted_date("2026-09-11T10:30:00+00:00") == date(2026, 9, 11)


def test_parse_posted_date_relative_phrases():
    from datetime import timedelta
    from src.models import parse_posted_date, utc_now
    today = utc_now().date()
    assert parse_posted_date("Posted Today", today=today) == today
    assert parse_posted_date("Today", today=today) == today
    assert parse_posted_date("Yesterday", today=today) == today - timedelta(days=1)
    assert parse_posted_date("Posted 3 days ago", today=today) == today - timedelta(days=3)
    assert parse_posted_date("30+ days ago", today=today) == today - timedelta(days=30)
    assert parse_posted_date("6d", today=today) == today - timedelta(days=6)
    assert parse_posted_date("6 hours ago", today=today) == today
    assert parse_posted_date("2 weeks ago", today=today) == today - timedelta(days=14)


def test_parse_posted_date_unparseable_returns_none():
    from src.models import parse_posted_date
    assert parse_posted_date(None) is None
    assert parse_posted_date("") is None
    assert parse_posted_date("   ") is None
    assert parse_posted_date("garbage") is None
