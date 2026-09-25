"""Project paths, environment, and runtime configuration."""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv optional
    def load_dotenv(*_a, **_k) -> None:
        return None


ROOT = Path(__file__).resolve().parent.parent

OUTPUT_DIR = ROOT / "output"
RUNTIME_DIR = ROOT / ".runtime"
SLC_DIR = ROOT / ".slc"

STATE_PATH = SLC_DIR / "state.json"
SEEN_PATH = SLC_DIR / "seen.json"
DEAD_LETTER_PATH = SLC_DIR / "dead_letter.json"

STATE_SCHEMA_VERSION = 1


def load_env() -> None:
    load_dotenv(ROOT / ".env")
    load_dotenv()


def scan_keywords() -> list[str]:
    """Primary AI-domain keywords: a job must match at least one of these
    to qualify (Java Developer etc. without an AI term is rejected)."""
    raw = os.environ.get(
        "SCRAPE_KEYWORDS",
        "AI/ML,LLM Engineer,AI Engineer,ML Engineer,AI FDE,Generative AI,Agentic AI",
    )
    return [k.strip() for k in raw.split(",") if k.strip()]


def scan_role_keywords() -> list[str]:
    """Secondary role keywords (Engineer/Developer): used only to steer
    scraper targeting; never enough on their own to qualify a job."""
    raw = os.environ.get("SCRAPE_ROLE_KEYWORDS", "Engineer,Developer")
    return [k.strip() for k in raw.split(",") if k.strip()]


def scrape_delay_range() -> tuple[float, float]:
    lo = env_float("SCRAPE_DELAY_MIN", 1.0)
    hi = env_float("SCRAPE_DELAY_MAX", 3.0)
    if lo > hi:
        raise SystemExit(f"[config] SCRAPE_DELAY_MIN ({lo}) > SCRAPE_DELAY_MAX ({hi})")
    return lo, hi


def scrape_headless() -> bool:
    return os.environ.get("SCRAPE_HEADLESS", "1") == "1"


def board_headless() -> bool:
    """Headed by default for CAPTCHA-prone boards (Indeed/Glassdoor) so a human
    can solve challenges in the visible browser. Opt into unattended headless
    runs explicitly via BOARD_HEADLESS=1."""
    return os.environ.get("BOARD_HEADLESS", "0") == "1"


def scrape_remote_only() -> bool:
    """Drop on-site/hybrid jobs entirely unless a job is clearly remote."""
    return os.environ.get("SCRAPE_REMOTE_ONLY", "1") == "1"


def chrome_binary() -> str | None:
    """Path to a real Chrome binary when available (lowest automation signal).
    Falls back to Playwright's bundled Chromium."""
    import shutil

    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        path = shutil.which(name)
        if path:
            return path
    return None


def captcha_solve_timeout() -> float:
    # Cloud cron must fail-closed immediately — nobody is at a headed window.
    if is_cloud_runner() and os.environ.get("CAPTCHA_SOLVE_TIMEOUT") is None:
        return 0.0
    return min(env_float("CAPTCHA_SOLVE_TIMEOUT", 120.0), max(10.0, source_timeout_s() - 20.0))


# All registered sources are live-verified and default ON.
DEFAULT_DISABLED_SOURCES: frozenset[str] = frozenset()

# Playwright / persistent-profile sources. The GitHub Actions cron sets
# JOB_LOOP_CLOUD=1 and cannot solve CAPTCHAs or reuse .runtime Chrome profiles.
# They stay available on a local headed machine unless CLOUD_ALLOW_BROWSER=1.
BROWSER_BOUND_SOURCES = frozenset({
    "indeed", "glassdoor",
})

FRIDAY_WEEKDAY = 4


def _get_tz() -> ZoneInfo:
    raw = os.environ.get("SCRAPE_TZ", "UTC")
    try:
        return ZoneInfo(raw)
    except (ValueError, KeyError):  # bad tz string → UTC
        return ZoneInfo("UTC")


def is_cloud_runner() -> bool:
    """True only for the scheduled/cloud job (not pytest in Actions test-gate)."""
    return os.environ.get("JOB_LOOP_CLOUD", "") == "1"


def allow_browser_scrapers() -> bool:
    if os.environ.get("CLOUD_ALLOW_BROWSER", "") == "1":
        return True
    return not is_cloud_runner()


def job_loop_should_run() -> bool:
    """Single-writer guard so local cron and GitHub cron cannot both notify.

    JOB_LOOP_ENABLED=0 always skips the scrape.
    JOB_LOOP_PRIMARY=github → only JOB_LOOP_CLOUD=1 runs
    JOB_LOOP_PRIMARY=local  → only non-cloud runs (default)
    JOB_LOOP_PRIMARY=both   → both (duplicate Telegram risk)
    """
    if os.environ.get("JOB_LOOP_ENABLED", "1") == "0":
        return False
    primary = os.environ.get("JOB_LOOP_PRIMARY", "local").strip().lower()
    cloud = is_cloud_runner()
    if primary in ("github", "github_actions", "cloud"):
        return cloud
    if primary == "local":
        return not cloud
    return True


