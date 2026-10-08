"""Data models: RawJob (source-level) and NormalizedJob (standard schema)."""
from __future__ import annotations

import hashlib
import re
import unicodedata
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


def is_valid_job_url(url: str | None) -> bool:
    """True if URL points to a legitimate job posting, not a user profile or root domain."""
    if not url:
        return False
    u = url.lower().strip()
    if not (u.startswith("http://") or u.startswith("https://")):
        return False
    # Never accept LinkedIn user profiles as job URLs
    if "linkedin.com/in/" in u:
        return False
    return True


def check_link_health(url: str, timeout_s: float = 1.5) -> bool:
    """True if link is alive (or health is indeterminate); False only on definitive death.

    Fail-closed only for proof of death (404/410). Network flake / timeout /
    TLS weirdness must NOT drop a valid Rule-11 job (symmetric with
    `is_expired_job`: unknown stays, known-dead goes).

    PR #13 finding 2: default timeout is 1.5s (was 3.0) so a per-job HEAD
    cannot blow the source/run budget; callers should invoke this only for
    jobs that already survived every other gate."""
    if not is_valid_job_url(url):
        return False
    import os
    import requests
    # In unmocked pytest runs, do not make live outbound requests on dummy test domains
    if os.environ.get("PYTEST_CURRENT_TEST") and getattr(requests.head, "__module__", "") == "requests.api":
        return True

    def _close(r) -> None:
        close = getattr(r, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    try:
        headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        resp = requests.head(url, headers=headers, timeout=timeout_s, allow_redirects=True)
        try:
            if resp.status_code == 405:
                _close(resp)  # PR #13: never leak the HEAD response
                resp = requests.get(url, headers=headers, timeout=timeout_s, stream=True)
            if resp.status_code in (404, 410):
                return False
            return True
        finally:
            _close(resp)
    except requests.exceptions.HTTPError:
        # 4xx other than 404/410 still answers — treat as alive enough to keep
        return True
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        # Indeterminate: DNS blip / RST / slow origin — keep the job
        return True
    except Exception:
        # Unknown client-side error — do not punish the job for our stack
        return True


def canonical_job_url(url: str, source: str | None = None) -> str:
    """Canonicalize tracking / dynamic query parameters from job URLs for consistent hashing."""
    if not url:
        return ""
    if source == "indeed" or "indeed.com" in url:
        m = re.search(r"[?&]jk=([a-fA-F0-9]+)", url)
        if m:
            return f"https://www.indeed.com/viewjob?jk={m.group(1)}"
    if source == "glassdoor" or "glassdoor.com" in url:
        m = re.search(r"[?&](?:jl|jobListingId)=(\d+)", url)
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
    profile_scores: dict[str, int] = field(default_factory=dict)
    profile_best: str = ""
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
            "profile_scores": self.profile_scores,
            "profile_best": self.profile_best,
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
            profile_scores=dict(d.get("profile_scores") or {}),
            profile_best=str(d.get("profile_best") or ""),
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

# A3: major US metros that appear in "Remote - Austin" / "Chicago - Remote"
# without a state name — previously slipped the US-board gate.
_US_MAJOR_CITIES = frozenset({
    "new york", "nyc", "los angeles", "chicago", "houston", "phoenix",
    "philadelphia", "san antonio", "san diego", "dallas", "austin",
    "san jose", "jacksonville", "fort worth", "columbus", "charlotte",
    "indianapolis", "seattle", "denver", "washington", "boston", "el paso",
    "nashville", "detroit", "oklahoma city", "portland", "las vegas",
    "memphis", "louisville", "baltimore", "milwaukee", "albuquerque",
    "tucson", "fresno", "sacramento", "mesa", "kansas city", "atlanta",
    "colorado springs", "miami", "raleigh", "omaha", "long beach",
    "virginia beach", "oakland", "minneapolis", "tampa", "tulsa", "arlington",
    "new orleans", "wichita", "cleveland", "bakersfield", "aurora",
    "anaheim", "honolulu", "santa ana", "riverside", "corpus christi",
    "lexington", "san francisco", "pittsburgh", "st louis", "cincinnati",
    "st paul", "greensboro", "anchorage", "plano", "lincoln", "orlando",
    "irvine", "newark", "durham", "chula vista", "toledo", "fort wayne",
    "st petersburg", "laredo", "jersey city", "chandler", "madison",
    "lubbock", "scottsdale", "reno", "buffalo", "gilbert", "glendale",
    "north las vegas", "winston salem", "chesapeake", "norfolk", "fremont",
    "garland", "irving", "hialeah", "richmond", "boise", "spokane",
    "baton rouge", "san brae", "dayton", "moreno valley", "santa clarita",
    "fayetteville", "birmingham", "rochester", "oxnard", "port st lucie",
    "grand rapids", "huntsville", "salt lake city", "yrs", "frisco",
    "amherst", "round rock", "cambridge", "tucson", "raleigh",
    "brooklyn", "manhattan", "queens", "bronx", "jersey", "waterbury",
})

_US_RESTRICTED_RE = re.compile(
    r"(?i)(?:remote\s*\(([^)]*)\)"          # "Remote (US Only)" / "Remote (San Francisco)"
    # Hyphen/sep clause: comma joins the enumeration ("Remote - Austin,
    # Berlin"), and the tempered group stops before any following "remote"
    # word so a later pin ("... Berlin. This role is Remote - Dallas.")
    # remains a SEPARATE match for finditer (Beat 120 MEDIUM-1a/2).
    r"|remote\s*[-,–/]\s*((?:(?!\bremote\b)[A-Za-z .&,])+)"
    r"|((?:(?!\bremote\b)[A-Za-z .&,])+?)\s*[-,–/]\s*remote)"  # "Maryland – Remote" / "TX - Remote" / "Austin, TX - Remote"
)

US_DOMESTIC_BOARDS = frozenset({"indeed", "glassdoor", "ziprecruiter", "monster"})

_WORLDWIDE_MARKERS = (
    "worldwide", "work from anywhere", "anywhere in the world", "anywhere in world",
    "global remote", "globally remote", "remote - global", "remote (global)",
    "remote - worldwide", "remote (worldwide)", "international remote",
    "remote international",
    "b2b", "b2b contract", "freelance", "freelance remote", "contractor",
    "independent contractor", "c2c",
    "pakistan remote", "remote in pakistan", "pakistan (remote)", "remote (pakistan)", "remote - pakistan",
    "apac remote", "asia pacific remote", "south asia remote", "remote (apac)", "apac (remote)",
    "middle east remote", "remote - middle east", "remote (middle east)", "middle east (remote)",
    "mena remote", "remote - mena", "remote (mena)", "mena (remote)",
    "gcc remote", "remote - gcc", "remote (gcc)", "gcc (remote)",
    "uae remote", "dubai remote", "saudi arabia remote", "qatar remote",
    "remote (uae)", "remote (dubai)", "uae (remote)", "dubai (remote)",
    "saudi arabia (remote)", "qatar (remote)",
)


_APAC_REGIONS = frozenset({
    "apac", "asia pacific", "asia-pacific", "south asia", "southeast asia", "east asia",
    "pakistan", "bangladesh", "sri lanka", "nepal", "bhutan", "maldives",
    "singapore", "malaysia", "philippines", "vietnam", "thailand", "indonesia", "myanmar", "cambodia", "laos", "brunei",
    "japan", "south korea", "korea", "taiwan", "china", "hong kong", "macau", "mongolia",
    "australia", "new zealand", "fiji",
    "islamabad", "lahore", "karachi", "rawalpindi", "peshawar", "faisalabad",
    "tokyo", "seoul", "taipei", "bangkok", "manila", "jakarta", "kuala lumpur",
    "dhaka", "colombo", "sydney", "melbourne",
})

_MIDDLE_EAST_REGIONS = frozenset({
    "middle east", "mena", "gcc",
    "uae", "united arab emirates", "dubai", "abu dhabi", "sharjah",
    "saudi arabia", "ksa", "riyadh", "jeddah",
    "qatar", "doha", "bahrain", "manama", "kuwait", "kuwait city", "oman", "muscat",
    "lebanon", "beirut", "jordan", "amman", "iraq", "baghdad", "egypt", "cairo",
    "turkey", "türkiye", "istanbul", "ankara", "cyprus", "yemen", "syria",
    "iran", "tehran",
    "palestine", "west bank", "gaza", "ramallah",
})

_GLOBAL_CONTRACT_QUALIFIERS = frozenset({
    "worldwide", "global", "globally", "anywhere in the world", "work from anywhere",
    "b2b", "b2b contract", "freelance", "freelancer", "contract", "contractor",
    "independent contractor", "c2c",
})

_ALLOWED_REMOTE_QUALIFIERS_PATTERN = r"\b(?:" + "|".join(
    re.escape(k) for k in sorted(
        _GLOBAL_CONTRACT_QUALIFIERS
        | set(_APAC_REGIONS)
        | set(_MIDDLE_EAST_REGIONS),
        key=len,
        reverse=True,
    )
) + r")\b"

_FOREIGN_RESTRICTED_COUNTRIES = frozenset({
    "poland", "ukraine", "lithuania", "argentina", "brazil", "canada",
    "germany", "france", "spain", "italy", "netherlands", "sweden",
    "switzerland", "ireland", "uk", "united kingdom", "great britain",
    "england", "scotland", "wales", "mexico", "colombia", "chile",
    "russia", "nigeria", "kenya", "south africa",
    "czech republic", "czechia", "romania", "hungary", "bulgaria",
    "greece", "portugal", "austria", "belgium", "finland", "norway",
    "denmark", "estonia", "latvia",
    "israel", "tel aviv", "jerusalem", "haifa",
    "japan", "tokyo", "osaka", "yokohama", "nagoya", "kyoto",
    "australia", "sydney", "melbourne", "new zealand", "china", "hong kong",
    "south korea", "seoul", "taiwan", "taipei",
    "peru", "uruguay", "ecuador", "paraguay", "venezuela", "bolivia", "cuba",
    "dominican republic", "puerto rico", "panama", "costa rica", "guatemala", "jamaica",
    "ghana", "ethiopia", "tanzania", "uganda",
    "zimbabwe", "cameroon", "mozambique",
    "india", "bangalore", "bengaluru", "mumbai", "delhi", "hyderabad", "pune", "chennai", "gurgaon", "noida",
    "latin america", "latam", "north america", "europe", "emea",
    # Beat 108: metro names whose country token is absent from the location label
    # ("Greater Rio de Janeiro" never matches \bbrazil\b — BairesDev FP).
    "rio de janeiro", "sao paulo", "são paulo", "buenos aires", "santiago",
    "mexico city", "bogota", "bogotá", "lima", "montreal", "toronto", "vancouver",
    "london", "paris", "berlin", "munich", "frankfurt", "hamburg", "amsterdam",
    "rotterdam", "madrid", "barcelona", "milan", "rome", "lisbon", "dublin",
    "zurich", "geneva", "vienna", "prague", "warsaw", "budapest", "bucharest",
    "athens", "helsinki", "stockholm", "copenhagen", "oslo", "lyon", "brussels",
})

# Beat 120 MEDIUM-1b: complete non-US-locality set for the mixed-clause skip
# in _is_us_restricted — restricted foreign countries PLUS in-scope APAC/ME
# localities (Singapore, Dubai, Riyadh, Bangkok, Kuala Lumpur, Philippines,
# ...). Any of these next to a US locality marks the clause as multi-locality
# prose, not a US residency pin. Verified disjoint from _US_STATE_NAMES /
# _US_MAJOR_CITIES / _US_STATE_ABBR (no US pin can be skipped by this set).
_NON_US_LOCALITY_TOKENS = (
    _FOREIGN_RESTRICTED_COUNTRIES | _APAC_REGIONS | _MIDDLE_EAST_REGIONS
)


def _has_strong_worldwide_eligibility(description: str | None) -> bool:
    """Beat 108: description proves *job eligibility*, not marketing reach.

    Bare "worldwide" ("impact worldwide", "clients worldwide") must NOT override
    a physical foreign location — that reopened Germany/Chile/Rio BairesDev FPs.
    Only explicit open-to-the-world phrasing qualifies (Rule 11c / B3).
    """
    d = (description or "").lower()
    # CodeRabbit CR (PR #13): country-scoped "work from anywhere in <geo>" is
    # NOT worldwide eligibility — "Work from anywhere in the UK" is UK-only and
    # must not unlock a foreign physical location. Only "in the world/globe"
    # (or a bare phrase) qualifies; the "anywhere in the world" marker below
    # also catches the world form.
    if re.search(r"work\s+from\s+anywhere\s+in\s+(?!(?:the\s+)?(?:world|globe)\b)", d):
        return False
    if any(m in d for m in (
        "work from anywhere", "anywhere in the world", "anywhere in world",
        "global remote", "globally remote", "worldwide remote",
        "open worldwide", "eligible worldwide", "candidates worldwide",
        "applicants worldwide", "no location requirement",
        "no geographic restriction", "location-agnostic", "location agnostic",
        "hire from anywhere", "hiring from anywhere",
        "100% remote worldwide", "fully remote worldwide",
        "remote worldwide role", "remote worldwide team",
        "remote worldwide position", "remote worldwide job",
        "remote worldwide opportunity", "remote, worldwide",
        "remotely worldwide", "hire remotely worldwide",
        # Beat 110 R4: verb-first forms only with a job-subject left context —
        # bare "is remote worldwide" matched marketing ("tooling is remote
        # worldwide") and re-opened foreign metros (Checker R4 MAJOR).
        "role is remote worldwide", "position is remote worldwide",
        "job is remote worldwide", "title is remote worldwide",
        "opportunity is remote worldwide", "work is remote worldwide",
        "remote worldwide is available", "remote worldwide is open",
    )):
        return True
    # Bare "remote worldwide" is marketing-speak ("remote worldwide clients")
    # and must NOT unlock a foreign physical city (Beat 110 São Paulo/Lagos FP).
    return False


def is_foreign_country_restricted(text: str) -> bool:
    """True if location ties the role to a foreign country outside Pakistan/APAC/Middle East/worldwide."""
    low = text.lower()
    if any(w in low for w in (
        "worldwide", "anywhere in the world", "work from anywhere", "global remote", "globally remote",
        "b2b", "freelance", "contractor", "c2c", "independent contractor",
    )):
        return False
    has_hard_blocked = any(re.search(rf"\b{re.escape(b)}\b", low) for b in _FOREIGN_RESTRICTED_COUNTRIES)
    in_scope_region = any(re.search(rf"\b{re.escape(r)}\b", low) for r in _APAC_REGIONS) or any(
        re.search(rf"\b{re.escape(r)}\b", low) for r in _MIDDLE_EAST_REGIONS)
    if in_scope_region and not has_hard_blocked:
        return False
    return has_hard_blocked


_FOREIGN_LANGUAGE_RESTRICTION_PATTERNS = [
    r"\bjlpt(?:\s*n[1-5])?\b",
    r"\bjapanese\b",
    r"\bn[1-5]\s+level\b",
    r"\bbusiness\s+(?:level\s+)?japanese\b",
    r"\bfluent\s+(?:in\s+)?japanese\b",
    r"\bgerman\b",
    r"\bdeutsch\b",
    r"\bfluent\s+(?:in\s+)?german\b",
    r"\bhebrew\b",
    r"\bmandarin\b",
    r"\bchinese\b",
    r"\bfluent\s+(?:in\s+)?chinese\b",
    r"\bfrench\b",
    r"\bfrançais\b",
    r"\bfluent\s+(?:in\s+)?french\b",
    r"\bspanish\b",
    r"\bespañol\b",
    r"\bfluent\s+(?:in\s+)?spanish\b",
    r"\bkorean\b",
    r"\bfluent\s+(?:in\s+)?korean\b",
    r"\bdutch\b",
    r"\bitalian\b",
    # CodeRabbit CR: bare \bpolish\b matched the English noun/verb ("UI
    # polish") — require explicit language context instead.
    r"\bpolish\s+(?:language|speaking|fluency|proficiency|level|knowledge)\b",
    r"\b(?:fluent|native|proficient|professional|business)\s+(?:in\s+)?polish\b",
    r"\bpolish\s+(?:language\s+)?(?:required|mandatory|needed|essential)\b",
    r"\b(?:fluency|proficiency)\s+(?:in\s+)?polish\b",
    r"\b(?:speak|speaking|read|write|understand)\s+polish\b",
    r"\bpolish\s*[\(\[]\s*(?:a[1-4]|b[1-5]|c[1-2])\s*[\)\]]",
    r"\bpolski\b",
    r"\brussian\b",
    r"\bnative\s+or\s+bilingual\s+in\s+(?:japanese|german|french|hebrew|chinese|korean|spanish|italian|russian)\b",
    # A6: broader local-language requirements (Arabic/Portuguese/Turkish/Thai/…)
    r"\bnative\s+(?:or\s+bilingual\s+)?arabic\b",
    r"\bfluent\s+(?:in\s+)?arabic\b",
    r"\barabic\s+(?:is\s+)?(?:a\s+)?(?:must|required|mandatory|needed|essential)\b",
    r"\b(?:must|required|needs?\s+to)\s+(?:speak|have)\s+arabic\b",
    r"\bprofessional\s+arabic\b",
    r"\b(?:fluent|native|proficient)\s+(?:in\s+)?(?:portuguese|turkish|thai|hindi|vietnamese|indonesian|bahasa|farsi|persian|urdu)\b",
    r"\b(?:portuguese|turkish|thai|hindi|vietnamese|indonesian|bahasa|farsi|persian|urdu)\s+(?:required|mandatory|native|fluent|needed|must)\b",
    r"\b(?:portuguese|turkish|thai|hindi|vietnamese|indonesian|bahasa|farsi|persian|urdu)\s+(?:is\s+)?(?:a\s+)?(?:must|required|mandatory|needed|essential)\b",
    r"\bprofi(?:ciency|cient)\s+(?:in\s+)?(?:portuguese|turkish|thai|hindi|vietnamese|indonesian|bahasa|farsi|persian|urdu)\b",
    r"\b(?:business|professional)\s+(?:level\s+)?(?:portuguese|turkish|thai|hindi|vietnamese)\b",
    r"\b(?:speak|speaking)\s+(?:fluent\s+)?(?:portuguese|turkish|thai|hindi|vietnamese|arabic)\b",
    r"\b(?:portuguese|turkish|thai|hindi|vietnamese|indonesian|bahasa|farsi|persian|urdu|arabic)\s+fluency\b",
    r"\bfluency\s+(?:in\s+)?(?:portuguese|turkish|thai|hindi|vietnamese|indonesian|bahasa|farsi|persian|urdu|arabic)\b",
    r"\b(?:arabic|portuguese|turkish|thai|hindi|vietnamese)\s+(?:language\s+)?required\b",
]


def is_language_restricted(text: str | None) -> bool:
    """True if text requires a foreign local language (Japanese, JLPT, German, Hebrew, etc.)."""
    if not text:
        return False
    low = text.lower()
    for pat in _FOREIGN_LANGUAGE_RESTRICTION_PATTERNS:
        if re.search(pat, low):
            return True
    return False


def is_hybrid_work(text: str | None) -> bool:
    """True only when text designates a hybrid *work arrangement* (RTO), not
    tech-stack "hybrid" (Hybrid Cloud, hybrid of monorepo/polyrepo, …).

    Beat 105/B1: bare `\\bhybrid\\b` anywhere killed Worldwide jobs whose body
    merely said "hybrid of X and Y". We now require an RTO-shaped signal.
    """
    if not text:
        return False
    low = text.lower()
    # Beat 111 (user): Hybrid cloud couples on-prem/private infra with public
    # cloud — not fully remote-workable for Pakistan (needs private network /
    # local rack access). Was a stack carve-out; now explicitly restricted.
    if re.search(r"\bhybrid[\s_-]+(?:cloud|multicloud|multi-cloud)\b", low):
        return True
    # Tech-stack / figure-of-speech carve-outs (hybrid cloud handled above)
    cleaned = re.sub(
        r"\bhybrid[\s_-]+(?:infrastructure|infra|"
        r"ai|architecture|models?|search|retrieval|rag|index(?:ing)?|storage|"
        r"native|approach|strategy|method|pattern|mix|modeling|modelling)\b",
        " ", low,
    )
    cleaned = re.sub(r"\bhybrid\s+of\b", " ", cleaned)
    cleaned = re.sub(r"\bhybrid(?:ly)?\s+(?:combines?|uses?|blends?|merges?)\b", " ", cleaned)
    # Positive RTO / work-arrangement signals
    if re.search(
        r"\bhybrid\s+(?:work|schedule|model|arrangement|office|remote|onsite|on-site|"
        r"role|position|setup|environment|workplace|policy|format|structure|working)\b",
        cleaned,
    ):
        return True
    if re.search(r"\b(?:work|role|position|job|schedule|model|workplace)\s+(?:is|as|:)\s*hybrid\b", cleaned):
        return True
    if re.search(r"\b(?:work|role|position|job|schedule|workplace)\s+model\s*[:：]\s*hybrid\b", cleaned):
        return True
    if re.search(r"\bhybrid\s*[-–/]\s*(?:remote|onsite|on-site|in-office)\b", cleaned):
        return True
    if re.search(r"\b(?:onsite|on-site)\s*/\s*hybrid\b|\bhybrid\s*/\s*(?:remote|onsite|on-site)\b", cleaned):
        return True
    if re.search(r"\b\d+\s*days?\s+(?:a|per)\s+week\s+(?:in|from)\s+(?:the\s+)?office\b", cleaned):
        return True
    if re.search(r"\breturn\s+to\s+office\b|\brto\b.*\bhybrid\b|\bhybrid\b.*\brto\b", cleaned):
        return True
    # Bare "hybrid" only counts with explicit office/onsite context nearby
    if re.search(r"\bhybrid\b", cleaned) and re.search(
        r"\b(?:in[- ]office|on[- ]?site|onsite|office\s+days?|office\s+attendance|commute)\b",
        cleaned,
    ):
        return True
    return False


def is_title_restricted(title: str | None) -> bool:
    """True if the job title contains restrictions that exclude worldwide/Pakistan candidates.

    Catches titles like:
      "(100% Remote - USA Only)"
      "[NYC or SF]"
      "[Full Time; 100% remote; US-only]"
      "-Onsite in Katy, Texas"
      "(US Candidates Only)"
      "(Must reside in USA)"
      "JLPT N1 Level"
      "AI Engineer - India Only" / "… Japan Only" / "… Singapore Only"   (A4)
    """
    if not title:
        return False
    if is_language_restricted(title):
        return True
    if is_hybrid_work(title):
        return True
    t = unicodedata.normalize("NFC", title.lower())
    # Underscore is a word char — normalize before every title token match
    # so "AI_Engineer_Onsite" / "ML Engineer_Hybrid" behave like spaces (R4).
    t_norm = t.replace("_", " ")
    # Localized DE/FR residency pins in titles (task-20 LOW): fail-closed, no
    # exemption machinery — titles are terse and carry no negation phrasing.
    for _pat in _LOCALIZED_RESIDENCY_PATTERNS:
        if re.search(_pat, t_norm):
            return True
    if re.search(rf"\bwohnsitz\s+(?:(?:in|innerhalb\s+der|i\.?\s*d\.?)\s*)?{_DE_LOCALITIES}\b", t_norm):
        return True
    # Foreign domestic-only restrictions in title (US, UK, Canada, Europe, Germany, Poland, LATAM)
    # A4: extend to APAC/ME foreign markets that previously slipped ("India Only", "Japan Only").
    _title_only_countries = (
        "usa?|u\\.s\\.a?|uk|united kingdom|canada|europe|germany|poland|brazil|latam|israel"
        "|india|japan|singapore|australia|china|south korea|korea|taiwan|hong kong"
        "|france|spain|italy|netherlands|sweden|switzerland|ireland|mexico|colombia"
        "|uae|saudi arabia|qatar|kuwait|bahrain|oman|egypt|turkey|nigeria|kenya"
        "|south africa|russia|ukraine|argentina|chile|peru|vietnam|thailand"
        "|malaysia|indonesia|philippines|new zealand"
    )
    if re.search(rf"\b(?:{_title_only_countries})\s*[-–]?\s*only\b", t_norm):
        return True
    if re.search(rf"\bonly\s+in\s+(?:the\s+)?(?:{_title_only_countries})\b", t_norm):
        return True
    if re.search(rf"\b(?:{_title_only_countries}|eu|european|emirates)\s+candidates?\s+only\b", t_norm):
        return True
    if re.search(r"\b(?:us|usa|u\.s\.|uk|canada|eu|european|israel)\s+based\b", t_norm):
        return True
    if re.search(
        rf"\b(?:must\s+reside\s+in|residen(?:ce|cy)\s+in)\s+(?:the\s+)?(?:{_title_only_countries})\b",
        t_norm,
    ):
        return True
    if re.search(
        rf"\bresiden(?:ce|cy)\s+(?:in\s+(?:the\s+)?(?:{_title_only_countries})\s+)?(?:is\s+)?(?:required|mandatory)\b",
        t_norm,
    ):
        return True
    if re.search(r"\[(?:[^\]]*\b)?(?:us|usa|uk|canada|europe|germany|poland|latam|israel)[- ]only(?:\b[^\]]*)?\]", t_norm):
        return True
    if re.search(r"\((?:[^)]*\b)?(?:us|usa|uk|canada|europe|germany|poland|latam|israel)[- ]only(?:\b[^)]*)?\)", t_norm):
        return True
    # Physical hub / city restrictions in title e.g. [NYC or SF], (NYC or SF), -Onsite in ...
    if re.search(r"\[(?:[^\]]*\b)?(?:nyc|sf|new york|san francisco|london|berlin|austin|seattle|boston|tel aviv|jerusalem)(?:\b[^\]]*)?\]", t_norm):
        return True
    if re.search(r"\((?:[^)]*\b)?(?:nyc|sf|new york|san francisco|london|berlin|austin|seattle|boston|tel aviv|jerusalem)(?:\b[^)]*)?\)", t_norm):
        return True
    # Bare on-site / in-office mention anywhere in the title is a physical-attendance signal.
    if re.search(r"\b(?:on-site|onsite|on site|in[- ]office|office[- ]based|office only)\b", t_norm):
        return True
    # Commission-only / sales-closer modes are not salaried engineering roles.
    if re.search(r"\bcommission\s+(?:only|-only|based)\b", t_norm):
        return True
    # Foreign employment forms a Pakistan candidate cannot exercise
    # (German "Working Student", apprenticeships, exchange/internship visas).
    if re.search(r"\bworking\s+student\b|\bwerkstudent\b|\bco[- ]op\b", t_norm):
        return True
    # Beat 110: bare hybrid work-mode token in titles ("ML Engineer (Hybrid)",
    # "ML Engineer - Hybrid", …). Hybrid Cloud already rejected via
    # is_hybrid_work(title) above (Beat 111 — stack carve-out removed).
    # Stack words (Search/RAG/AI/Models) stay allowed.
    cleaned_title = re.sub(
        r"\bhybrid[\s_-]+(?:infrastructure|infra|"
        r"ai|architecture|models?|search|retrieval|rag|index(?:ing)?|storage|"
        r"native|approach|strategy|method|pattern|mix|modeling|modelling)\b",
        " ", t_norm,
    )
    cleaned_title = re.sub(r"\bhybrid\s+of\b", " ", cleaned_title)
    if re.search(r"\bhybrid\b", cleaned_title):
        return True
    # Beat 110/111: non-engineering talent titles — only when the title is NOT an
    # engineering role (HR-tech eng titles like "Software Engineer - Recruiting
    # Solutions" must stay open). Do NOT count analyst/devops/mlops/sre here —
    # "DevOps Recruiter" / "Talent Acquisition Analyst" are still talent roles.
    # Match "engineering" too ("Engineering Manager - Recruiting Solutions").
    # Strip order (Checker B110 F2/F3):
    #   1. forward compound discipline+Recruiter, but not when "solutions" follows
    #      (underscore form "Software_Engineer_Recruiting_Solutions" must stay open)
    #   2. inverse head+separator+discipline ("Technical Recruiter - Engineering");
    #      separator REQUIRED so "Recruiting Software Engineer" stays open.
    if re.search(
        r"\b(?:technical\s+)?recruiter(?:s)?\b|\brecruit(?:er|ing|ers)\b"
        r"|\btalent[\s_]+(?:acquisition|intelligence|partner|scout|lead|specialist)\b"
        r"|\bheadhunter\b",
        t_norm,
    ):
        t_eng = t_norm
        if "solution" not in t_norm:
            t_eng = re.sub(
                r"\b(?:engineering|engineers?|developers?|architects?|scientists?|"
                r"researchers?|programmers?)\s+(?:technical\s+)?(?:recruiter|recruiting)\b",
                " ", t_norm,
            )
        t_eng = re.sub(
            r"\b(?:technical\s+)?(?:recruiter(?:s)?|recruit(?:er|ing|ers)"
            r"|talent[\s_]+(?:acquisition|intelligence|partner|scout|lead|specialist)"
            r"|headhunter)\s*[-–,:/]\s*"
            r"(?:\w+\s+){0,5}(?:engineering|engineers?|developers?|architects?|"
            r"scientists?|researchers?|programmers?)\b",
            " ", t_eng,
        )
        if not re.search(
            r"\b(?:engineer(?:ing)?|developer|architect|scientist|researcher|programmer)\b",
            t_eng,
        ):
            return True
    return False


# A5: residency/"X only" phrasings generalized off the country tables.
# Pakistan is intentionally EXCLUDED — Pakistan residency is in-scope for this loop.
_RESIDENCY_BLOCK_COUNTRIES = tuple(sorted(
    (
        _FOREIGN_RESTRICTED_COUNTRIES
        | {
            "singapore", "malaysia", "thailand", "vietnam", "indonesia",
            "philippines", "saudi arabia", "saudi", "uae", "united arab emirates",
            "qatar", "kuwait", "bahrain", "oman", "egypt", "turkey", "türkiye",
            "dubai", "riyadh", "doha", "istanbul", "abu dhabi",
            "japan", "south korea", "china", "taiwan", "hong kong",
            "australia", "new zealand", "india",
        }
    ) - {"pakistan"},
    key=len,
    reverse=True,
))
_RESIDENCY_COUNTRY_ALT = "|".join(re.escape(c) for c in _RESIDENCY_BLOCK_COUNTRIES)

_DESCRIPTION_RESTRICTION_PATTERNS = [
    # US / North America / Europe / Foreign geographic or work authorization restrictions
    r"\bmust\s+reside\s+in\s+(?:the\s+)?(?:us|usa|united states|north america|canada|uk|europe|germany|latin america|poland|japan|singapore|saudi|uae|australia|israel)\b",
    r"\bmust\s+be\s+in\s+the\s+(?:us|usa|united states|uk|europe|canada|japan|australia|israel)\b",
    r"\bmust\s+be\s+located\s+in\s+(?:the\s+)?(?:us|usa|united states|north america|canada|uk|europe|germany|latin america|poland|japan|singapore|saudi|uae|australia|israel)\b",
    r"\bresiden(?:ce|cy)\s+(?:in\s+(?:the\s+)?(?:us|usa|united states|uk|canada|eu|europe|germany|france|poland|spain|italy|japan|singapore|australia|israel)\s+)?(?:is\s+)?(?:required|mandatory|essential|erforderlich)\b",
    r"\bresiden(?:ce|cy)\s+in\s+(?:the\s+)?(?:us|usa|united states|uk|canada|eu|europe|germany|france|poland|spain|italy|japan|singapore|australia|israel)\b",
    r"\b(?:us|usa)\s+(?:citizenship|citizen|resident|residency|based|candidates?)\s+only\b",
    r"\b(?:us|usa|u\.s\.)\s+citizens?\s+or\s+permanent\s+residents?\b",
    r"\b(?:uk|canada|eu|european)\s+citizens?\s+or\s+permanent\s+residents?\b",
    r"\b(?:uk|canada|eu|european)\s+(?:candidates?|residen(?:ts?|cy)|based)\s+only\b",
    # Beat 110: "UK based candidates only" (word order = based + candidates + only)
    r"\b(?:uk|united\s+kingdom|canada|eu|european)\s+based\s+(?:candidates?|engineers?|developers?|applicants?)\s+only\b",
    # Beat 110: ITAR / export-control "US person(s)/personnel" — matched on the
    # ORIGINAL case below (lowercase "us person" is the English pronoun).
    r"\b(?:must\s+be\s+(?:a\s+)?)(?:u\.?s\.?)\s*persons?\b",
    r"\b(?:u\.?s\.?)\s*citizen(?:s|ship)?\s+only\b",
    r"\b(?:japan|singapore|saudi|uae|australia|israel)\s+(?:residen(?:ts?|cy)|citizens?|based)\s+only\b",
    r"\bgreen\s+card(?:\s+holder)?\b",
    r"\b(?:uk|united\s+kingdom)\s+right\s+to\s+work\b",
    r"\bright\s+to\s+work\s+in\s+(?:the\s+)?(?:uk|united\s+kingdom|eu|london|canada|japan|singapore|australia)\b",
    r"\b(?:eu|european)\s+(?:resident|residency|work|working)\s+(?:permit|right|authoriz(?:e|a)tion)\b",
    r"\bwe\s+(?:are\s+unable\s+to|cannot|do\s+not)\s+(?:sponsor|hire\s+outside|hire\s+internationally)\b",
    r"\b(?:must\s+be\s+)?(?:legally\s+)?authorized\s+to\s+work\s+in\s+(?:the\s+)?(?:us|usa|united states|uk|canada|eu|japan|singapore|australia)\b",
    r"\bable\s+to\s+work\s+in\s+(?:the\s+)?(?:us|usa|united states|uk|canada|eu|japan|singapore|australia)\b",
    r"\beligible\s+to\s+work\s+in\s+(?:the\s+)?(?:us|usa|united states|uk|canada|eu|japan|singapore|australia)\b",
    r"\b(?:us|u\.s\.|usa)\s+work\s+authorization\b",
    r"\bwork\s+authorization\s+in\s+(?:the\s+)?(?:us|usa|united states|uk|canada|eu|japan|singapore|australia)\b",
    r"\b(?:us|u\.s\.)\s+work\s+permit\b",
    r"\b(?:no\s+c2c|w-?2\s+only|w2\s+candidates?)\b",
    r"\bsecurity\s+clearance\s+required\b",
    r"\bactive\s+secret\s+clearance\b",
    # A8: timezone exclusions that cannot be accommodated from Pakistan (UTC+5)
    r"\bwithin\s+\d+\s*(?:[-–to]+\s*\d*\s*)?hours?\s+of\s+(?:london|uk|gmt|cet|bst|est|cst|mst|pst)\b",
    r"\bmust\s+be\s+based\s+in\s+(?:cet|bst|gmt|est|cst|mst|pst)\b",
    r"\bus\s+(?:eastern|central|pacific|mountain)\b",
    # CodeRabbit CR: exclude "Asia Pacific time"/"APAC / Pacific time" —
    # in-scope APAC roles must not be dropped as US-timezone restrictions.
    # Fixed-width lookbehinds only (Python): "asia[ -]", "apac ", "apac/",
    # "apac / ", "apac - ".
    r"\b(?<!asia[\s-])(?<!apac\s)(?<!apac/)(?<!apac\s/\s)(?<!apac\s-\s)(?:eastern|central|pacific|mountain)\s+(?:time|hours?|zone)\b",
    r"\b(?:est|cst|mst|pst)\s+(?:time|hours?|zone|business)\b",
    # Beat 110: zone trails the phrase ("business hours EST") — searched on
    # lowercased text, so patterns must be lowercase.
    r"\bbusiness\s+hours?\s+(?:est|cst|mst|pst|et|ct|mt|pt)\b",
    r"\b(?:eastern|central|pacific|mountain)\s*\(\s*(?:est|cst|mst|pst)\s*\)",
    r"\bmust\s+overlap\b",
    r"\b\d+\s+hours?\s+(?:of\s+)?(?:timezone\s+)?overlap\b",
    # Regional remote restrictions (e.g. "fully remote role in EU", "remote in US only")
    r"\b(?:fully\s+remote|remote|wfh)\s+(?:role|job|position)?\s*(?:in|within)\s+(?:the\s+)?(?:us|usa|united states|uk|eu|europe|canada|germany|india|latin america)\b",
    # Onsite requirements
    r"\b(?:1|2|3|4)\s*days\s+(?:a|per)\s+week\s+(?:in|from)\s+(?:the\s+)?office",
    r"\b(?:onsite|on-site)\b.*(?:in\s+\w+|office\b)",
    r"\brelocation\s+(?:required|assistance\s+to)\b",
    r"\bmust\s+be\s+able\s+to\s+commute\b",
    # B2: Israel roles blocked only with residency/geo pins — not market mentions
    # ("we sell to teams in Israel" must not kill a Worldwide role).
    r"\b(?:based\s+in|reside(?:s|nt)?\s+in|resident\s+of|located\s+in|office\s+in)\s+(?:israel|tel\s+aviv|jerusalem|haifa)\b",
    r"\b(?:israeli?|tel\s+aviv)\s+(?:residents?|based|citizens?|nationals?|only|work\s+permit|office|location)\b",
    r"\b(?:must|need(?:ing)?\s+to|required\s+to)\s+(?:be\s+)?(?:based|reside|live|work)\s+in\s+(?:israel|tel\s+aviv|jerusalem|haifa)\b",
    r"\b(?:israel|tel\s+aviv|jerusalem|haifa)\s*[-–]?\s*only\b",
    r"\bright\s+to\s+work\s+in\s+israel\b",
    r"\bwork\s+authorization\s+in\s+israel\b",
    # A5: generalized "… only" / "candidates in X only" residency pins (non-Pakistan)
    rf"\b(?:only|restricted\s+to)\s+(?:candidates\s+)?(?:based\s+)?in\s+(?:the\s+)?(?:{_RESIDENCY_COUNTRY_ALT})\b",
    rf"\bcandidates\s+(?:in|based\s+in)\s+(?:the\s+)?(?:{_RESIDENCY_COUNTRY_ALT})\s+only\b",
    rf"\bopen\s+to\s+candidates\s+in\s+(?:the\s+)?(?:{_RESIDENCY_COUNTRY_ALT})\s+only\b",
    rf"\bonly\s+candidates\s+(?:based\s+)?in\s+(?:the\s+)?(?:{_RESIDENCY_COUNTRY_ALT})\b",
    rf"\b(?:{_RESIDENCY_COUNTRY_ALT})\s+(?:residents?|nationals?|based|citizens?)\s+only\b",
    rf"\b(?:must|required)\s+(?:to\s+)?be\s+(?:based|located|residing)\s+in\s+(?:the\s+)?(?:{_RESIDENCY_COUNTRY_ALT})\b",
    # "Applicants in Germany only" / "in India only" / "based in Japan only"
    rf"\b(?:applicants?|candidates?|individuals?|engineers?)\s+in\s+(?:the\s+)?(?:{_RESIDENCY_COUNTRY_ALT})\s+only\b",
    rf"\bin\s+(?:the\s+)?(?:{_RESIDENCY_COUNTRY_ALT})\s+only\b",
    rf"\bbased\s+in\s+(?:the\s+)?(?:{_RESIDENCY_COUNTRY_ALT})\s+only\b",
    rf"\b(?:must|required)\s+be\s+based\s+in\s+(?:the\s+)?(?:{_RESIDENCY_COUNTRY_ALT})\b",
    # Beat 110: soft residency preference still pins geography ("Based in India preferred")
    rf"\bbased\s+in\s+(?:the\s+)?(?:{_RESIDENCY_COUNTRY_ALT})\s+preferred\b",
    rf"\b(?:reside|residing|living|located)\s+in\s+(?:the\s+)?(?:{_RESIDENCY_COUNTRY_ALT})\s+preferred\b",
    rf"\bprefer(?:ably)?\s+(?:based|located|living)\s+in\s+(?:the\s+)?(?:{_RESIDENCY_COUNTRY_ALT})\b",
    # Beat 122 MEDIUM-B: bare foreign geography pins the country-alt forms all
    # miss — "Remote - Berlin only", "Remote - Warsaw only", "Germany only".
    # The hyphen form is SOLE-locality only: an enumeration mixing in another
    # locality ("Remote - France vs Texas", "Remote - UK or California") is a
    # mixed clause and stays open (recall-first, pinned in test_pr13_*).
    rf"\bremote\s*[-–,]\s*(?:{_RESIDENCY_COUNTRY_ALT})\b(?!\s+(?:and|or|vs)\b|\s*(?:,|&))",
    # ...unless BOTH localities of the enumeration are foreign
    # ("Remote - Berlin, Germany" / "Remote - Warsaw and Berlin").
    rf"\bremote\s*[-–,]\s*(?:{_RESIDENCY_COUNTRY_ALT})\s*(?:,|and|or|vs)\s+(?:{_RESIDENCY_COUNTRY_ALT})\b",
    rf"\b(?:{_RESIDENCY_COUNTRY_ALT})\s+only\b",
]

# ── Phase 3 (A3): localized DE/FR residency pins ────────────────────────────
# Searched on lowercased text (accents preserved by .lower()). Kept OUT of the
# main list because these carry per-sentence polarity (M3): a match restricts
# unless its sentence carries an explicit exemption (ohne Wohnsitz /
# nicht erforderlich / non requise / without residence …).

_DE_LOCALITIES = (
    r"(?:deutschland|germany|bundesrepublik(?:\s+deutschland)?|berlin|hamburg|"
    r"münchen|munich|frankfurt|köln|cologne|stuttgart|düsseldorf|leipzig|dresden|"
    r"nrw|nordrhein-westfalen|bayern|bavaria|hessen|baden-württemberg)"
)

_LOCALIZED_RESIDENCY_PATTERNS = [
    # DE: Wohnsitz / Wohnort / wohnen / Ansässigkeit / Aufenthalt
    # Preposition form ("Wohnsitz in Deutschland")
    rf"\bwohnsitz\s+(?:in|innerhalb\s+der|i\.?\s*d\.?)\s+{_DE_LOCALITIES}\b",
    # Preposition-optional form ("Wohnsitz Deutschland") requires requirement phrasing
    # to avoid false positives on questionnaire prompts or company location mentions (Beat 151 LOW2).
    rf"\bwohnsitz\s+{_DE_LOCALITIES}\b[^.!?\n]{{0,40}}\b(?:erforderlich|pflicht|voraussetzung|zwingend|nötig|benötigt|notwendig|required|must)\b",
    rf"\b(?:erforderlich|pflicht|voraussetzung|zwingend|nötig|benötigt|notwendig|required|must)\b[^.!?\n]{{0,40}}\bwohnsitz\s+{_DE_LOCALITIES}\b",
    rf"\bmit\s+wohnsitz\s+(?:(?:in|innerhalb\s+der|i\.?\s*d\.?)\s*)?{_DE_LOCALITIES}\b",
    rf"\bohne\s+wohnsitz\s+(?:(?:in|innerhalb\s+der|i\.?\s*d\.?)\s*)?{_DE_LOCALITIES}\b",
    rf"\bwohnort\b[^.!?\n]{{0,40}}\b(?:in\s+)?{_DE_LOCALITIES}\b",
    rf"\b(?:in\s+{_DE_LOCALITIES}\s+wohnen|wohnen\s+in\s+{_DE_LOCALITIES})\b",
    # M2: country/locality required inside the SAME muss-living clause; `[^.!?\n]`
    # never bridges sentences. Umlaut forms: muss/musst/müssen/musste/mussten/müsste.
    # B2: includes major German cities/states (Berlin, Hamburg, NRW).
    # Round-2 (M3): living verbs extended to ansässig/leben for EN parity.
    rf"\bm(?:u|ü)(?:ss|ß)(?:t|en|te|ten|st|sten)?\b[^.!?\n]{{0,60}}\b(?:in\s+)?{_DE_LOCALITIES}\b[^.!?\n]{{0,40}}\b(?:wohnen|ansässig|leben)\b",
    # Post-verb locality: "Bewerber müssen wohnen in Deutschland"
    rf"\bm(?:u|ü)(?:ss|ß)(?:t|en|te|ten|st|sten)?\b[^.!?\n]{{0,60}}\b(?:wohnen|ansässig|leben)\b[^.!?\n]{{0,40}}\b(?:in\s+)?{_DE_LOCALITIES}\b",
    rf"\bansässig(?:keit|en)?\s+(?:in\s+)?{_DE_LOCALITIES}\b",
    r"\baufenthaltserlaubnis\s+(?:für|in)\s+(?:deutschland|germany)\b",
    # FR: résider / résidant / résidence / résidents / basé / domiciliation
    r"\brésid(?:ant|erez|er)\s+en\s+(?:france|europe)\b",
    r"\brésidence\s+(?:en|dans\s+l'|dans\s+le|dans\s+la|dans)?\s*(?:france|europe|union\s+européenne|ue)\b",
    r"\brésident(?:e)?s?\s+en\s+(?:france|europe)\b",
    r"\bbas[eé]e?s?\s+en\s+france\b",
    r"\bdomicilié(?:e)?\s+en\s+france\b",
    r"\bdomiciliation\s+en\s+france\b",
]

# Clauses are separated by punctuation OR coordinating/adversative conjunctions (M2).
_LOCALIZED_CLAUSE_SPLIT = re.compile(
    r"[,;:—–()\[\]]+|\b(?:und|aber|oder|sondern|mais|et|ou|and|or|but)\b",
    re.IGNORECASE,
)

# M1: client/partner-HQ skip ONLY applies to company/client headquarters mentions
# directly preceding 'basé(e) en France' ("Notre client, basé en France, recrute…").
# It must NEVER suppress personal candidate residency pins like Wohnsitz or Résidant.
_CLIENT_HQ_SKIP = re.compile(
    r"\b(?:notre\s+client|notre\s+entreprise|la\s+soci[ée]t[ée]|notre\s+partenaire|our\s+client|our\s+company)\b[^.!?\n]{0,25}\s*$",
    re.IGNORECASE,
)

_LOCALIZED_RESIDENCY_EXEMPT = re.compile(
    r"(?i)"
    # DE open-neg (muss/soll/mochte stems, zwingend, pflicht)
    r"\bnicht\b[^.!?\n]{0,15}\b(?:erforderlich|benötigt|nötig|vorgeschrieben|zwingend|pflicht)\b"
    r"|\bkeine?\s+pflicht\b"
    r"|\bm(?:u|ü)(?:ss|ß)(?:t|en|te|ten|st|sten)?\s+nicht\b"
    r"|\bohne\s+(?:[a-zäöüß]+\s+){0,2}wohnsitz\b"
    r"|\bohne\s+ansässigkeit\b"
    r"|\bkein(?:e|er|en)?\s+(?:wohnsitz|ansässigkeit)\b"
    # possibility, not requirement ("in Deutschland wohnen möglich", "wohnen ist möglich")
    r"|\b(?:wohnen|leben)\s+(?:ist\s+)?(?:möglich|possible)\b"
    r"|\b(?:wohnsitz|ansässigkeit)\b[^.!?\n]{0,30}\bmöglich\b"
    r"|\bmöglich\s+für\s+(?:alle\b|kandidaten\b|bewerber\b)"
    r"|\b(?:wohnort|wohnsitz)\s+(?:frei|free)\b"
    # "you may live…" permission
    r"|\bk(?:a|ä|ö|o)nn(?:st|en)?\b[^.!?\n]{0,60}\b(?:wohnen|leben)\b"
    # FR open-neg (non requis, non/pas obligatoire, pas besoin de, sans résidence)
    r"|\bnon\s+requi(?:s|se|ses)\b"
    r"|\b(?:non|pas)\s+obligatoire\b"
    r"|n'est\s+pas\s+(?:requis|requise|nécessaire|obligatoire)\b"
    r"|\bpas\s+besoin\s+de\b"
    r"|\bsans\s+(?:résidence|résider|domicile)\b"
    # EN equivalents (CodeRabbit: "residence not required" / "without residence")
    r"|\b(?:residence|residency|domicile)\s+not\s+required\b"
    r"|\bno\s+(?:residence|residency)\s+requirement\b"
    r"|\bwithout\s+(?:a\s+)?(?:residence|residency)\b"
)


def is_description_restricted(description: str | None) -> bool:
    """True if description contains geographic/residency/onsite restrictions excluding Pakistan remote."""
    if not description:
        return False
    if is_language_restricted(description):
        return True
    if is_hybrid_work(description):
        return True
    # NFC first: `.lower()` still raises AttributeError on non-str (parity with
    # main), then NFD accents (Résident = e+U+0301) compose for every pattern.
    low = unicodedata.normalize("NFC", description.lower())
    description = unicodedata.normalize("NFC", description)
    for pattern in _DESCRIPTION_RESTRICTION_PATTERNS:
        if re.search(pattern, low):
            return True
    # A3 localized pins: clause-anchored polarity (round-2 M1/M2).
    # Newlines are layout, not sentence breaks → collapse before matching so
    # line-straddling pins ("Der Wohnort\nmuss in Deutschland sein") still hit
    # (LOW2), while `.!?` still separates sentences for polarity.
    loc = re.sub(r"[ \t]*[\r\n]+[ \t]*", " ", low)
    _sent_ends = [m.end() for m in re.finditer(r"[.!?]", loc)]
    for pattern in _LOCALIZED_RESIDENCY_PATTERNS:
        for m in re.finditer(pattern, loc):
            # sentence span containing the match (matches never contain .!?)
            s_start = 0
            s_end = len(loc)
            for e in _sent_ends:
                if e <= m.start():
                    s_start = e
                elif e >= m.end():
                    s_end = e
                    break
            sent = loc[s_start:s_end]
            # clause region around the FULL match span (clause seps , ; : — – ( ) [ ] or conjunctions):
            # a pin whose internal gap crosses a sep ("wohnort frei — auch in
            # Deutschland wohnen") is judged against every clause it touches;
            # pins that end before the sep keep clause-local polarity (M1/M2).
            rel_start, rel_end = m.start() - s_start, m.end() - s_start
            c_start, c_end = 0, len(sent)
            for cm in _LOCALIZED_CLAUSE_SPLIT.finditer(sent):
                if cm.end() <= rel_start:
                    c_start = cm.end()
                elif cm.start() >= rel_end:
                    c_end = cm.start()
                    break
            # M1: only skip client/partner HQ location for 'basé(e) en France'
            if m.group(0).startswith("bas") and _CLIENT_HQ_SKIP.search(
                loc[max(0, m.start() - 60) : m.start()]
            ):
                continue
            if _LOCALIZED_RESIDENCY_EXEMPT.search(sent[c_start:c_end]):
                continue  # clause this pin touches explicitly negated → open
            return True
    # "100% Remote - USA Only" / "US-only" must only match the UPPERCASE abbreviation,
    # never the lowercase pronoun "us" (e.g. "gives us only ..."). Match on the original case.
    if re.search(r"\b(?i:100%\s+remote\s*[-–]?\s*)?(?:US|USA|U\.S\.)\s*[-–]?\s*(?i:only)\b", description):
        return True
    # Beat 110 R4: ITAR "US person(s)/personnel" and "US business hours" —
    # US token case-sensitive (pronoun protection); trailing words case-insensitive.
    # Polarity is evaluated PER SENTENCE (Checker R4 MAJOR): unrelated negation in
    # another sentence ("No agencies please.") must not suppress a later hard pin
    # ("US PERSONS ONLY."). A hard "only" in the same sentence always restricts.
    # U\.S(?:\.A)?\. covers both "U.S." and "U.S.A." (bare U\.S\. missed U.S.A.).
    _us_tok = r"(?:US|USA|U\.S(?:\.A)?\.)"
    if re.search(rf"\b{_us_tok}\s*(?i:persons?|personnel)\b", description) or re.search(
        rf"\b{_us_tok}\s+(?i:business\s+hours?)\b", description
    ):
        _us_open_neg = re.compile(
            r"(?i)"
            r"\bnot\s+(?:a\s+)?(?:required|requirement|mandatory|necessary|needed)\b"
            r"|\bisn't\s+required\b|\baren't\s+required\b"
            r"|\bshall\s+not\s+be\s+required\b|\bnot\s+mandatory\b"
            r"|\bno\s+(?:us\s+|u\.s\.(?:\.a)?\s*)?(?:persons?|citizenship|requirement)\b"
            r"|\bdoes\s+not\s+require\b|\bdo(?:es)?\s+not\s+require\b|\bdon't\s+require\b"
            r"|\brequirement\s*:\s*none\b|\brequirement\s+is\s+none\b|\bnone\s+required\b"
            r"|\bwithout\s+(?:a\s+)?(?:us\s+|u\.s\.(?:\.a)?\s*)?persons?\b"
            # Consume full "non-US persons" so strip does not leave a bare
            # "persons only" that would trip the persons-ONLY pin (R4 residual).
            r"|\bnon[-\s]?(?:us|u\.s\.(?:\.a)?)\s+(?:persons?|personnel)\b"
            r"|\bnon[-\s]?(?:us|u\.s\.(?:\.a)?)\b"
        )
        _us_hard = re.compile(
            r"(?i)\bonly\b|\bmust\s+(?:be|work|have|possess)\b"
            r"|\bis\s+required\b|\bare\s+required\b|\brequires?\b"
        )
        _restricted_any = False
        # Protect U.S. / U.S.A. periods so the sentence splitter does not cut
        # "U.S. persons only" into "U.S." + "persons only" (R4 regression).
        # Pattern is U + "." + S + optional("."+A) + "."  — not U\.S\.A?\. which
        # demanded a third period after a bare "U.S.".
        _protected = re.sub(
            r"\bU\.S(?:\.A)?\.", lambda m: m.group(0).replace(".", "\x01"), description, flags=re.I
        )
        for _seg in re.split(r"(?<=[.!?])\s+|\n+", _protected):
            _seg = _seg.replace("\x01", ".")
            if not (
                re.search(rf"\b{_us_tok}\s*(?i:persons?|personnel)\b", _seg)
                or re.search(rf"\b{_us_tok}\s+(?i:business\s+hours?)\b", _seg)
            ):
                continue
            # Beat 111 F1: open-neg must not suppress a DIFFERENT hard pin in
            # the same clause ("…not required; must work US business hours").
            # Strip open-neg phrases first, then look for an independent hard
            # pin on the remainder — so "does not require US person" stays open
            # (bare `require` was the open-neg itself, not a second pin).
            # After strip: only count a persons-ONLY pin (not bare "only",
            # which survives inside "not only" / "the only thing").
            if re.search(_us_open_neg, _seg):
                _rest = _us_open_neg.sub(" ", _seg)
                _not_only = re.search(r"(?i)\bnot\s+only\b", _rest)
                # US token REQUIRED on the pin: optional US made "Open to
                # non-US persons only" restrict after stripping non-US.
                if not _not_only and re.search(
                    r"(?i)\b(?:us|usa|u\.s(?:\.a)?\.?)\s+persons?\s+only\b"
                    r"|\bonly\s+(?:us|usa|u\.s(?:\.a)?\.?)\s+persons?\b",
                    _rest,
                ):
                    return True
                if re.search(
                    r"(?i)\bmust\s+(?:be|work|have|possess)\b"
                    r"|\bis\s+required\b|\bare\s+required\b|\brequires?\b",
                    _rest,
                ):
                    return True
                continue
            # No open-neg: hard pin or bare mention → restrict.
            if re.search(r"(?i)\bonly\b", _seg) and not re.search(
                r"(?i)\bnot\s+only\b", _seg
            ):
                return True
            if re.search(_us_hard, _seg):
                return True
            # Bare US person/hours mention with no open-negation → restrict
            # (original fail-closed behavior; pronouns never reach here — US token).
            _restricted_any = True
        return _restricted_any
    return False


def _usa_token_polarity_open(text: str) -> bool:
    """True when every sentence with a bare USA/U.S.A./United States token is
    open-negated (R4 polarity) and has no hard pin.

    Shared with is_description_restricted's US-person block so daily
    (_is_us_restricted) and digest stay in lockstep on "not required" forms.
    """
    _open_neg = re.compile(
        r"(?i)"
        r"\bnot\s+(?:a\s+)?(?:required|requirement|mandatory|necessary|needed)\b"
        r"|\bisn't\s+required\b|\baren't\s+required\b"
        r"|\bshall\s+not\s+be\s+required\b|\bnot\s+mandatory\b"
        r"|\bno\s+(?:us\s+|u\.s\.(?:\.a)?\s*)?(?:persons?|citizenship|requirement)\b"
        r"|\bdoes\s+not\s+require\b|\bdo(?:es)?\s+not\s+require\b|\bdon't\s+require\b"
        r"|\brequirement\s*:\s*none\b|\brequirement\s+is\s+none\b|\bnone\s+required\b"
        r"|\bwithout\s+(?:a\s+)?(?:us\s+|u\.s\.(?:\.a)?\s*)?persons?\b"
        r"|\bnon[-\s]?(?:us|u\.s\.(?:\.a)?)\b"
    )
    _hard = re.compile(
        r"(?i)\bonly\b|\bmust\s+(?:be|work|have|possess)\b"
        r"|\bis\s+required\b|\bare\s+required\b|\brequires?\b"
    )
    _usa_tok = re.compile(r"(?i)\b(?:usa|united states(?:\s+of\s+america)?|u\.s\.a)\b")
    _protected = re.sub(
        r"\bU\.S(?:\.A)?\.", lambda m: m.group(0).replace(".", "\x01"), text, flags=re.I
    )
    _found = False
    for _seg in re.split(r"(?<=[.!?])\s+|\n+", _protected):
        _seg = _seg.replace("\x01", ".")
        if not _usa_tok.search(_seg):
            continue
        _found = True
        if re.search(r"(?i)\bonly\b", _seg) and not re.search(r"(?i)\bnot\s+only\b", _seg):
            return False
        if _hard.search(_seg):
            return False
        if not _open_neg.search(_seg):
            return False
    return _found


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
    # Beat 122 MEDIUM-A: the target-marker exception ("worldwide", "apac", ...)
    # used to sit HERE and short-circuit EVERYTHING — hard US residency pins
    # ("must be based in Austin", "Remote - Dallas only", "in NY only") were
    # silently bypassed on any marker'd text (Rule 11 violation). It now runs
    # only AFTER all hard-pin detection, at the bottom of this function.
    # Explicit disambiguation for Remote, Oregon (Coos County, OR, ZIP 97458)
    if (re.search(r"\bremote\s*,\s*(?:or|oregon)\b", low)
            or re.search(r"\bremote\s+(?:or|oregon)\b", low)
            or re.search(r"\bcoos\s+county\b", low)
            or re.search(r"\bremote\b.*\b97458\b", low)):
        return True

    # Tokens / phrases indicating USA restriction.
    # R4 residual: bare USA/U.S.A./United States token respects sentence-scoped
    # polarity — "U.S.A. person status is not required" is open (is_description_restricted
    # already agrees); geo pins and hard "only"/must forms still restrict.
    if re.search(r"\b(?:usa|united states(?:\s+of\s+america)?|u\.s\.a)\b", low):
        if not _usa_token_polarity_open(text):
            return True
    if re.search(r"\b(?:us|u\.s\.)\s*(?:only|based|resident|citizen|candidates?)\b", low):
        return True

    # PR #13 residual: state names / postal abbrevs restrict only inside
    # residency-pin constructions — never on casual prose ("Offices in New
    # York, London" on a Worldwide role must stay open). Short location
    # strings ("Remote - Texas", "TX - Remote") still hit via
    # _US_RESTRICTED_RE's group-walk below; whole-string location tokens are
    # is_worldwide_remote's job (single_low in _US_STATE_NAMES there).
    for state in _US_STATE_NAMES:
        s = re.escape(state)
        if re.search(
            rf"(?i)(?:\bbased\s+in\s+{s}\b|\blocated\s+in\s+{s}\b"
            rf"|\breside(?:s|ing)?\s+in\s+{s}\b|\bliving\s+in\s+{s}\b"
            rf"|\bmust\s+be\s+(?:based\s+|located\s+)?in\s+{s}\b"
            rf"|\bremote\s+(?:in|at)\s+{s}\b"
            rf"|\b{s}\s+only\b|\b{s}[\s-]+based\b)",
            low,
        ):
            return True

    # Postal abbreviation: pin forms only ("based in TX", "must be in CA",
    # "in TX only"). Comma/remote forms ("Remote, TX", "TX - Remote") are
    # already covered by _US_RESTRICTED_RE's group-walk. Bare "Austin, TX"
    # in office-prose must NOT restrict a Worldwide description.
    # CodeRabbit CR: walk EVERY match on the ORIGINAL text and accept only
    # UPPERCASE captures — lowercase English words ("or" in "located in or
    # around Karachi", "an" in "based in an async culture") must never hit
    # Oregon/…, and a later real pin ("must be based in TX") must not be
    # masked by an earlier incidental first match (re.search → finditer).
    # (?i) keeps the construction words case-insensitive; isupper() on the
    # captured original substring enforces the state-abbr case convention.
    for m_abbr in re.finditer(
        rf"(?i)(?:based|located|reside(?:s|ing)?|living)\s+in\s+([a-z]{{2}})\b"
        rf"|\bmust\s+be\s+(?:based\s+)?in\s+([a-z]{{2}})\b"
        rf"|\bin\s+([a-z]{{2}})\s+only\b",
        text,
    ):
        for g in m_abbr.groups():
            if g and g.isupper() and g.lower() in _US_STATE_ABBR:
                return True

    # Beat 120 MEDIUM-2: walk EVERY regex match (finditer, not search) —
    # a mixed clause skipped below must NOT mask a later US-only pin
    # ("Remote - Austin and Berlin; Remote - Dallas" must still restrict).
    for m in _US_RESTRICTED_RE.finditer(text):
        for grp in m.groups():
            if not grp:
                continue
            grp_low = grp.lower().strip()
            if re.search(r"\b(us|usa|united states|u\.s\.a?)\b", grp_low):
                return True
            if any(phrase in grp_low for phrase in ("us only", "usa only", "u.s. only", "u.s.a. only", "united states only", "u.s.")):
                return True
            # PR #13 human-gate fix (a) + Beat 120 MEDIUM-1b: enumeration/
            # locality-aware group-walk. A captured clause naming ANY non-US
            # locality (restricted foreign country OR in-scope APAC/ME place —
            # "Remote - Austin and Berlin", "Remote (New York, London)",
            # "Remote - Austin, Berlin", "Remote - Austin and Singapore")
            # alongside a US one is multi-locality prose on a Worldwide role —
            # NOT a US residency pin. US-only qualifiers ("Remote - Austin",
            # "Remote (New York)", "Remote - US Only") still restrict;
            # USA/US-person tokens above stay unconditional.
            if any(re.search(rf"\b{re.escape(f)}\b", grp_low)
                   for f in _NON_US_LOCALITY_TOKENS):
                continue
            # PR #13 residual MEDIUM: the hyphen alt captures the whole trailing
            # clause ("Remote-first hubs in Austin and Berlin" → group includes
            # a city). Geo walks only fire on SHORT location qualifiers
            # ("Austin", "US Only", "New York", "TX") — never on prose (≤4
            # words); otherwise Worldwide descriptions naming a US office drop.
            if len(grp_low.split()) > 4:
                continue
            two_letter_words = set(re.findall(r"\b[a-z]{2}\b", grp_low))
            if any(w in _US_STATE_ABBR for w in two_letter_words):
                return True
            if any(re.search(rf"\b{re.escape(name)}\b", grp_low) for name in _US_STATE_NAMES):
                return True
            if any(re.search(rf"\b{re.escape(city)}\b", grp_low) for city in _US_MAJOR_CITIES):
                return True
    # A3 / PR #13 finding 1: a US city restricts only inside a residency-pin
    # construction — never via casual co-occurrence with "remote" anywhere in
    # the text. "Remote - Austin" / "Chicago - Remote" already match via
    # _US_RESTRICTED_RE above; here we cover "Remote in Austin", "Remote
    # Austin", "based in Austin", "Austin-based", "Austin only". Prose like
    # "hubs in Austin" / "offices in Seattle" on a Worldwide description must
    # stay open (Rule 11(b) recall — reviewer repro on PR #13).
    for city in _US_MAJOR_CITIES:
        c = re.escape(city)
        if re.search(
            rf"(?i)(?:\bremote\s+(?:in|at)\s+{c}\b"
            rf"|\bremote\s+{c}\b"
            rf"|\bremote\s+(?:role|job|position|work|team)\s+in\s+{c}\b"
            rf"|\bbased\s+in\s+{c}\b|\blocated\s+in\s+{c}\b"
            rf"|\breside(?:s|ing)?\s+in\s+{c}\b|\bliving\s+in\s+{c}\b"
            rf"|\bmust\s+be\s+(?:based\s+)?in\s+{c}\b"
            rf"|\b{c}\s+only\b|\b{c}[\s-]+based\b)",
            low,
        ):
            return True
    # Beat 158: short-string US-metro rule — a bare "City, ST" location label
    # ("San Francisco, CA (Remote)", "Austin, TX", "Seattle, WA — Remote") is
    # a US residency pin even with NO pin verb ("based in", "remote in") and
    # even when the description carries worldwide-eligibility marketing (that
    # B3 escape must not unlock a US metro). Guards: only short location
    # labels (prose stays open), never when a non-US locality shares the
    # string ("hubs in Austin, TX and Berlin" = multi-locality, open), never
    # on worldwide-marked text (handled by the marker exception below).
    words = low.split()
    if (
        len(words) <= 6
        and not any(w in low for w in ("worldwide", "anywhere in the world", "work from anywhere", "global remote", "globally remote"))
        and not any(re.search(rf"\b{re.escape(f)}\b", low) for f in _NON_US_LOCALITY_TOKENS)
        and any(re.search(rf"\b{re.escape(city)}\b", low) for city in _US_MAJOR_CITIES)
    ):
        return True
    # Beat 122 MEDIUM-A: target-marker exception — applied ONLY after every
    # hard US pin above. Casual multi-region prose ("Europe, LATAM, APAC, the
    # U.S., Canada", "Worldwide; hubs in Austin and Berlin") falls through to
    # here and stays open; marker'd text with a real pin never reaches this.
    if any(w in low for w in ("worldwide", "anywhere in the world", "work from anywhere", "global remote", "globally remote", "pakistan", "apac", "asia pacific", "south asia")):
        return False
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
            or "middle east" in text or "mena" in text or "gcc" in text
            or "b2b" in text or "freelance" in text
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


def parse_location_hierarchy(location: str | None) -> dict[str, str | None | bool]:
    """Breakdown a location string into city, state, country, and remote status.

    Examples:
      'Lahore, Punjab, Pakistan' -> {'city': 'Lahore', 'state': 'Punjab', 'country': 'Pakistan', 'is_remote': False}
      'Islamabad, Islāmābād, Pakistan' -> {'city': 'Islamabad', 'state': 'Islāmābād', 'country': 'Pakistan', 'is_remote': False}
      'San Francisco, CA' -> {'city': 'San Francisco', 'state': 'CA', 'country': 'United States', 'is_remote': False}
      'Remote, Pakistan' -> {'city': None, 'state': None, 'country': 'Pakistan', 'is_remote': True}
      'Worldwide' -> {'city': None, 'state': None, 'country': 'Worldwide', 'is_remote': True}
    """
    if not location:
        return {"city": None, "state": None, "country": None, "is_remote": False}

    raw = location.strip()
    is_rem = any(w in raw.lower() for w in ("remote", "wfh", "work from home", "anywhere", "worldwide", "global"))

    cleaned = re.sub(r"(?i)\s*[\(\[]?\b(?:remote|wfh|work from home|telecommute|virtual)\b[\)\]]?", "", raw)
    cleaned = re.sub(r"^[\s,–-]+|[\s,–-]+$", "", cleaned).strip()

    parts = [p.strip() for p in re.split(r",|–|-|\|", cleaned) if p.strip()]

    city: str | None = None
    state: str | None = None
    country: str | None = None

    if len(parts) == 1:
        single = parts[0]
        single_low = single.lower()
        if single_low in ("pakistan", "united states", "usa", "uk", "canada", "germany", "japan", "worldwide", "global"):
            country = single
        elif single_low in _US_STATE_NAMES or single_low in _US_STATE_ABBR:
            state = single
            country = "United States"
        else:
            city = single
    elif len(parts) == 2:
        p0, p1 = parts[0], parts[1]
        p1_low = p1.lower()
        if p1_low in _US_STATE_ABBR or p1_low in _US_STATE_NAMES:
            city = p0
            state = p1
            country = "United States"
        elif p1_low in ("pakistan", "india", "uk", "united kingdom", "canada", "germany", "japan", "australia", "uae", "saudi arabia"):
            city = p0
            country = p1
        else:
            city = p0
            state = p1
    elif len(parts) >= 3:
        city = parts[0]
        state = parts[1]
        country = parts[2]

    return {
        "city": city,
        "state": state,
        "country": country,
        "is_remote": is_rem,
    }


def is_worldwide_remote(
    location: str | None,
    source: str | None = None,
    description: str | None = None,
    title: str | None = None,
) -> bool:
    """True only when the job is clearly remote *without* US-restriction.

    Used by SCRAPE_REMOTE_ONLY: drops US state/city-restricted remote jobs
    (e.g. "Maryland – Remote", "Remote (US Only)", "Remote, OR"), US domestic-only
    remote jobs posted on US boards without worldwide eligibility (e.g. Indeed/Glassdoor
    bare "Remote"), and non-remote positions.

    In-scope remote (worldwide / Global / APAC / Middle East / Pakistan / South-Asia neighbor remote / B2B)
    qualifies for this Pakistan-based loop.
    """
    if not location:
        return False
    if is_title_restricted(title):
        return False
    if is_description_restricted(description):
        return False
    text = location.lower().strip()

    # Remote, Oregon disambiguation (physical hamlet in Coos County, OR)
    if (re.search(r"\bremote\s*,\s*(?:or|oregon)\b", text)
            or re.search(r"\bremote\s+(?:or|oregon)\b", text)
            or re.search(r"\bcoos\s+county\b", text)
            or re.search(r"\bremote\b.*\b97458\b", text)):
        return False

    # Country/region-restricted anywhere (e.g. "anywhere in India", "anywhere in the US")
    # Only "anywhere in the world" or "anywhere in world" or "work from anywhere" is allowed.
    if re.search(r"anywhere\s+in\s+(?!(?:the\s+)?world\b)", text):
        return False

    # B3 (Beat 108 tightened): only *eligibility* phrasing in the DESCRIPTION
    # overrides a physical-city location label (HQ city ≠ residency pin).
    # Bare "worldwide" marketing copy does NOT qualify — Residency language is
    # already rejected by is_description_restricted above; Israel stays hard-blocked.
    if (
        description
        and _has_strong_worldwide_eligibility(description)
        and not _is_us_restricted(text)
        and not re.search(r"\b(?:israel|tel aviv|jerusalem|haifa)\b", text)
        and not is_hybrid_work(text)
        and not any(w in text for w in ("onsite", "on-site", "in-office", "office only"))
    ):
        return True

    # If the location is restricted to a foreign country outside Pakistan/APAC/worldwide -> reject
    if is_foreign_country_restricted(text):
        return False

    # If the location is restricted to the US -> reject
    if _is_us_restricted(text):
        return False

    # US-domestic boards (Indeed, Glassdoor): bare "Remote" is domestic US remote
    # (requires US residency / SSN / W-2). Reject unless explicitly worldwide/global
    # or referencing in-scope APAC/Middle East/contractors in location or description.
    if source and source.lower() in US_DOMESTIC_BOARDS:
        combined = f"{text} {(description or '').lower()}"
        has_worldwide = any(m in combined for m in _WORLDWIDE_MARKERS)
        has_in_scope_geo = any(re.search(rf"\b{re.escape(r)}\b", combined) for r in (_APAC_REGIONS | _MIDDLE_EAST_REGIONS))
        has_contract = any(re.search(rf"\b{re.escape(c)}\b", combined) for c in _GLOBAL_CONTRACT_QUALIFIERS)
        if not (has_worldwide or has_in_scope_geo or has_contract):
            return False

    # Definitive worldwide / anywhere indicators (unambiguous)
    if any(w in text for w in (
        "worldwide", "work from anywhere", "anywhere in the world", "global remote", "globally remote",
        "work from home", "wfh", "anywhere"
    )):
        return True

    # Standalone "global"
    if re.search(r"\bglobal(?:ly)?\b", text):
        return True

    # B2B / Freelance contract modes (no geographic entity bounds)
    if any(w in text for w in ("b2b", "freelance")):
        return True

    # Hard-blocked developed APAC / Oceania markets ("zero residency" law:
    # Japan, Korea, Taiwan, HK/China board posts, Australia/NZ). These are
    # in APAC geographically but the durable location law rejects them as
    # foreign markets even when marked remote — a bare "Remote (Japan)" post
    # never gets the APAC fully-remote carve-out. (Singapore/India/APAC mark)
    # remain in-scope via the carve-out below.
    if re.search(
        r"\b(?:japan|tokyo|osaka|yokohama|nagoya|kyoto|south\s+korea|seoul|taiwan|"
        r"taipei|hong\s+kong|macau|china|beijing|shanghai|shenzhen|australia|"
        r"sydney|melbourne|new\s+zealand|auckland|wellington)\b",
        text, re.I,
    ):
        return False

    # Remote-native broad region designations (APAC, Asia Pacific, South Asia, Middle East, MENA, GCC)
    if any(w in text for w in ("apac", "asia pacific", "south asia", "middle east", "mena", "gcc")) and not any(w in text for w in ("onsite", "on-site", "hybrid", "in-office")):
        return True

    # APAC & Middle East Regional Remote Verification:
    # A candidate sitting at home in Pakistan can only perform:
    # 1. Direct Pakistan remote roles (e.g. "Remote, Pakistan", "Lahore (Remote)")
    # 2. Foreign regional roles (Tokyo, Dubai, Riyadh, Singapore) ONLY IF they explicitly
    #    declare Worldwide/Global remote, B2B/Contractor hiring, or open to Pakistan candidates.
    # Domestic foreign postings (requiring local residency, in-country taxes, or local work permit) are rejected.
    in_scope_geo = _APAC_REGIONS | _MIDDLE_EAST_REGIONS
    if any(re.search(rf"\b{re.escape(r)}\b", text) for r in in_scope_geo):
        if is_hybrid_work(text) or is_hybrid_work(description):
            return False
        if any(w in text for w in ("onsite", "on-site", "in-office", "office only", "office-based")):
            return False
        desc_lower = (description or "").lower()
        if any(w in desc_lower for w in ("onsite", "on-site", "in-office", "office only", "office-based")):
            return False

        is_pakistan = any(p in text for p in ("pakistan", "karachi", "lahore", "islamabad", "rawalpindi", "faisalabad", "peshawar"))
        has_remote_in_loc = any(w in text for w in ("remote", "work from home", "wfh", "anywhere", "telecommute"))
        title_has_remote = bool(re.search(r"\b(?:remote|wfh|work\s+from\s+home)\b", title.lower())) if title else False
        has_explicit_remote_desc = (
            any(w in desc_lower for w in ("100% remote", "fully remote", "work from home", "wfh", "100% work from home"))
            or bool(re.search(r"\b(?:location|workplace|workplace\s+type)\s*:\s*remote\b", desc_lower))
            or bool(re.search(r"\bremote[,\s]+pakistan\b", desc_lower))
            or bool(re.search(r"\bpakistan[,\s]+remote\b", desc_lower))
        )

        if is_pakistan:
            return has_remote_in_loc or title_has_remote or has_explicit_remote_desc

        # If location is a foreign physical city/country (e.g. "Tokyo, Japan", "Jeddah, Saudi Arabia")
        # without "remote" in the location text: casual description mentions of "wfh/remote"
        # only apply domestically within that country. It is only workable from Pakistan if
        # explicitly open Worldwide/Global or via B2B/Contractor/Freelance agreements.
        if not has_remote_in_loc:
            combined = f"{text} {desc_lower}"
            has_global_or_contract = (
                any(w in combined for w in _WORLDWIDE_MARKERS)
                or any(w in combined for w in _GLOBAL_CONTRACT_QUALIFIERS)
                or "pakistan" in combined
            )
            if not has_global_or_contract:
                return False
            return has_explicit_remote_desc

        return True

    # Standalone "anywhere"
    if "anywhere" in text:
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
        # Bare remote with a qualifier: in-scope qualifiers (worldwide,
        # all APAC countries/cities, all Middle East countries/cities, B2B, Freelance) qualify;
        # any other qualifier (US Only, Germany, Poland, EMEA, UK) stays rejected.
        if re.search(rf"remote\s*\((?!.*{_ALLOWED_REMOTE_QUALIFIERS_PATTERN})", text):
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


# Relative post-age units (Indeed/Glassdoor emit "Posted 3 days ago", "30+ days ago", "6d", "24h").
_RELATIVE_UNITS = {
    "day": 1, "days": 1, "d": 1,
    "h": 0, "hr": 0, "hrs": 0, "hour": 0, "hours": 0,  # hours ago -> posted today
    "week": 7, "weeks": 7, "w": 7,
    "mo": 30, "month": 30, "months": 30,
    "year": 365, "years": 365, "y": 365,
}


def parse_posted_date(value: str | None, today: date | None = None) -> date | None:
    """Parse a source's `posted_date` string into a date.

    Accepts ISO dates/timestamps ("2026-09-11", "2026-09-11T10:00:00+00:00"),
    "Today"/"Yesterday", and the relative strings Indeed/Glassdoor emit
    ("Posted 3 days ago", "30+ days ago", "6d", "24h", "Just posted"). Any unparseable
    value returns None so downstream code degrades to fetched_at instead of failing."""
    if not value:
        return None
    text = str(value).strip()
    today = today or utc_now().date()

    lowered = text.lower()
    for prefix in ("posted ", "active ", "employer active ", "urgently hiring "):
        if lowered.startswith(prefix):
            lowered = lowered[len(prefix):].strip()

    if lowered in ("today", "now", "just now", "just posted", "posted today", "active today"):
        return today
    if lowered == "yesterday":
        return today - timedelta(days=1)

    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass

    m = re.search(
        r"(\d+(?:\.\d+)?)\s*\+?\s*(day|days|d|h|hrs?|hours?|week|weeks|w|mo|month|months|year|years|y)\b",
        lowered,
    )
    if m:
        unit = m.group(2)
        multiplier = _RELATIVE_UNITS.get(unit)
        if multiplier is not None:
            delta_days = int(round(float(m.group(1)) * multiplier))
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
    """Profile gate: True when ANY pilot profile matches the job.

    (The keyword args are legacy — matching is profile-driven now. Kept in
    the signature so existing callers and tests don't break.)
    """
    from src.matcher import passing_profiles
    return bool(passing_profiles(job.title, job.description, job.tags))

