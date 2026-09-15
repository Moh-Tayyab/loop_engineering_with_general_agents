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
    raw = os.environ.get("SCRAPE_KEYWORDS", "AI,Machine Learning,LLM,NLP,Data Science,Computer Vision,AI FDE")
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
    return env_float("CAPTCHA_SOLVE_TIMEOUT", 300.0)


# Curated boards registered but NOT yet wired (no live-verified collection).
# Default-OFF so an unverified fetch can't silently return nothing or mask a
# real outage with a fake 'ok' on a live cron. Flip SOURCE_<NAME>=1 to opt in
# only after the collector for that board is implemented & live-verified.
# (wellfound + justremote were moved OUT of this set on 2026-09-15 — their
# collectors are now live-verified and default ON.)
DEFAULT_DISABLED_SOURCES = frozenset({
    "feedcoyote", "jobboardsearch",
    "flexjobs", "dynamitejobs", "virtual_vocations", "nodesk",
})


def source_enabled(name: str) -> bool:
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
    return int(env_float("MAX_JOBS_PER_SOURCE", 100))


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


def die(msg: str, code: int = 1) -> None:
    print(f"[error] {msg}", file=sys.stderr)
    raise SystemExit(code)


def ensure_dirs() -> None:
    for d in (OUTPUT_DIR, RUNTIME_DIR, SLC_DIR):
        d.mkdir(parents=True, exist_ok=True)