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


def test_is_worldwide_remote_apac_regions_with_foreign_blocked_countries():
    """Broad APAC-region designators remain in-scope, but roles hard-blocked
    to a developed foreign market (Japan/Korea/Australia) are domestic-only
    even when they carry a Remote label — foreign country law outranks APAC."""
    assert is_worldwide_remote("Remote (Singapore)")
    assert not is_worldwide_remote("Remote (India)")
    assert is_worldwide_remote("Remote (India) - Worldwide Contractor")
    assert is_worldwide_remote("APAC (Remote)")
    assert is_worldwide_remote("Asia Pacific (Remote)")
    assert not is_worldwide_remote("Remote (Japan)")
    assert not is_worldwide_remote("Remote (South Korea)")
    assert not is_worldwide_remote("Remote (Australia)")
    """Working Nomads & remote-native boards using 'Global' and multi-region APAC strings."""
    # Region-scoped lists that EXCLUDE Pakistan (Europe/LatAm/US-specific) are
    # domestic restrictions for a Pakistan-based candidate — reject (Rule 11).
    assert not is_worldwide_remote("Europe, North America, Latin America, APAC")
    assert not is_worldwide_remote("Europe, LATAM, APAC, the U.S., Canada")
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
    assert not is_worldwide_remote("Islamabad, Islāmābād, Pakistan")
    assert not is_worldwide_remote("Pakistan")
    # Generic mentions of remote in description must NOT override physical city or bare country
    assert not is_worldwide_remote("Islamabad, Islāmābād, Pakistan", description="This is not just another remote opportunity")
    assert not is_worldwide_remote("Pakistan", description="Work remotely on meaningful engagements with US clients")
    assert not is_worldwide_remote("Karachi, Pakistan", description="Work in our Clifton office")
    assert not is_worldwide_remote("Karachi (Hybrid), Pakistan")
    assert not is_worldwide_remote("Lahore, Pakistan", description="Hybrid working model: 3 days in office, 2 days home")
    # But genuine remote in Pakistan is accepted:
    assert is_worldwide_remote("Pakistan (Remote)")
    assert is_worldwide_remote("Remote in Pakistan")
    assert is_worldwide_remote("Remote, Pakistan")
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


def test_is_title_restricted_cases():
    """Verify title-level restriction detection for US-only, domestic-only, and physical city hubs."""
    from src.models import is_title_restricted
    assert is_title_restricted("Senior Python/DevOps Engineer (100% Remote - USA Only)")
    assert is_title_restricted("Software Engineer - Backend/Infra [NYC or SF]")
    assert is_title_restricted("Backend Software Engineer (FastAPI) -Onsite in Katy, Texas")
    assert is_title_restricted("Junior Frontend Developer-US Based")
    assert is_title_restricted("Python Engineer [US-Only]")
    assert is_title_restricted("Data Scientist (US Candidates Only)")
    assert is_title_restricted("Software Engineer - Only in the US")
    # Leave-eligible: bare on-site/hybrid, commission-only, and foreign student roles
    assert is_title_restricted("SDR - AI Voice Company (Commission Only - Remote & On-Site)")
    assert is_title_restricted("Working Student – Innovation, AI & Entrepreneurship")
    assert is_title_restricted("Software Engineer - Hybrid (NYC)")
    # Beat 111: Hybrid cloud needs private/on-prem coupling — not remote for PK
    assert is_title_restricted("Hybrid Cloud Engineer")
    assert is_title_restricted("Staff Hybrid Cloud Architect")
    assert is_title_restricted("Hybrid-Cloud Engineer")
    # Legitimate non-restricted titles
    assert not is_title_restricted("AI agent engineer")
    assert not is_title_restricted("Senior Software Engineer")
    assert not is_title_restricted("Lead Python Backend Engineer")
    assert not is_title_restricted("Software Engineer: IaC Platform Experience")
    assert not is_title_restricted("Senior Machine Learning Engineer")


