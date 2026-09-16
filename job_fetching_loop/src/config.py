"""Project paths, environment, and runtime configuration."""
from __future__ import annotations

import os
import sys
from pathlib import Path

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
        "AI,Machine Learning,LLM,NLP,Data Science,Computer Vision,AI FDE,Generative AI,GenAI,Deep Learning,MLOps,AI Agent,PyTorch",
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
    return env_float("CAPTCHA_SOLVE_TIMEOUT", 300.0)


# All registered sources are live-verified and default ON.
DEFAULT_DISABLED_SOURCES: frozenset[str] = frozenset()

# Playwright / persistent-profile sources. The GitHub Actions cron sets
# JOB_LOOP_CLOUD=1 and cannot solve CAPTCHAs or reuse .runtime Chrome profiles.
# They stay available on a local headed machine unless CLOUD_ALLOW_BROWSER=1.
BROWSER_BOUND_SOURCES = frozenset({
    "indeed", "glassdoor", "justremote",
    "remote_rocketship", "apac_remote", "pakistan_remote",
})


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


def source_timeout_s() -> float:
    """Hard per-source wall-clock cap. A hung Playwright fetch (CAPTCHA stall,
    EPIPE, stuck SPA) must not stall the whole daily loop beyond this. The
    orchestrator runs each source in a bounded worker; a source that exceeds
    this is failed (circuit breaker) and the run continues with the rest.
    150s < 15-min run budget: worst case ≈ linkedin(135) + 2 heavy browsers
    (2×120) + 12 fast sources (~2s each) ≈ 8 min, plus digest + notifies."""
    return env_float("SOURCE_TIMEOUT_S", 150.0)


def linkedin_guest_timeout_s() -> float:
    """Budget for LinkedIn's public guest pass (26 sequential requests: 13
    keywords × Worldwide/Pakistan). Unbounded it can eat 390s of network
    timeout and starve the whole source. Yields what it collected once the
    budget is exhausted and stops, so the browser feed pass still has room."""
    return env_float("LINKEDIN_GUEST_TIMEOUT_S", 45.0)


def linkedin_browser_timeout_s() -> float:
    """Cap for the authenticated LinkedIn browser pass (feed + board gather).
    The public guest request pass is fast; only the Playwright SPA path needs
    the rope so a single keyword-nav loop can't burn the whole budget.
    45 (guest) + 90 (browser) = 135s < SOURCE_TIMEOUT_S=150 → LinkedIn yields
    guest jobs first, then feed posts, without hitting the orchestrator cap."""
    return env_float("LINKEDIN_BROWSER_TIMEOUT_S", 90.0)


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


def die(msg: str, code: int = 1) -> None:
    print(f"[error] {msg}", file=sys.stderr)
    raise SystemExit(code)


def ensure_dirs() -> None:
    for d in (OUTPUT_DIR, RUNTIME_DIR, SLC_DIR):
        d.mkdir(parents=True, exist_ok=True)