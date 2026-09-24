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


def check_link_health(url: str, timeout_s: float = 3.0) -> bool:
    """True if link is alive (or health is indeterminate); False only on definitive death.

    Fail-closed only for proof of death (404/410). Network flake / timeout /
    TLS weirdness must NOT drop a valid Rule-11 job (symmetric with
    `is_expired_job`: unknown stays, known-dead goes)."""
    if not is_valid_job_url(url):
        return False
    import os
    import requests
    # In unmocked pytest runs, do not make live outbound requests on dummy test domains
    if os.environ.get("PYTEST_CURRENT_TEST") and getattr(requests.head, "__module__", "") == "requests.api":
        return True
    try:
        headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        resp = requests.head(url, headers=headers, timeout=timeout_s, allow_redirects=True)
        if resp.status_code == 405:
            resp = requests.get(url, headers=headers, timeout=timeout_s, stream=True)
        if resp.status_code in (404, 410):
            return False
        return True
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
    r"|remote\s*[-,–/]\s*([A-Za-z .]+)"  # "Remote - US Only" / "Remote - Texas" / "Remote / US"
    r"|([A-Za-z .]+?)\s*[-,–/]\s*remote)"  # "Maryland – Remote" / "TX - Remote" / "US - Remote"
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


def _has_strong_worldwide_eligibility(description: str | None) -> bool:
    """Beat 108: description proves *job eligibility*, not marketing reach.

    Bare "worldwide" ("impact worldwide", "clients worldwide") must NOT override
    a physical foreign location — that reopened Germany/Chile/Rio BairesDev FPs.
    Only explicit open-to-the-world phrasing qualifies (Rule 11c / B3).
    """
    d = (description or "").lower()
    return any(m in d for m in (
        "work from anywhere", "anywhere in the world", "anywhere in world",
        "global remote", "globally remote", "worldwide remote", "remote worldwide",
        "open worldwide", "eligible worldwide", "candidates worldwide",
        "applicants worldwide", "no location requirement",
        "no geographic restriction", "location-agnostic", "location agnostic",
        "hire from anywhere", "hiring from anywhere", "work from anywhere in",
    ))


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
    r"\bpolish\b",
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
    # Tech-stack / figure-of-speech carve-outs first
    cleaned = re.sub(
        r"\bhybrid[\s_-]+(?:cloud|multicloud|multi-cloud|infrastructure|infra|"
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
    t = title.lower()
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
    if re.search(rf"\b(?:{_title_only_countries})\s*[-–]?\s*only\b", t):
        return True
    if re.search(rf"\bonly\s+in\s+(?:the\s+)?(?:{_title_only_countries})\b", t):
        return True
    if re.search(rf"\b(?:{_title_only_countries}|eu|european|emirates)\s+candidates?\s+only\b", t):
        return True
    if re.search(r"\b(?:us|usa|u\.s\.|uk|canada|eu|european|israel)\s+based\b", t):
        return True
    if re.search(r"\[(?:[^\]]*\b)?(?:us|usa|uk|canada|europe|germany|poland|latam|israel)[- ]only(?:\b[^\]]*)?\]", t):
        return True
    if re.search(r"\((?:[^)]*\b)?(?:us|usa|uk|canada|europe|germany|poland|latam|israel)[- ]only(?:\b[^)]*)?\)", t):
        return True
    # Physical hub / city restrictions in title e.g. [NYC or SF], (NYC or SF), -Onsite in ...
    if re.search(r"\[(?:[^\]]*\b)?(?:nyc|sf|new york|san francisco|london|berlin|austin|seattle|boston|tel aviv|jerusalem)(?:\b[^\]]*)?\]", t):
        return True
    if re.search(r"\((?:[^)]*\b)?(?:nyc|sf|new york|san francisco|london|berlin|austin|seattle|boston|tel aviv|jerusalem)(?:\b[^)]*)?\)", t):
        return True
    # Bare on-site / in-office mention anywhere in the title is a physical-attendance signal.
    if re.search(r"\b(?:on-site|onsite|on site|in[- ]office|office[- ]based|office only)\b", t):
        return True
    # Commission-only / sales-closer modes are not salaried engineering roles.
    if re.search(r"\bcommission\s+(?:only|-only|based)\b", t):
        return True
    # Foreign employment forms a Pakistan candidate cannot exercise
    # (German "Working Student", apprenticeships, exchange/internship visas).
    if re.search(r"\bworking\s+student\b|\bwerkstudent\b|\bco[- ]op\b", t):
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
    r"\b(?:us|usa)\s+(?:citizenship|citizen|resident|residency|based|candidates?)\s+only\b",
    r"\b(?:us|usa|u\.s\.)\s+citizens?\s+or\s+permanent\s+residents?\b",
    r"\b(?:uk|canada|eu|european)\s+citizens?\s+or\s+permanent\s+residents?\b",
    r"\b(?:uk|canada|eu|european)\s+(?:candidates?|residen(?:ts?|cy)|based)\s+only\b",
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
    r"\b(?:eastern|central|pacific|mountain)\s+(?:time|hours?|zone)\b",
    r"\b(?:est|cst|mst|pst)\s+(?:time|hours?|zone|business)\b",
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
]