def test_is_worldwide_remote_rejects_title_restrictions():
    """Even if location is Worldwide or Remote, title restrictions must reject the job."""
    assert not is_worldwide_remote("Worldwide", title="Senior Python/DevOps Engineer (100% Remote - USA Only)")
    assert not is_worldwide_remote("Remote", title="Staff Software Engineer - Backend/Infra [NYC or SF]")
    assert not is_worldwide_remote("Worldwide", title="Backend Software Engineer (FastAPI) -Onsite in Katy, Texas")
    assert not is_worldwide_remote("Remote", title="Junior Frontend Developer-US Based")


def test_is_worldwide_remote_rejects_foreign_country_remote():
    """Remote positions tied to specific foreign countries outside Pakistan/APAC must be rejected."""
    assert not is_worldwide_remote("Remote, United States of America")
    assert not is_worldwide_remote("Poland, Lviv, Ivano-Frankivsk, Ternopil, Uzhhorod, Chernivtsi or Kyiv, Ukraine/Poland")
    assert not is_worldwide_remote("100% Remote, USA Only")
    assert not is_worldwide_remote("Katy, TX, United States")
    assert not is_worldwide_remote("Warsaw (fully remote), Poland")
    assert not is_worldwide_remote("Remote, Argentina")
    assert not is_worldwide_remote("Remote, Brazil")
    assert not is_worldwide_remote("Remote, Canada")


def test_is_description_restricted_cases():
    """Verify description restriction detection for US-only, hybrid, security clearance, and timezones."""
    from src.models import is_description_restricted
    assert is_description_restricted("Must reside in the US. Comprehensive health benefits.")
    assert is_description_restricted("Candidates must be authorized to work in the United States.")
    assert is_description_restricted("US citizens or permanent residents only.")
    assert is_description_restricted("No C2C, W-2 only position.")
    assert is_description_restricted("We are unable to hire outside the US at this time.")
    assert is_description_restricted("Remote (within 2 hours of London timezone)")
    assert is_description_restricted("Hybrid schedule: 3 days in the office, 2 days from home.")
    assert is_description_restricted("Must be able to commute to our NYC office.")
    assert is_description_restricted("Active secret clearance required.")
    assert is_description_restricted("100% Remote - USA Only")
    assert is_description_restricted("Must be a US Citizen or Green Card holder")
    assert is_description_restricted("Must have UK Right to Work")
    assert is_description_restricted("EU resident permit required")
    assert is_description_restricted("Must hold valid US work authorization")
    assert is_description_restricted("Must be able to work in the US")
    # Legitimate worldwide description
    assert not is_description_restricted("We are an all-remote global team building AI tools in Python. Anyone anywhere can apply.")
    assert not is_description_restricted("Supabase is remote-first and hires globally across multiple timezones.")
    assert not is_description_restricted("We hire contractors worldwide via Deel.")


def test_is_worldwide_remote_rejects_description_restrictions():
    """Worldwide or bare Remote jobs must be rejected if description contains restrictions."""
    assert not is_worldwide_remote("Worldwide", description="Must reside in the US.")
    assert not is_worldwide_remote("Remote", description="Hybrid working model: 3 days in office.")
    assert not is_worldwide_remote("Worldwide", description="Remote (within 2 hours of London timezone).")
    assert not is_worldwide_remote("Global", description="US work permit required.")
    assert is_worldwide_remote("Worldwide", description="100% remote worldwide team.")


def test_is_worldwide_remote_allowed_tags():
    """Explicitly verify the allowed location tags: worldwide, anywhere, work from home, WFH, APAC, Pakistan remote."""
    assert is_worldwide_remote("Worldwide")
    assert is_worldwide_remote("Work from anywhere")
    assert is_worldwide_remote("Anywhere in the world")
    assert is_worldwide_remote("Anywhere in World")
    assert is_worldwide_remote("Anywhere")
    assert is_worldwide_remote("Work from home")
    assert is_worldwide_remote("WFH")
    assert is_worldwide_remote("APAC")
    assert is_worldwide_remote("Asia Pacific")
    assert is_worldwide_remote("Pakistan (Remote)")
    assert is_worldwide_remote("Remote in Pakistan")
    assert is_worldwide_remote("Global Remote")


