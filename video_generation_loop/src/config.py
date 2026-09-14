"""Project paths, environment, and runtime configuration."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is optional in bare envs
    def load_dotenv(*_a, **_k) -> None:  # type: ignore
        return None


ROOT = Path(__file__).resolve().parent.parent

# Top-level dirs
COURSE_DIR = ROOT / "course"
OUTPUT_DIR = ROOT / "output"
RUNTIME_DIR = ROOT / ".runtime"
SLC_DIR = ROOT / ".slc"

# Derived paths
TOPICS_PATH = COURSE_DIR / "topics.json"
STATE_PATH = SLC_DIR / "state.json"
BROWSER_PROFILE_DIR = RUNTIME_DIR / "flow-pipeline-profile"
DEFAULT_SCHEMA = "https://labs.google/fx/tools/flow"


def load_env() -> None:
    """Load .env from project root (never prints values)."""
    load_dotenv(ROOT / ".env")
    load_dotenv()


def gcloud_api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or None


def planner_source() -> str:
    """Which engine writes the storyboard scripts.

    Default is 'template' — a deterministic, offline script-builder with no
    API dependency. Set FLOW_PLANNER=gemini to opt into the Gemini API
    (requires GEMINI_API_KEY / GOOGLE_API_KEY).
    """
    return os.environ.get("FLOW_PLANNER", "template").strip().lower()


def use_gemini() -> bool:
    """True only when the user explicitly opted into the Gemini API AND a key
    is present. Never auto-fallback to an API the user did not choose."""
    return planner_source() == "gemini" and gcloud_api_key() is not None


def gemini_base_url() -> str:
    return os.environ.get(
        "GEMINI_BASE_URL",
        "https://generativelanguage.googleapis.com/v1beta/openai/",
    )


def gemini_model() -> str:
    return os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")


def flow_url() -> str:
    return os.environ.get("FLOW_URL", DEFAULT_SCHEMA)


def flow_headless() -> bool:
    return os.environ.get("FLOW_HEADLESS", "1") == "1"


def browser_profile_dir() -> Path:
    return Path(os.environ.get("FLOW_PROFILE_DIR", str(BROWSER_PROFILE_DIR)))


def ffmpeg_binary() -> str:
    """Return an ffmpeg binary; prefer system, fall back to imageio-ffmpeg."""
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        import imageio_ffmpeg
    except ImportError:
        return "ffmpeg"  # let the user see the standard 'command not found'
    return imageio_ffmpeg.get_ffmpeg_exe()


def ffprobe_binary() -> str | None:
    """Return an ffprobe binary if one exists (system or imageio sibling)."""
    system = shutil.which("ffprobe")
    if system:
        return system
    try:
        import imageio_ffmpeg
    except ImportError:
        return None
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    sibling = Path(exe).with_name("ffprobe")
    return str(sibling) if sibling.exists() else None


def ensure_dirs() -> None:
    for d in (OUTPUT_DIR, RUNTIME_DIR, SLC_DIR):
        d.mkdir(parents=True, exist_ok=True)


def env_or(name: str, default: str) -> str:
    """Env lookup with an explicit default (never raises)."""
    return os.environ.get(name, default)


def env_float(name: str, default: float) -> float:
    """Env float lookup that fails loudly (no raw traceback) on a bad value.

    Unattended cron runs surface confusing tracebacks; a bad timeout should be
    a one-line message instead."""
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        raise SystemExit(f"[config] {name} must be a number, got '{raw!r}'") from None


def decide_fail_fast(*, auto_env: str | None, headless: bool, tty: bool) -> bool:
    """Pure fail-fast decision for unattended runs (unit-testable seam).

    An automated run (cron/CI) with no human at the screen must FAIL fast at a
    blocking step instead of hanging on manual assistance. Priority: an explicit
    FLOW_AUTO_FAILFAST=1 always wins; headless Flow implies unattended; a
    non-TTY stdin (cron/CI) means nobody is there to answer a prompt anyway."""
    if auto_env == "1":
        return True
    if headless:
        return True
    return not tty


def fail_fast_enabled() -> bool:
    """True when blocking steps (manual_assist, ...) must fail and log to
    manual_todo.txt instead of waiting for a human operator."""
    return decide_fail_fast(
        auto_env=os.environ.get("FLOW_AUTO_FAILFAST"),
        headless=flow_headless(),
        tty=sys.stdin.isatty() if hasattr(sys.stdin, "isatty") else False,
    )


def manual_todo_path() -> Path:
    """Where unattended runs log human tasks they refuse to block on."""
    return ROOT / "manual_todo.txt"


def youtube_publish_at(now_override: _dt.datetime | None = None) -> _dt.datetime:
    """Today's publish datetime from YOUTUBE_PUBLISH_TIME ('HH:MM', local) and
    YOUTUBE_PUBLISH_TZ (IANA name; default 'Asia/Karachi'). Used by the GitHub
    Actions cron to compute `publishAt` for the scheduled upload.

    The cron fires ~45 min before the slot, so publish_at is expected to be in
    the future. If today's slot has already passed (late/manual run), it rolls
    over to tomorrow at the configured time so YouTube Data API v3 never rejects
    the scheduled upload with a 400 error (Invalid publishAt date in past).
    """
    import datetime as _dt
    from zoneinfo import ZoneInfo

    hhmm = os.environ.get("YOUTUBE_PUBLISH_TIME", "18:00")
    tz = os.environ.get("YOUTUBE_PUBLISH_TZ", "Asia/Karachi")
    try:
        hour, minute = (int(x) for x in hhmm.split(":"))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except ValueError as exc:
        raise SystemExit(
            f"[config] YOUTUBE_PUBLISH_TIME must be HH:MM in 00:00-23:59, got '{hhmm}'"
        ) from exc
    try:
        zone = ZoneInfo(tz)
    except Exception as exc:  # unknown IANA timezone name
        raise SystemExit(f"[config] bad YOUTUBE_PUBLISH_TZ '{tz}': {exc}") from exc

    now = now_override if now_override is not None else _dt.datetime.now(zone)
    if now.tzinfo is None:
        now = now.replace(tzinfo=zone)
    else:
        now = now.astimezone(zone)

    publish_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if publish_dt <= now:
        publish_dt += _dt.timedelta(days=1)
    return publish_dt


def die(msg: str, code: int = 1) -> None:
    print(f"[error] {msg}", file=sys.stderr)
    raise SystemExit(code)