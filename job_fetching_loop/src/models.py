"""Data models: RawJob (source-level) and NormalizedJob (standard schema)."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

SOURCE_NAMES = [
    "remote_rocketship",
    "working_nomads",
    "linkedin",
    "indeed",
    "glassdoor",
    "apac_remote",
    "pakistan_remote",
    "remotive",
    "remoteok",
    "himalayas",
    "weworkremotely",
    "jobicy",
    "justremote",
    "wellfound",
    "nodesk",
    "arbeitnow",
    "python_org",
]

# Salary parsing units (k/m plus Indian/Pakistani lakh conventions)
_SALARY_MULTIPLIERS = {
    "k": 1_000,
    "m": 1_000_000,
    "l": 100_000,
    "lakh": 100_000,
    "lac": 100_000,
    "lpa": 100_000,
}

# Normalized location buckets
LOCATION_REMOTE = "remote"
LOCATION_HYBRID = "hybrid"
LOCATION_ONSITE = "onsite"
LOCATION_UNKNOWN = "unknown"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def canonical_job_url(url: str, source: str | None = None) -> str:
    """Canonicalize tracking / dynamic query parameters from job URLs for consistent hashing."""
    if not url:
        return ""
    if source == "indeed" or "indeed.com" in url:
        m = re.search(r"[?&]jk=([a-fA-F0-9]+)", url)
        if m:
            return f"https://www.indeed.com/viewjob?jk={m.group(1)}"
    if source == "glassdoor" or "glassdoor.com" in url:
        m = re.search(r"[?&]jl=(\d+)", url)
        if m:
            return f"https://www.glassdoor.com/job-listing/?jl={m.group(1)}"
    return url


def job_id(url: str, title: str, company: str, source: str | None = None) -> str:
    """Deterministic hash for exact-match dedup (Layer 1)."""
    canon_url = canonical_job_url(url, source=source)
    raw = f"{canon_url.lower().strip()}|{title.lower().strip()}|{company.lower().strip()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def normalize_text(s: str | None) -> str:
    """Lowercase + collapse whitespace + strip punctuation, for fuzzy matching."""
    if not s:
        return ""
    s = s.lower()
    s = re.sub(r"[\W_]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


@dataclass
class RawJob:
    """Unprocessed job as received from a source (before normalization)."""

    source: str
    title: str
    company: str
    url: str
    location: str | None = None
    salary: str | None = None
    posted_date: str | None = None
    description: str | None = None
    job_type: str | None = None
    tags: list[str] = field(default_factory=list)
    fetched_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "title": self.title,
            "company": self.company,
            "url": self.url,
            "location": self.location,
            "salary": self.salary,
            "posted_date": self.posted_date,
            "description": self.description,
            "job_type": self.job_type,
            "tags": self.tags,
            "fetched_at": self.fetched_at.isoformat(),
        }


@dataclass
class NormalizedJob:
    """Standard job record after normalization + dedup."""

    id: str
    title: str
    title_normalized: str
    company: str
    company_normalized: str
    url: str
    source: str
    location: str | None
    location_type: str
    salary_min: int | None
    salary_max: int | None
    salary_currency: str | None
    job_type: str
    posted_date: date | None
    fetched_at: datetime
    tags: list[str]
    description_snippet: str
    cv_match_score: int = 0
    cv_match_label: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "title_normalized": self.title_normalized,
            "company": self.company,
            "company_normalized": self.company_normalized,
            "url": self.url,
            "source": self.source,
            "location": self.location,
            "location_type": self.location_type,
            "salary_min": self.salary_min,
            "salary_max": self.salary_max,
            "salary_currency": self.salary_currency,
            "job_type": self.job_type,
            "posted_date": self.posted_date.isoformat() if self.posted_date else None,
            "fetched_at": self.fetched_at.isoformat(),
            "tags": self.tags,
            "description_snippet": self.description_snippet,
            "cv_match_score": self.cv_match_score,
            "cv_match_label": self.cv_match_label,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "NormalizedJob":
        return cls(
            id=str(d.get("id", "")),
            title=str(d.get("title", "")),
            title_normalized=normalize_text(d.get("title")),
            company=str(d.get("company", "")),
            company_normalized=normalize_text(d.get("company")),
            url=str(d.get("url", "")),
            source=str(d.get("source", "")),
            location=d.get("location"),
            location_type=str(d.get("location_type", LOCATION_UNKNOWN)),
            salary_min=d.get("salary_min"),
            salary_max=d.get("salary_max"),
            salary_currency=d.get("salary_currency"),
            job_type=str(d.get("job_type", "unknown")),
            posted_date=_parse_date(d.get("posted_date")),
            fetched_at=_parse_datetime(d.get("fetched_at")),
            tags=list(d.get("tags", [])),
            description_snippet=str(d.get("description_snippet", "")),
            cv_match_score=int(d.get("cv_match_score", 0)),
            cv_match_label=str(d.get("cv_match_label", "")),
            raw=dict(d.get("raw", {})),
        )


_US_STATE_NAMES = frozenset({
    # 50 states + DC, lowercase — used to detect region-restricted "Remote"
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine",
    "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
    "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey",
    "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina",
    "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
    "washington", "west virginia", "wisconsin", "wyoming", "district of columbia",
})

# Two-letter postal abbreviations that are NOT also common English words, so
# matching them alongside "Remote" is unambiguous ("Remote, OR" is a city;
# with the abbreviation set we also catch "TX - Remote", "MD - Remote").
_US_STATE_ABBR = frozenset({
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "dc", "fl", "ga", "hi",
    "id", "il", "in", "ks", "ky", "la", "md", "ma", "mi", "mn", "ms", "mo",
    "mt", "ne", "nv", "nj", "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa",
    "ri", "sc", "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy",
})

_US_RESTRICTED_RE = re.compile(
    r"(?i)(?:remote\s*\(([^)]*)\)"          # "Remote (US Only)" / "Remote (San Francisco)"
    r"|remote\s*[-,–/]\s*([A-Za-z .]+)"  # "Remote - US Only" / "Remote - Texas" / "Remote / US"
    r"|([A-Za-z .]+?)\s*[-,–/]\s*remote)"  # "Maryland – Remote" / "TX - Remote" / "US - Remote"
)

US_DOMESTIC_BOARDS = frozenset({"indeed", "glassdoor", "ziprecruiter", "monster"})

_WORLDWIDE_MARKERS = (
    "worldwide", "work from anywhere", "anywhere in the world",
    "global remote", "globally remote", "remote - global", "remote (global)",
    "remote - worldwide", "remote (worldwide)", "international remote",
    "remote international", "work from home", "wfh", "anywhere",
    "pakistan remote", "remote in pakistan", "pakistan (remote)", "remote (pakistan)", "remote - pakistan",
    "apac remote", "asia pacific remote", "south asia remote", "remote (apac)",
)


def _is_us_restricted(text: str) -> bool:
    """True when the location ties work to a specific US state/city/region.

    The word "Remote" is also a US city name (Remote, OR) and is commonly
    paired with a US state to mean *region-restricted* remote ("Maryland –
    Remote", "TX - Remote", "Remote (US Only)").  A bare "Remote" with no
    such qualifier is the only form we count as worldwide/anywhere remote,
    so this detector must trip on every restricted variant.
    """
    if not text:
        return False
    low = text.lower()
    # Explicit disambiguation for Remote, Oregon (Coos County, OR, ZIP 97458)
    if (re.search(r"\bremote\s*,\s*(?:or|oregon)\b", low)
            or re.search(r"\bremote\s+(?:or|oregon)\b", low)
            or re.search(r"\bcoos\s+county\b", low)
            or re.search(r"\bremote\b.*\b97458\b", low)):
        return True

    for state in _US_STATE_NAMES:
        if re.search(rf"\b{re.escape(state)}\b", low):
            if "remote" in low or "anywhere" in low:
                return True
    # Postal abbreviation immediately adjacent to "Remote" (dash/comma/paren/slash)
    m = _US_RESTRICTED_RE.search(text)
    if not m:
        return False
    for grp in m.groups():
        if not grp:
            continue
        grp_low = grp.lower().strip()
        if re.search(r"\b(us|usa|united states|u\.s\.a?)\b", grp_low):
            return True
        if any(phrase in grp_low for phrase in ("us only", "usa only", "u.s. only", "u.s.a. only", "united states only", "u.s.")):
            return True
        two_letter_words = set(re.findall(r"\b[a-z]{2}\b", grp_low))
        if any(w in _US_STATE_ABBR for w in two_letter_words):
            return True
        if any(re.search(rf"\b{re.escape(name)}\b", grp_low) for name in _US_STATE_NAMES):
            return True
    return False


def classify_location(location: str | None, title: str | None = None) -> str:
    """Classify a location string into LOCATION_REMOTE, LOCATION_HYBRID, or LOCATION_ONSITE.

    Distinguishes bare "Remote" from city-restricted remote like "Remote, OR"
    (the hamlet of Remote in Coos County, Oregon) and "Remote in Brooklyn, NY"
    (Indeed city-restricted).
    """
    loc_text = (location or "").lower().strip()
    title_text = (title or "").lower().strip()

    title_has_remote = any(
        w in title_text
        for w in ("(remote)", "- remote", "[remote]", "remote)", "(wfh)", "- wfh", "work from home")
    )

    if not loc_text:
        if title_has_remote:
            return LOCATION_REMOTE
        return LOCATION_UNKNOWN

    text = loc_text

    # Definitive remote indicators (unambiguous)
    if ("worldwide" in text or "work from anywhere" in text or "anywhere" in text
            or "work from home" in text or "wfh" in text
            or "global" in text or "apac" in text or "asia pacific" in text
            or re.search(r"\bremote\s+in\s+pakistan\b", text)
            or re.search(r"\bremote\s*,\s*pakistan\b", text)):
        if not any(w in text for w in ("on-site", "onsite", "on site", "in-office", "hybrid")):
            return LOCATION_REMOTE

    # Handle the word "Remote" — distinguish from city names
    # Patterns that are NOT remote:
    #   "Remote, OR" / "Remote, Oregon"          -> city name (physical town)
    #   "Remote in Brooklyn, NY"                 -> city-restricted (Indeed)
    #   "Remote in Windsor, CO 80550"            -> city-restricted
    #   "San Francisco, CA (Remote)"             -> has city, ambiguous → treat as hybrid
    #   "Maryland – Remote" / "TX - Remote"      -> US region-restricted → NOT worldwide
    # Patterns that ARE remote:
    #   "Remote" / "REMOTE"                      -> bare token
    #   "Remote (Worldwide)" / "Remote - Worldwide" -> explicitly worldwide
    #   "Remote (US Only)"                       -> region-restricted but still remote
    is_city_name = (
        bool(re.search(r"remote\s+in\s+\w", text) and "pakistan" not in text)
        or bool(re.search(r"remote\s*,\s+[a-z]{2}\b", text))
        or bool(re.search(r"\bremote\s+(?:or|oregon)\b", text))
        or bool(re.search(r"\bcoos\s+county\b", text))
    )
    is_bare_remote = re.search(r"(?:^|[(,;|\s])remote(?:$|[),\s(;\-])", text) is not None

    if (is_bare_remote and not is_city_name) or title_has_remote:
        if _is_us_restricted(text) and not re.search(r"remote\s*\(", text):
            return LOCATION_ONSITE
        if any(w in text for w in ("on-site", "onsite", "on site", "in-office", "hybrid")):
            return LOCATION_HYBRID if "hybrid" in text else LOCATION_ONSITE
        return LOCATION_REMOTE

    if "hybrid" in text or "flexible" in text:
        return LOCATION_HYBRID
    if any(w in text for w in ("on-site", "onsite", "on site", "in-office", "in office")):
        return LOCATION_ONSITE
    # A city/country without remote markers -> on-site by default
    return LOCATION_ONSITE


def is_worldwide_remote(
    location: str | None,
    source: str | None = None,
    description: str | None = None,
) -> bool:
    """True only when the job is clearly remote *without* US-restriction.

    Used by SCRAPE_REMOTE_ONLY: drops US state/city-restricted remote jobs
    (e.g. "Maryland – Remote", "Remote (US Only)", "Remote, OR"), US domestic-only
    remote jobs posted on US boards without worldwide eligibility (e.g. Indeed/Glassdoor
    bare "Remote"), and non-remote positions.

    In-scope remote (worldwide / Global / APAC / Pakistan / South-Asia neighbor remote)
    qualifies for this Pakistan-based loop.
    """
    if not location:
        return False
    text = location.lower().strip()

    # Remote, Oregon disambiguation (physical hamlet in Coos County, OR)
    if (re.search(r"\bremote\s*,\s*(?:or|oregon)\b", text)
            or re.search(r"\bremote\s+(?:or|oregon)\b", text)
            or re.search(r"\bcoos\s+county\b", text)
            or re.search(r"\bremote\b.*\b97458\b", text)):
        return False

    # Country/region-restricted anywhere (e.g. "anywhere in India", "anywhere in the US")
    # Only "anywhere in the world" or "work from anywhere" is allowed
    if re.search(r"anywhere\s+in\s+(?!the\s+world\b)", text):
        return False

    # US-domestic boards (Indeed, Glassdoor): bare "Remote" is domestic US remote
    # (requires US residency / SSN / W-2). Reject unless explicitly worldwide/global
    # in location or description.
    if source and source.lower() in US_DOMESTIC_BOARDS:
        combined = f"{text} {(description or '').lower()}"
        if not any(m in combined for m in _WORLDWIDE_MARKERS):
            return False

    # Definitive worldwide / anywhere / work-from-home indicators
    if any(w in text for w in (
        "worldwide", "work from anywhere", "anywhere in the world", "global",
        "work from home", "wfh", "telecommute", "100% remote", "fully remote"
    )):
        if not _is_us_restricted(text) or "worldwide" in text or "global" in text:
            return True

    # In-scope regional targets (APAC, Asia Pacific, South Asia)
    if any(w in text for w in ("apac", "asia pacific", "south asia")):
        if not _is_us_restricted(text):
            return True

    # Pakistan: allow if explicitly remote in location text
    # (e.g. "Pakistan (Remote)", "Remote in Pakistan", "Remote, Pakistan", WFH)
    # OR if description explicitly declares 100% remote / fully remote / work from home / wfh.
    # Strictly reject physical on-site/hybrid city postings
    # (e.g. "Lahore, Punjab, Pakistan", "Karachi (Hybrid)", "Islamabad, Islāmābād, Pakistan")
    # and bare country postings ("Pakistan") without explicit remote/wfh markers.
    if "pakistan" in text:
        if any(w in text for w in ("hybrid", "onsite", "on-site", "in-office", "office only", "office-based")):
            return False
        desc_lower = (description or "").lower()
        if any(w in desc_lower for w in ("hybrid", "onsite", "on-site", "in-office", "office only", "office-based")):
            return False
        has_remote_in_loc = any(w in text for w in ("remote", "work from home", "wfh", "anywhere", "telecommute"))
        has_explicit_remote_desc = any(
            w in desc_lower for w in ("100% remote", "fully remote", "work from home", "wfh", "100% work from home")
        )
        if not (has_remote_in_loc or has_explicit_remote_desc):
            return False
        if not _is_us_restricted(text):
            return True
        return False

    # Standalone "anywhere"
    if "anywhere" in text and not _is_us_restricted(text):
        return True

    # Bare "Remote" with no city/state qualifier = worldwide by convention
    is_city_name = (
        bool(re.search(r"remote\s+in\s+\w", text))
        or bool(re.search(r"remote\s*,\s+[a-z]", text))
        or bool(re.search(r"\bremote\s+(?:or|oregon)\b", text))
        or bool(re.search(r"\bcoos\s+county\b", text))
    )
    is_bare_remote = re.search(r"(?:^|[,;|\s])remote(?:$|[,\s(;\-])", text) is not None
    if is_bare_remote and not is_city_name:
        # But reject region qualifiers like "Remote (US Only)" and
        # "Maryland – Remote" / "TX - Remote" (US state-restricted remote)
        if _is_us_restricted(text):
            return False
        # Bare remote with a qualifier: in-scope qualifiers (worldwide,
        # APAC / Asia Pacific, Pakistan, anywhere, and South-Asia
        # neighbors) qualify; any other qualifier stays rejected.
        if re.search(r"remote\s*\((?!.*(?:worldwide|apac|asia pacific|pakistan|anywhere|anytime|india|bangladesh|sri lanka|nepal|islamabad|lahore|karachi|rawalpindi))", text):
            return False
        return True
    return False


# ── Expired job detection ────────────────────────────────────────────────────

_EXPIRED_TITLE_RE = re.compile(
    r"\b(closed|expired|no longer (?:accepting|accepting applications|available|accepting applications)"
    r"|filled|ended|terminated|withdrawn|cancelled|canceled)\b",
    re.IGNORECASE,
)


def is_expired_job(raw: RawJob) -> bool:
    """Detect jobs that are closed, expired, or no longer available."""
    title = (raw.title or "").strip()
    if _EXPIRED_TITLE_RE.search(title):
        return True
    desc = (raw.description or "").lower()
    if any(phrase in desc for phrase in (
        "this position has been filled",
        "this job is no longer",
        "this job has expired",
        "applications are closed",
        "no longer accepting applications",
    )):
        return True
    return False


def parse_salary(raw: str | None) -> tuple[int | None, int | None, str | None]:
    """Parse '180k-220k', '$150-200K', '$150,000 - $200,000', '£120k', '$200k+',
    '₹25L-30L', '3.5 LPA' into (min, max, currency)."""
    if not raw or not re.search(r"\d", raw):
        # "N/A", "Not specified", empty → no numbers, no made-up currency
        return None, None, None
    currency_match = re.match(r"^\s*([$£€₹A-Za-z]*)", raw)
    currency = currency_match.group(1) if currency_match else None
    if currency and not currency.isalpha() and currency not in (
        "$", "£", "€", "₹", "Rs", "PKR", "USD", "EUR", "GBP", "INR",
    ):
        currency = None

    # Strip thousand-separator commas (e.g. $150,000 -> $150000) so commas don't split values
    cleaned = re.sub(r"(?<=\d),(?=\d)", "", raw)

    nums = re.findall(r"(\d+(?:\.\d+)?)\s*((?:lakh|lac|lpa|[kKmMlL])?)", cleaned)
    if not nums:
        return None, None, currency

    # Propagate multiplier suffix across range if one number omits it (e.g. "$150-200K", "$150K-200", "25-30L")
    if len(nums) >= 2:
        val0, suf0 = nums[0]
        val1, suf1 = nums[1]
        if not suf0 and suf1:
            mult1 = _SALARY_MULTIPLIERS.get(suf1.lower())
            if mult1:
                try:
                    f0 = float(val0)
                    f1 = float(val1)
                    if f0 <= f1 or f0 < 1000:
                        nums[0] = (val0, suf1)
                except ValueError:
                    pass
        elif suf0 and not suf1:
            mult0 = _SALARY_MULTIPLIERS.get(suf0.lower())
            if mult0:
                try:
                    f0 = float(val0)
                    f1 = float(val1)
                    if f1 >= f0 or f1 < 1000:
                        nums[1] = (val1, suf0)
                except ValueError:
                    pass

    # Annual indicator check: if unsuffixed but explicitly annual (e.g. "$150 - 200 / yr", "$120 / year")
    is_annual = bool(re.search(r"(?i)(?:\bper\s+year|/\s*yr\b|/\s*year\b|\bannually\b|\bannual\b|\bper\s+annum|/\s*annum\b)", raw))
    is_hourly = bool(re.search(r"(?i)(?:\bper\s+hour|/\s*hr\b|/\s*hour\b|\bhourly\b)", raw))

    parsed = []
    for val, suffix in nums:
        multiplier = _SALARY_MULTIPLIERS.get(suffix.lower())
        if not multiplier and is_annual and not is_hourly:
            try:
                fval = float(val)
                if 20 <= fval < 1000:
                    multiplier = 1000
            except ValueError:
                pass
        parsed.append(int(float(val) * multiplier) if multiplier else int(float(val)))

    if len(parsed) == 1:
        return parsed[0], None, currency or None
    return parsed[0], parsed[1], currency or None


def parse_posted_datetime(value: str | None, now: datetime | None = None) -> datetime | None:
    """Parse a full UTC-aware datetime from ISO timestamps if available."""
    if not value:
        return None
    text = str(value).strip()
    try:
        # Full ISO with time (e.g. 2026-09-17T04:12:00Z or 2026-09-17T04:12:00+00:00)
        if "T" in text or " " in text:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
    except ValueError:
        pass
    return None


def classify_job_type(raw: str | None) -> str:
    if not raw:
        return "unknown"
    text = raw.lower()
    if "full" in text:
        return "full-time"
    if "part" in text:
        return "part-time"
    if "contract" in text or "freelance" in text:
        return "contract"
    return "unknown"


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


# Relative post-age units (Indeed/Glassdoor emit "Posted 3 days ago", "30+ days ago", "6d").
_RELATIVE_UNITS = {
    "day": 1, "days": 1, "d": 1,
    "hr": 0, "hour": 0, "hours": 0,  # hours ago -> posted today
    "week": 7, "weeks": 7, "w": 7,
    "mo": 30, "month": 30, "months": 30,
    "year": 365, "years": 365, "y": 365,
}


def parse_posted_date(value: str | None, today: date | None = None) -> date | None:
    """Parse a source's `posted_date` string into a date.

    Accepts ISO dates/timestamps ("2026-09-11", "2026-09-11T10:00:00+00:00"),
    "Today"/"Yesterday", and the relative strings Indeed/Glassdoor emit
    ("Posted 3 days ago", "30+ days ago", "6d"). Any unparseable value returns
    None so downstream code degrades to fetched_at instead of failing."""
    if not value:
        return None
    text = str(value).strip()
    today = today or utc_now().date()

    lowered = text.lower()
    if lowered.startswith("posted "):
        lowered = lowered[len("posted "):]
    if lowered in ("today", "now", "just now"):
        return today
    if lowered == "yesterday":
        return today - timedelta(days=1)

    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass

    m = re.search(
        r"(\d+(?:\.\d+)?)\s*\+?\s*(day|days|d|hr?|hours?|week|weeks|w|mo|month|months|year|years|y)\b",
        text.lower(),
    )
    if m:
        unit = m.group(2)
        delta_days = int(round(float(m.group(1)) * _RELATIVE_UNITS[unit]))
        return today - timedelta(days=delta_days)
    return None


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return utc_now()


def keyword_matches(job: RawJob, keywords: list[str]) -> bool:
    """True when a keyword matches the title or description at word boundaries.

    Substring matching is too noisy ('AI' inside 'tr*ai*ning'); short keywords
    must match a contiguous lowercase word (or hyphenated token).
    """
    title = job.title.lower()
    desc = (job.description or "").lower()
    haystack = f"{title}\n{desc}"
    for raw_kw in keywords:
        kw = raw_kw.lower().strip()
        if not kw:
            continue
        if " " in kw:
            # multi-word keywords: appear as an exact contiguous phrase
            if kw in haystack:
                return True
        else:
            # single-token keyword (incl. abbreviations like 'ai', 'ml'):
            # match whole words only
            for token in re.findall(r"[a-z0-9+#]+", haystack):
                if token == kw:
                    return True
    return False


def ai_keyword_matches(job: RawJob, ai_keywords: list[str], role_keywords: list[str] | None = None) -> bool:
    """AI-domain gate: requires candidate CV match (Muhammad Usama profile)
    and strictly drops blacklisted non-technical roles and unrelated tech stacks.
    """
    from src.matcher import match_usama_cv
    is_match, score, label = match_usama_cv(job.title, job.description, job.tags)
    return is_match