def test_is_worldwide_remote_middle_east():
    """Verify Middle East, MENA, GCC, UAE, Dubai, Saudi Arabia remote handling."""
    assert is_worldwide_remote("Middle East (Remote)")
    assert is_worldwide_remote("Remote - Middle East")
    assert is_worldwide_remote("MENA (Remote)")
    assert is_worldwide_remote("GCC (Remote)")
    assert is_worldwide_remote("Dubai (Remote)")
    assert is_worldwide_remote("Remote, UAE")
    assert is_worldwide_remote("United Arab Emirates (Remote)")
    assert is_worldwide_remote("Saudi Arabia (Remote)")
    assert is_worldwide_remote("Riyadh (Remote), Saudi Arabia")
    assert is_worldwide_remote("Qatar (Remote)")
    assert is_worldwide_remote("Remote (Iran)")
    assert not is_worldwide_remote("Remote (Israel)")  # Blocked: legal & banking impossibility for Pakistan
    assert is_worldwide_remote("Remote (Palestine)")
    assert not is_worldwide_remote("Dubai, UAE", description="This role is 100% remote work from home.")
    assert is_worldwide_remote("Dubai, UAE", description="Worldwide 100% remote work from home.")
    # On-site and hybrid office roles in Middle East must be strictly rejected
    assert not is_worldwide_remote("Dubai, UAE")
    assert not is_worldwide_remote("Dubai (Hybrid), UAE")
    assert not is_worldwide_remote("Riyadh, Saudi Arabia")
    assert not is_worldwide_remote("Doha, Qatar")
    assert not is_worldwide_remote("Tehran, Iran")
    assert not is_worldwide_remote("Tel Aviv, Israel")
    assert not is_worldwide_remote("Ramallah, Palestine")
    assert not is_worldwide_remote("Dubai, UAE", description="Hybrid role: 3 days in the Dubai office.")


def test_is_worldwide_remote_b2b_and_freelance():
    """Verify B2B and freelance contractor roles with no geographic entity restrictions."""
    assert is_worldwide_remote("Worldwide (B2B)")
    assert is_worldwide_remote("Remote (B2B Contract)")
    assert is_worldwide_remote("Remote (Freelance)")
    assert is_worldwide_remote("B2B Remote")
    assert is_worldwide_remote("Freelance Remote")
    assert is_worldwide_remote("Remote (Contract)")
    assert is_worldwide_remote("Remote (Contractor)")
    assert is_worldwide_remote("Remote (C2C)")
    assert is_worldwide_remote("Remote (Independent Contractor)")


def test_is_worldwide_remote_bare_subregions_rejected_without_remote():
    """Sub-regions like 'Southeast Asia' or 'East Asia' without remote markers are rejected."""
    assert not is_worldwide_remote("Southeast Asia")
    assert not is_worldwide_remote("East Asia")
    assert is_worldwide_remote("Southeast Asia (Remote)")
    assert is_worldwide_remote("East Asia (Remote)")


def test_is_worldwide_remote_broad_regions_and_domestic_board_apac():
    """Verify broad region names pass and US-domestic boards accept in-scope APAC/ME remote."""
    assert is_worldwide_remote("South Asia")
    assert is_worldwide_remote("Middle East")
    assert is_worldwide_remote("MENA")
    assert is_worldwide_remote("GCC")
    assert not is_worldwide_remote("Remote (India)", source="indeed")
    assert is_worldwide_remote("Remote (India) - Worldwide", source="indeed")
    # Japan is a hard-blocked APAC market (visa/tax/language) despite geography
    assert not is_worldwide_remote("Remote (Japan)", source="indeed")
    assert is_worldwide_remote("Remote (Singapore)", source="glassdoor")
    assert is_worldwide_remote("Dubai (Remote)", source="indeed")
    # Bare Remote on Indeed without in-scope markers stays rejected
    assert not is_worldwide_remote("Remote", source="indeed")


