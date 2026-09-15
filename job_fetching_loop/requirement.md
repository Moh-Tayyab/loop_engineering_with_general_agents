# requirement.md — AI/ML Job Fetching Loop (Production Spec)

## 1. Vision

An autonomous, resilient job-discovery loop that scrapes AI/ML remote positions
from 7 sources, deduplicates intelligently, and delivers curated notifications
via WhatsApp/Telegram. Designed for daily autonomous operation with zero human
intervention after initial setup.

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         OUTER LOOP (Scheduler)                         │
│  ┌─────────────┐                                                       │
│  │ Cron Trigger │──> Read STATE.md → Check schedule → Dispatch beats   │
│  └─────────────┘                                                       │
├─────────────────────────────────────────────────────────────────────────┤
│                         INNER LOOP (Beat Execution)                    │
│                                                                         │
│  ┌──────────┐   ┌──────────────┐   ┌──────────┐   ┌──────────────┐    │
│  │ Schedule │──>│ Source Router │──>│ Pipeline │──>│  Notifier    │    │
│  │  Engine  │   │  (7 sources) │   │          │   │ (WhatsApp/   │    │
│  └──────────┘   └──────────────┘   │ Fetch    │   │  Telegram)   │    │
│                                    │ Dedup    │   └──────────────┘    │
│                                    │ Normalize│                        │
│                                    │ Store    │                        │
│                                    └──────────┘                        │
├─────────────────────────────────────────────────────────────────────────┤
│                         RESILIENCE LAYER                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                 │
│  │ Circuit      │  │ Retry with   │  │ Dead Letter  │                 │
│  │ Breaker      │  │ Backoff      │  │ Queue        │                 │
│  └──────────────┘  └──────────────┘  └──────────────┘                 │
└─────────────────────────────────────────────────────────────────────────┘
```

## 3. Schedule Engine (Day-Aware)

```python
# schedule.py logic
def compute_fetch_window(now: datetime) -> tuple[datetime, str]:
    """Returns (fetch_after, reason) based on day-of-week."""
    match now.weekday():
        case 0:  # Monday — catch up weekend
            return now - timedelta(days=3), "weekend_backfill"
        case 1 | 2 | 3:  # Tue-Thu — daily
            return now - timedelta(hours=24), "daily_incremental"
        case 4:  # Friday — weekly + digest
            return now - timedelta(days=7), "weekly_digest"
        case 5 | 6:  # Weekend — idle
            return None, "idle"
```

**State Persistence:**
```json
{
  "last_run": "2026-09-14T09:00:00+05:00",
  "last_fetch_window": {"start": "2026-09-13T09:00:00+05:00", "reason": "daily_incremental"},
  "sources": {
    "linkedin": {"last_success": "...", "consecutive_fails": 0, "circuit_open_until": null},
    "indeed": {"last_success": "...", "consecutive_fails": 2, "circuit_open_until": null}
  },
  "jobs_this_week": 47,
  "schema_version": 1
}
```

## 4. Source Architecture (Strategy Pattern)

```python
# scrapers/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator

@dataclass
class RawJob:
    """Unprocessed job from a source — before normalization."""
    source: str
    title: str
    company: str
    url: str
    location: str | None
    salary: str | None
    posted_date: str | None  # raw from source
    description: str | None
    tags: list[str]
    fetched_at: datetime

