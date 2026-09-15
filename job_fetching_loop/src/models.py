"""Data models: RawJob (source-level) and NormalizedJob (standard schema)."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
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
    "himalayas",
    "feedcoyote",
    "justremote",
    "wellfound",
    "jobboardsearch",
    "flexjobs",
    "dynamitejobs",
    "virtual_vocations",
    "nodesk",
]

# Salary parsing units
_SALARY_MULTIPLIERS = {"k": 1_000, "m": 1_000_000}

# Normalized location buckets
LOCATION_REMOTE = "remote"
LOCATION_HYBRID = "hybrid"
LOCATION_ONSITE = "onsite"
LOCATION_UNKNOWN = "unknown"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def job_id(url: str, title: str, company: str) -> str:
    """Deterministic hash for exact-match dedup (Layer 1)."""
    raw = f"{url.lower().strip()}|{title.lower().strip()}|{company.lower().strip()}"
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
            raw=dict(d.get("raw", {})),
        )


def classify_location(location: str | None) -> str:
    """Map a free-text location to a normalized bucket.

    CONTEXT-AWARE: the word "Remote" appears in both work-mode descriptions
    ("Remote", "Remote (Worldwide)") and US city names ("Remote, OR",
    "Remote, Oregon").  The classifier checks for *definitive* remote
    indicators first, then only treats bare "Remote" as remote when it's
    clearly a standalone location token — NOT when followed by a city/state
    or preceded by a comma (e.g. "San Francisco, Remote" is ambiguous).
    """
    if not location:
        return LOCATION_UNKNOWN
    text = location.lower().strip()

    # Definitive remote indicators (unambiguous)
    if ("worldwide" in text or "work from anywhere" in text or "anywhere" in text
            or "work from home" in text or "wfh" in text):
        return LOCATION_REMOTE

    # Handle the word "Remote" — distinguish from city names
    # Patterns that are NOT remote:
    #   "Remote, OR" / "Remote, Oregon"          -> city name
    #   "Remote in Brooklyn, NY"                 -> city-restricted (Indeed)
    #   "Remote in Windsor, CO 80550"            -> city-restricted
    #   "San Francisco, CA (Remote)"             -> has city, ambiguous → treat as hybrid
    # Patterns that ARE remote:
    #   "Remote" / "REMOTE"                      -> bare token
    #   "Remote (Worldwide)" / "Remote - Worldwide" -> explicitly worldwide
    #   "Remote (US Only)"                       -> region-restricted but still remote
    is_city_name = bool(re.search(r"remote\s+in\s+\w", text)) or bool(re.search(r"remote\s*,\s+[a-z]", text))
    is_bare_remote = re.search(r"(?:^|[,;|\s])remote(?:$|[,\s(;\-])", text) is not None

    if is_bare_remote and not is_city_name:
        return LOCATION_REMOTE

    if "hybrid" in text or "flexible" in text:
        return LOCATION_HYBRID
    if any(w in text for w in ("on-site", "onsite", "on site", "in-office", "in office")):
        return LOCATION_ONSITE
    # A city/country without remote markers -> on-site by default
    return LOCATION_ONSITE


def is_worldwide_remote(location: str | None) -> bool:
    """True only when the job is clearly remote *without* geographic restriction.

    Used by SCRAPE_REMOTE_ONLY: drops city/state-restricted remote jobs
    (e.g. "Remote in Brooklyn, NY") and non-remote positions entirely.
    """
    if not location:
        return False
    text = location.lower().strip()
    # Definitive worldwide indicators
    if "worldwide" in text or "work from anywhere" in text or "anywhere" in text:
        return True
    # Bare "Remote" with no city/state qualifier = worldwide by convention
    is_city_name = bool(re.search(r"remote\s+in\s+\w", text)) or bool(re.search(r"remote\s*,\s+[a-z]", text))
    is_bare_remote = re.search(r"(?:^|[,;|\s])remote(?:$|[,\s(;\-])", text) is not None
    if is_bare_remote and not is_city_name:
        # But reject region qualifiers like "Remote (US Only)"
        if re.search(r"remote\s*\((?!.*worldwide)", text):
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
    """Parse '180k-220k', '$150-200K', '£120k', '$200k+' into (min, max, currency)."""
    if not raw:
        return None, None, None
    currency_match = re.match(r"^\s*([$£€A-Za-z]*)", raw)
    currency = currency_match.group(1) if currency_match else None
    if currency and not currency.isalpha() and currency not in ("$", "£", "€", "Rs", "PKR", "USD", "EUR", "GBP"):
        currency = None

    nums = re.findall(r"(\d+(?:\.\d+)?)\s*([kKmM]?)", raw)
    if not nums:
        return None, None, currency

    parsed = []
    for val, suffix in nums:
        multiplier = _SALARY_MULTIPLIERS.get(suffix.lower())
        parsed.append(int(float(val) * multiplier) if multiplier else int(float(val)))

    if len(parsed) == 1:
        return parsed[0], None, currency or None
    return parsed[0], parsed[1], currency or None


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
    """AI-domain gate: requires at least one primary AI keyword to match.

    Role keywords (Engineer/Developer) alone never qualify a job — they only
    refine within the AI domain. A 'Java Developer' with no AI term is rejected.
    """
    if any(keyword_matches(job, [kw]) for kw in ai_keywords):
        return True
    return False