def is_description_restricted(description: str | None) -> bool:
    """True if description contains geographic/residency/onsite restrictions excluding Pakistan remote."""
    if not description:
        return False
    if is_language_restricted(description):
        return True
    if is_hybrid_work(description):
        return True
    low = description.lower()
    for pattern in _DESCRIPTION_RESTRICTION_PATTERNS:
        if re.search(pattern, low):
            return True
    # "100% Remote - USA Only" / "US-only" must only match the UPPERCASE abbreviation,
    # never the lowercase pronoun "us" (e.g. "gives us only ..."). Match on the original case.
    if re.search(r"\b(?i:100%\s+remote\s*[-–]?\s*)?(?:US|USA|U\.S\.)\s*[-–]?\s*(?i:only)\b", description):
        return True
    return False


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
    # Explicit worldwide or in-scope markers override US mention (e.g. "Europe, LATAM, APAC, the U.S., Canada" or "Worldwide")
    if any(w in low for w in ("worldwide", "anywhere in the world", "work from anywhere", "global remote", "globally remote", "pakistan", "apac", "asia pacific", "south asia")):
        return False
    # Explicit disambiguation for Remote, Oregon (Coos County, OR, ZIP 97458)
    if (re.search(r"\bremote\s*,\s*(?:or|oregon)\b", low)
            or re.search(r"\bremote\s+(?:or|oregon)\b", low)
            or re.search(r"\bcoos\s+county\b", low)
            or re.search(r"\bremote\b.*\b97458\b", low)):
        return True

    # Tokens / phrases indicating USA restriction
    if re.search(r"\b(?:usa|united states(?:\s+of\s+america)?|u\.s\.a)\b", low):
        return True
    if re.search(r"\b(?:us|u\.s\.)\s*(?:only|based|resident|citizen|candidates?)\b", low):
        return True

    for state in _US_STATE_NAMES:
        if re.search(rf"\b{re.escape(state)}\b", low):
            return True

    # Postal abbreviation preceded by comma or in
    m_abbr = re.search(r"(?:,\s*|\bin\s+)([a-z]{2})\b", low)
    if m_abbr and m_abbr.group(1) in _US_STATE_ABBR:
        return True

    m = _US_RESTRICTED_RE.search(text)
    if m:
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
            if any(re.search(rf"\b{re.escape(city)}\b", grp_low) for city in _US_MAJOR_CITIES):
                return True
    # A3: bare "Remote - Austin" style where the city is the only qualifier
    # (already covered via _US_RESTRICTED_RE groups); also catch a US city
    # sitting next to Remote outside the paren/dash forms, e.g. "Remote, Chicago".
    if re.search(r"\bremote\b", low):
        for city in _US_MAJOR_CITIES:
            if re.search(rf"\b{re.escape(city)}\b", low):
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
    """AI-domain gate: requires candidate CV match (Muhammad Usama profile)
    and strictly drops blacklisted non-technical roles and unrelated tech stacks.
    """
    from src.matcher import match_usama_cv
    is_match, score, label = match_usama_cv(job.title, job.description, job.tags)
    return is_match