def test_is_title_restricted_foreign_domestic():
    """Verify title restrictions for UK, Canada, Europe, Germany, Poland, etc."""
    from src.models import is_title_restricted
    assert is_title_restricted("Senior AI Engineer (UK Only)")
    assert is_title_restricted("ML Engineer [Europe-Only]")
    assert is_title_restricted("AI Architect (Canada Only)")
    assert is_title_restricted("Staff Data Scientist - Germany Only")
    assert is_title_restricted("LLM Engineer (EU candidates only)")



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
    # Beat 158: bare location_type with NO location text and NO description is
    # unverifiable — fail-closed now (this assert used to encode the bypass).
    assert not is_remotely_workable("remote")
    assert is_remotely_workable(
        "remote", None, description="Work from anywhere in the world, no location requirements."
    )


def test_remote_only_uses_location_text():
    """When location text is available, is_worldwide_remote takes precedence."""
    from src.main import is_remotely_workable
    assert is_remotely_workable("remote", "Remote")
    assert is_remotely_workable("remote", "Worldwide")
    assert not is_remotely_workable("remote", "Remote in Brooklyn, NY")
    assert not is_remotely_workable("remote", "Remote, Oregon")
    # On-site and hybrid must ALWAYS be rejected even if location is provided
    assert not is_remotely_workable("onsite", "Islamabad, Islāmābād, Pakistan")
    assert not is_remotely_workable("onsite", "Pakistan")
    assert not is_remotely_workable("hybrid", "Karachi, Pakistan")
    assert not is_remotely_workable("onsite", "Islamabad, Islāmābād, Pakistan", description="remote opportunity")
    assert not is_remotely_workable("onsite", "Pakistan", description="work remotely with US clients")


def test_classify_location_pakistan_and_title_remote():
    from src.models import classify_location
    assert classify_location("Pakistan (Remote)") == "remote"
    assert classify_location("Remote in Pakistan") == "remote"
    assert classify_location("Remote, Pakistan") == "remote"
    assert classify_location("Islamabad, Islāmābād, Pakistan") == "onsite"
    assert classify_location("Pakistan") == "onsite"
    assert classify_location("Lahore, Punjab, Pakistan") == "onsite"
    assert classify_location("Karachi (Hybrid)") == "hybrid"
    # Title remote overrides bare physical location
    assert classify_location("Islamabad, Islāmābād, Pakistan", title="Senior AI Engineer (Remote)") == "remote"
    assert classify_location("Pakistan", title="Senior Software Engineer") == "onsite"


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


def test_is_valid_job_url_rejects_profile_urls():
    from src.models import is_valid_job_url
    assert not is_valid_job_url("https://www.linkedin.com/in/rana-hamza-22292123b/")
    assert not is_valid_job_url("https://www.linkedin.com/in/abdul-muqeet/")
    assert not is_valid_job_url("https://www.linkedin.com/in/sundaramx/")
    assert not is_valid_job_url("ftp://example.com/job")
    assert not is_valid_job_url("")
    assert not is_valid_job_url(None)
    assert is_valid_job_url("https://www.linkedin.com/jobs/view/4467933585/")
    assert is_valid_job_url("https://boards.greenhouse.io/company/jobs/12345")
    assert is_valid_job_url("https://jobs.lever.co/company/abc-123")


def test_matcher_rejects_business_and_recruiting_roles():
    from src.matcher import is_blacklisted_title, match_usama_cv
    title1 = "Founding Business Leader (Agentic AI Talent Intelligence) - Global AI-Native Tech Talent Venture"
    is_bl, _ = is_blacklisted_title(title1)
    assert is_bl
    matched, score, _ = match_usama_cv(title1)
    assert not matched
    assert score == 0

    title2 = "Specialist, Multimedia & Generative AI Production at SHRM"
    is_bl2, _ = is_blacklisted_title(title2)
    assert is_bl2

    title3 = "Postdoctoral Researcher / Research Scientist & Research / Software Engineer"
    is_bl3, _ = is_blacklisted_title(title3)
    assert is_bl3