def source_enabled(name: str) -> bool:
    if not allow_browser_scrapers() and name in BROWSER_BOUND_SOURCES:
        return False
    env_key = f"SOURCE_{name.upper()}"
    raw = os.environ.get(env_key)
    if raw is not None:
        return raw == "1"
    return name not in DEFAULT_DISABLED_SOURCES


# ── Phase 2 (A2): per-source domain registry ─────────────────────────────────
MAX_DOMAINS_PER_SOURCE = 15
DOMAIN_SOURCES = ("indeed", "glassdoor")

_DEFAULT_DOMAINS = {
    "indeed": "pk.indeed.com",          # proven both local and in cloud cron
    "glassdoor": "www.glassdoor.com",
}
_DOMAIN_ENV = {
    "indeed": "INDEED_DOMAINS",
    "glassdoor": "GLASSDOOR_DOMAINS",
}


def _valid_hostname(host: str) -> bool:
    """Registry-entry check: hostname only — no scheme/path/port/space/`..`."""
    if not host or len(host) > 253:
        return False
    if host.startswith(".") or host.endswith(".") or ".." in host:
        return False
    if not any(c.isalpha() for c in host):  # rejects IPs / all-numeric junk
        return False
    labels = host.split(".")
    for label in labels:
        if not label or label.startswith("-") or label.endswith("-"):
            return False
        if any(not (c.isalnum() or c == "-") for c in label):
            return False
    return True


def parse_domains(raw: str) -> list[str]:
    """Comma-separated hostnames → validated, deduped, order-preserving list.

    Capped at `MAX_DOMAINS_PER_SOURCE` (15). Invalid tokens are dropped, not
    raised: a malformed env value must shrink the list, never crash the run
    (fail-closed to fewer domains).
    """
    out: list[str] = []
    seen: set[str] = set()
    for tok in raw.split(","):
        host = tok.strip().lower()
        if not _valid_hostname(host) or host in seen:
            continue
        seen.add(host)
        out.append(host)
        if len(out) >= MAX_DOMAINS_PER_SOURCE:
            break
    return out


def source_domains(source: str) -> list[str]:
    """Domains a browser source may scrape (A2 env registry + cloud/local split).

    - `<SOURCE>_DOMAINS` (e.g. `INDEED_DOMAINS=a.com,b.com`) overrides everywhere.
    - In the scheduled cloud runner (`JOB_LOOP_CLOUD=1`), `<SOURCE>_DOMAINS_CLOUD`
      wins when set — the split lets cloud cron and local human runs use
      different domains without code changes.
    - No env → the pre-Phase-2 default (single proven domain): behaviour-
      preserving unless you opt in.
    - Non-registry sources → `[]` (no domain scoping; plain circuit keys).
    """
    base = _DOMAIN_ENV.get(source.lower())
    if base is None:
        return []
    if is_cloud_runner():
        cloud_raw = os.environ.get(f"{base}_CLOUD")
        if cloud_raw is not None and cloud_raw.strip():
            return parse_domains(cloud_raw)
    raw = os.environ.get(base)
    if raw is not None and raw.strip():
        return parse_domains(raw)
    return parse_domains(_DEFAULT_DOMAINS[source.lower()])


def notify_telegram() -> bool:
    return os.environ.get("NOTIFY_TELEGRAM", "1") == "1" and bool(os.environ.get("TELEGRAM_BOT_TOKEN"))


def notify_whatsapp() -> bool:
    return os.environ.get("NOTIFY_WHATSAPP", "0") == "1" and bool(os.environ.get("WHATSAPP_AUTH_TOKEN"))


def notify_linkedin() -> bool:
    return os.environ.get("NOTIFY_LINKEDIN", "0") == "1" and bool(os.environ.get("LINKEDIN_POST_ACCESS_TOKEN"))


def linkedin_feed_enabled() -> bool:
    """Scrape LinkedIn hiring FEED POSTS (content search) in addition to the
    jobs board. People announcing "we're hiring" in a status update are a major
    unofficial channel — an env-visible kill-switch in case the feed markup
    drifts and we want to stop the extra navigation without disabling the
    whole (already fragile) LinkedIn source."""
    return os.environ.get("SOURCE_LINKEDIN_FEED", "1") == "1"


def max_jobs_per_source() -> int:
    return int(env_float("MAX_JOBS_PER_SOURCE", 250))


def dedup_window_days() -> int:
    return int(env_float("DEDUP_WINDOW_DAYS", 30))