class BaseScraper(ABC):
    """Abstract base for all job sources."""
    
    name: str  # "linkedin", "indeed", etc.
    
    @abstractmethod
    def fetch(self, keywords: list[str], posted_after: datetime) -> Iterator[RawJob]:
        """Yield jobs matching keywords, posted after the given datetime.
        
        Must handle:
        - Anti-bot detection (retry with backoff)
        - CAPTCHA → raise CaptchaDetected for manual assist
        - Rate limiting (sleep between requests)
        - Empty results (valid — source may have no new jobs)
        """
        ...
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if this source is reachable (pre-flight)."""
        ...
    
    def login_required(self) -> bool:
        """Override True for sources needing session (LinkedIn)."""
        return False
```

**Per-Source Implementation Details:**

| Source | Strategy | Anti-Bot | Rate Limit | Notes |
|--------|----------|----------|------------|-------|
| Remote Rocketship | RSS/API scrape | Low | 1s | Easiest, structured |
| Working Nomads | HTML parse | Low | 1s | Clean HTML |
| LinkedIn | Playwright + session | HIGH | 3-5s | Needs login gate, stealth |
| Indeed | Playwright | HIGH | 2-3s | CAPTCHA common |
| Glassdoor | Playwright | HIGH | 3-5s | Aggressive blocking |
| APAC Remote | HTML parse | Low | 1s | Niche, less traffic |
| Pakistan Remote | HTML parse | Low | 1s | Rozee.pk structured |

**Stealth Configuration:**
```python
# Each Playwright browser gets:
STEALTH_CONFIG = {
    "args": [
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--no-sandbox",
    ],
    "user_agent": random.choice(USER_AGENTS),  # rotation
    "viewport": {"width": 1920, "height": 1080},
}
# + playwright-stealth plugin for fingerprint masking
```

## 5. Deduplication (Multi-Layer)

**Layer 1 — URL Hash (Fast, Exact):**
```python
import hashlib
def job_hash(url: str, title: str, company: str) -> str:
    """Deterministic hash for exact-match dedup."""
    raw = f"{url.lower().strip()}|{title.lower().strip()}|{company.lower().strip()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
```

**Layer 2 — Fuzzy Dedup (Same Job, Different Sources):**
```python
from difflib import SequenceMatcher

def is_duplicate(job: Job, existing: list[Job], threshold: float = 0.85) -> bool:
    """Check if job is semantically same as any existing (different URL)."""
    for prev in existing:
        title_sim = SequenceMatcher(None, job.title.lower(), prev.title.lower()).ratio()
        company_sim = SequenceMatcher(None, job.company.lower(), prev.company.lower()).ratio()
        if title_sim > threshold and company_sim > threshold:
            return True
    return False
```

**Dedup State:**
```json
{
  "seen_hashes": ["abc123...", "def456..."],
  "recent_jobs": [
    {"hash": "abc123", "title": "ML Engineer", "company": "OpenAI", "source": "linkedin", "added": "..."}
  ],
  "max_recent": 5000
}
```

## 6. Data Normalization

```python
@dataclass
class NormalizedJob:
    """Standardized job record after source-specific parsing."""
    id: str                    # hash
    title: str                 # cleaned
    title_normalized: str      # lowercase, no special chars (for fuzzy dedup)
    company: str               # cleaned
    company_normalized: str
    url: str
    source: str
    location: str | None
    location_type: str         # "remote" | "hybrid" | "onsite" | "unknown"
    salary_min: int | None     # parsed from raw
    salary_max: int | None
    salary_currency: str | None
    job_type: str              # "full-time" | "contract" | "part-time" | "unknown"
    posted_date: date | None
    fetched_at: datetime
    tags: list[str]
    description_snippet: str   # first 300 chars
    raw: dict                  # full source data (debugging)
```

## 7. Notification System

```python
# notifier.py
class Notifier(ABC):
    @abstractmethod
    def send_daily(self, jobs: list[NormalizedJob], stats: dict) -> bool:
        """Send daily summary. Returns True on success."""
        ...
    
    @abstractmethod
    def send_weekly_digest(self, week_stats: dict, top_jobs: list[NormalizedJob]) -> bool:
        """Send Friday digest."""
        ...

class TelegramNotifier(Notifier):
    """Telegram Bot API — free, no approval needed."""
    def __init__(self, bot_token: str, chat_id: str):
        self.api = f"https://api.telegram.org/bot{bot_token}"
        self.chat_id = chat_id

class WhatsAppNotifier(Notifier):
    """WhatsApp via Twilio or official Cloud API."""
    def __init__(self, from_number: str, to_number: str, auth_token: str):
        ...
```

**Message Format (Telegram):**
```
🤖 AI/ML Jobs — Sep 14, 2026
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 New: 12 jobs | Total this week: 47

🔥 Top Picks:
1. ML Engineer @ OpenAI (Remote) — $180-220k
   linkedin.com/jobs/...
2. AI Researcher @ DeepMind (Remote) — £120-160k
   indeed.com/jobs/...

📁 Full list: output/jobs_2026-09-14.json
```

## 8. Resilience Patterns

**Circuit Breaker (Per Source):**
```python
class CircuitBreaker:
    """Prevent hammering a failing source."""
    def __init__(self, fail_threshold: int = 3, reset_after: timedelta = timedelta(hours=1)):
        self.fail_threshold = fail_threshold
        self.reset_after = reset_after
        self.consecutive_fails = 0
        self.open_until: datetime | None = None
    
    def record_success(self):
        self.consecutive_fails = 0
        self.open_until = None
    
    def record_failure(self):
        self.consecutive_fails += 1
        if self.consecutive_fails >= self.fail_threshold:
            self.open_until = datetime.now(timezone.utc) + self.reset_after
    
    def is_open(self) -> bool:
        if self.open_until and datetime.now(timezone.utc) < self.open_until:
            return True
        return False
```

**Retry with Exponential Backoff:**
```python
async def retry_with_backoff(func, max_retries: int = 3, base_delay: float = 1.0):
    for attempt in range(max_retries):
        try:
            return await func()
        except CaptchaDetected:
            raise  # Don't retry CAPTCHAs — escalate to human
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
            await asyncio.sleep(delay)
```

**Dead Letter Queue:**
```json
{
  "failed_jobs": [
    {
      "source": "linkedin",
      "error": "CAPTCHA detected",
      "timestamp": "...",
      "retry_count": 3,
      "keywords": ["ML engineer", "remote"]
    }
  ]
}
```

## 9. Configuration (.env)

```bash
# === Scraping ===
SCRAPE_KEYWORDS=AI,Machine Learning,LLM,NLP,Data Science,Computer Vision
SCRAPE_DELAY_MIN=1.0
SCRAPE_DELAY_MAX=3.0
SCRAPE_HEADLESS=1

# === Sources (enable/disable) ===
SOURCE_REMOTE_ROCKETSHIP=1
SOURCE_WORKING_NOMADS=1
SOURCE_LINKEDIN=0          # requires login first
SOURCE_INDEED=1
SOURCE_GLASSDOOR=0         # aggressive blocking, disable until stealth proven
SOURCE_APAC_REMOTE=1
SOURCE_PAKISTAN_REMOTE=1

# === Notifications ===
NOTIFY_TELEGRAM=1
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id
NOTIFY_WHATSAPP=0
WHATSAPP_FROM=+1234567890
WHATSAPP_TO=+0987654321
WHATSAPP_AUTH_TOKEN=your_twilio_token

# === LinkedIn (if enabled) ===
LINKEDIN_SESSION_DIR=.runtime/linkedin-profile

# === Limits ===
MAX_JOBS_PER_SOURCE=100
DEDUP_WINDOW_DAYS=30
CIRCUIT_BREAKER_THRESHOLD=3
CIRCUIT_BREAKER_RESET_HOURS=1
```

## 10. File Structure

```
job_fetching_loop/
├── src/
│   ├── __init__.py
│   ├── main.py                 # CLI orchestrator
│   ├── config.py               # env, paths, feature flags
│   ├── state.py                # LoopState (atomic, crash-safe)
│   ├── schedule.py             # day-of-week window calculator
│   ├── models.py               # RawJob, NormalizedJob dataclasses
│   ├── normalize.py            # source-specific → standard schema
│   ├── dedup.py                # URL hash + fuzzy dedup
│   ├── circuit_breaker.py      # per-source resilience
│   ├── notifier.py             # Telegram + WhatsApp abstract
│   ├── digest.py               # Friday weekly summary
│   ├── browser.py              # Playwright stealth launcher
│   ├── login_gates/
│   │   ├── linkedin.py         # manual login gate
│   │   └── __init__.py
│   └── scrapers/
│       ├── __init__.py         # registry + factory
│       ├── base.py             # BaseScraper ABC
│       ├── remote_rocketship.py
│       ├── working_nomads.py
│       ├── linkedin.py
│       ├── indeed.py
│       ├── glassdoor.py
│       ├── apac_remote.py
│       └── pakistan_remote.py
├── tests/
│   ├── __init__.py
│   ├── test_schedule.py
│   ├── test_dedup.py
│   ├── test_normalize.py
│   ├── test_circuit_breaker.py
│   ├── test_scrapers.py       # integration tests (mocked HTML)
│   └── conftest.py
├── output/                     # generated job files
├── .slc/
│   ├── state.json              # loop state (atomic)
│   ├── seen.json               # dedup hashes
│   └── dead_letter.json        # failed items
├── .runtime/
│   └── linkedin-profile/       # browser session (gitignored)
├── .env
├── .env.example
├── .gitignore
├── requirement.md              # this file
├── requirements.txt
└── README.md
```

## 11. CLI Interface

```bash
# Daily run (respects schedule logic)
python -m src.main

# Force specific window
python -m src.main --window daily        # override schedule
python -m src.main --window weekly       # force weekly digest
python -m src.main --window backfill     # force 3-day backfill

# Single source testing
python -m src.main --source linkedin     # test one source
python -m src.main --source indeed --dry-run  # mock, no notifications

# Digest generation
python -m src.main --digest              # force Friday digest

# Maintenance
python -m src.main --stats              # print dedup stats
python -m src.main --reset-circuit      # reset all circuit breakers

# LinkedIn login
python -m src.main --linkedin-login     # manual login gate
```

## 12. Testing Strategy

| Test Type | Coverage | Tools |
|-----------|----------|-------|
| Unit | Schedule logic, dedup, normalize | pytest |
| Integration | Scraper with mocked HTML fixtures | pytest + fixtures |
| E2E | Full pipeline with --dry-run | pytest + Playwright |
| Resilience | Circuit breaker, retry, dead letter | pytest + mock |
| Manual | Live scrape verification | --dry-run → human inspect |

**Key Test Cases:**
1. Monday backfill computes correct 3-day window
2. Fuzzy dedup catches "ML Engineer" == "Machine Learning Engineer" at same company
3. Circuit breaker opens after 3 failures, resets after 1 hour
4. Dead letter captures sources that fail all retries
5. Notification message formatting (Telegram markdown)
6. Atomic state writes survive crash mid-write

## 13. Anti-Detection Strategy

1. **User-Agent Rotation:** 10+ realistic Chrome/Firefox UAs, rotate per source
2. **Stealth Mode:** playwright-stealth plugin (hides webdriver property)
3. **Random Delays:** 1-3s between page loads (not fixed interval)
4. **Viewport Variation:** Randomize within common resolutions
5. **Session Persistence:** LinkedIn/Indeed profiles saved, reused
6. **CAPTCHA Detection:** Detect hCaptcha/reCAPTCHA → pause, notify human
7. **Proxy Support (Optional):** residential proxies for high-volume sources

## 14. Constraints

- Never commit `.env`, `.runtime/`, `.slc/`, `output/` to git.
- Scraping must respect `robots.txt` where possible.
- Rate limits: minimum 1s between requests per source.
- LinkedIn session must be manually authenticated (no stored passwords).
- Max 3 consecutive failures per source → circuit opens for 1 hour.
- Notifications: max 1 per day + 1 per Friday (no spam).
- All dates/times in UTC internally, display in configured timezone.