def test_phase2_strict_location_and_remote_filtering():
    from src.models import is_worldwide_remote

    allowed_keywords = [
        "worldwide", "anywhere", "global", "remote - worldwide",
        "work from home", "pakistan remote", "apac remote"
    ]
    for kw in allowed_keywords:
        assert is_worldwide_remote(kw), f"Expected {kw} to pass"

    forbidden_keywords = [
        "onsite", "hybrid", "india", "usa", "united states", "uk",
        "canada", "germany", "remote, or", "remote, ca", "remote - us", "remote (india)"
    ]
    for kw in forbidden_keywords:
        assert not is_worldwide_remote(kw), f"Expected {kw} to be rejected"


def test_phase4_link_health_check(monkeypatch):
    from src.models import check_link_health
    import requests

    class Mock404:
        status_code = 404

    class Mock200:
        status_code = 200

    def mock_head_404(url, **kwargs):
        return Mock404()

    def mock_head_200(url, **kwargs):
        return Mock200()

    monkeypatch.setattr(requests, "head", mock_head_404)
    assert not check_link_health("https://example.com/job/404")

    monkeypatch.setattr(requests, "head", mock_head_200)
    assert check_link_health("https://example.com/job/200")


def test_phase1_schedule_windows():
    from datetime import datetime, timezone, timedelta
    from src.schedule import compute_fetch_window, FREQ_BACKFILL, FREQ_DAILY, FREQ_WEEKLY

    # Monday (2026-09-14)
    monday = datetime(2026, 9, 14, 9, 0, tzinfo=timezone.utc)
    win_mon = compute_fetch_window(monday)
    assert win_mon.reason == FREQ_BACKFILL
    assert win_mon.window_end - win_mon.window_start == timedelta(days=3)

    # Tuesday (2026-09-15)
    tue = datetime(2026, 9, 15, 9, 0, tzinfo=timezone.utc)
    win_tue = compute_fetch_window(tue)
    assert win_tue.reason == FREQ_DAILY
    assert win_tue.window_end - win_tue.window_start == timedelta(hours=24)

    # Wednesday (2026-09-16)
    wed = datetime(2026, 9, 16, 9, 0, tzinfo=timezone.utc)
    win_wed = compute_fetch_window(wed)
    assert win_wed.reason == FREQ_DAILY
    assert win_wed.window_end - win_wed.window_start == timedelta(hours=24)

    # Thursday (2026-09-17)
    thu = datetime(2026, 9, 17, 9, 0, tzinfo=timezone.utc)
    win_thu = compute_fetch_window(thu)
    assert win_thu.reason == FREQ_DAILY
    assert win_thu.window_end - win_thu.window_start == timedelta(hours=24)

    # Friday (2026-09-18)
    fri = datetime(2026, 9, 18, 9, 0, tzinfo=timezone.utc)
    win_fri = compute_fetch_window(fri)
    assert win_fri.reason == FREQ_WEEKLY
    assert win_fri.sources == ["linkedin"]


def test_phase3_url_validation():
    from src.models import is_valid_job_url

    # Negative profile link selector
    assert not is_valid_job_url("https://www.linkedin.com/in/john-doe")
    assert not is_valid_job_url("https://linkedin.com/in/recruiter-specialist-123/")
    assert not is_valid_job_url("https://www.linkedin.com/in/sarah-talent/")
    assert not is_valid_job_url("")
    assert not is_valid_job_url(None)
    assert not is_valid_job_url("ftp://invalid-protocol")

    # Valid application and feed update links
    assert is_valid_job_url("https://www.linkedin.com/feed/update/urn:li:activity:7123456789012345678/")
    assert is_valid_job_url("https://boards.greenhouse.io/openai/jobs/400123")
    assert is_valid_job_url("https://jobs.lever.co/anthropic/500456")
    assert is_valid_job_url("https://company.com/careers/ai-engineer")