def circuit_breaker_threshold() -> int:
    return int(env_float("CIRCUIT_BREAKER_THRESHOLD", 3))


def circuit_breaker_reset_hours() -> float:
    return env_float("CIRCUIT_BREAKER_RESET_HOURS", 1.0)


def delay_ms_between_requests() -> float:
    """Random per-request delay so traffic is not a fixed robot cadence."""
    import random

    lo, hi = scrape_delay_range()
    return random.uniform(lo, hi)


def lock_timeout_s() -> float:
    """How long a run waits to acquire the state lock before giving up.

    When two crons race, the loser waits this long, then exits cleanly with
    'another run in progress' instead of corrupting shared state."""
    return env_float("LOCK_TIMEOUT_S", 5.0)


def source_timeout_s(source_name: str | None = None, now: datetime | None = None) -> float:
    """Hard wall-clock cap per source worker (main.py worker.join).

    Browser-bound sources (Indeed, Glassdoor) that may involve human CAPTCHA
    solving get 300s. Regular sources get 150s. LinkedIn is the exception:
    Friday is the spec'd hiring-feed-only day, so its feed pass (21 queries)
    needs real headroom — otherwise the 150s cap strangles the feed pass and
    it silently yields only guest jobs. Other weekdays keep the standard cap so
    the full-sweep days stay bounded."""
    if source_name == "linkedin":
        weekday = (now or datetime.now(_get_tz())).weekday()
        if weekday in (0, FRIDAY_WEEKDAY):  # Monday (3d backfill + feed) and Friday (feed day)
            return env_float("LINKEDIN_FEED_TIMEOUT_S", 600.0)
        return env_float("LINKEDIN_TIMEOUT_S", 150.0)
    if source_name and source_name in BROWSER_BOUND_SOURCES:
        return env_float("BROWSER_SOURCE_TIMEOUT_S", 300.0)
    return env_float("SOURCE_TIMEOUT_S", 150.0)


def linkedin_guest_timeout_s() -> float:
    """Budget for LinkedIn's public guest pass (26 sequential requests: 13
    keywords × Worldwide/Pakistan). Unbounded it can eat 390s of network
    timeout and starve the whole source. Yields what it collected once the
    budget is exhausted and stops, so the browser feed pass still has room."""
    return env_float("LINKEDIN_GUEST_TIMEOUT_S", 120.0)


def linkedin_browser_timeout_s() -> float:
    """Cap for the authenticated LinkedIn browser pass (feed + board gather).
    The public guest request pass is fast; only the Playwright SPA path needs
    the rope. Friday expands _feed_queries to 3 per keyword (plain + #hiring +
    "we are hiring") = 21 content-search navigations on top of the 7 board
    scrapes — 90s was far too tight and the feed pass silently self-aborted
    with an empty TimeoutError. 480s fits Friday's full feed scan under the
    600s Friday source cap (120s guest + 480s browser = 600s)."""
    return env_float("LINKEDIN_BROWSER_TIMEOUT_S", 480.0)


def lock_stale_s() -> float:
    """Age beyond which a held lock is deemed stale (holder hung).

    The watchdog (main.py): a lock-starved run reads the holder's sidecar
    (pid + acquired_at); if the lock has been held longer than this, the loop
    exits 1 so monitoring alerts, instead of silently skipping like a benign
    two-cron race. 2h is generous — a legit run with CAPTCHA waits is minutes,
    never hours."""
    return env_float("LOCK_STALE_S", 7200.0)


def env_or(name: str, default: str) -> str:
    return os.environ.get(name, default)


def env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        raise SystemExit(f"[config] {name} must be a number, got '{raw!r}'") from None


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        raise SystemExit(f"[config] {name} must be an integer, got '{raw!r}'") from None


def health_port() -> int:
    """Port for daemon /healthz endpoint in --serve mode."""
    return env_int("HEALTH_PORT", 8080)


def easy_apply_only() -> bool:
    """If True, restrict search queries where supported (LinkedIn f_AL=true,
    Indeed iaFilter=1, Glassdoor easyApplyOnly=true) to Easy Apply jobs only."""
    return os.environ.get("EASY_APPLY_ONLY", "0") == "1"


def linkedin_experience_levels() -> str:
    """LinkedIn experience levels filter (f_E param).
    1: Internship, 2: Entry level, 3: Associate, 4: Mid-Senior level, 5: Director, 6: Executive.
    Disabled by default per user request. Empty string disables f_E from search URL."""
    return os.environ.get("LINKEDIN_EXPERIENCE_LEVELS", "").strip()



def die(msg: str, code: int = 1) -> None:
    print(f"[error] {msg}", file=sys.stderr)
    raise SystemExit(code)


def ensure_dirs() -> None:
    for d in (OUTPUT_DIR, RUNTIME_DIR, SLC_DIR):
        d.mkdir(parents=True, exist_ok=True)