"""Playwright stealth launcher: anti-detection browser management.

Each source gets its own browser instance. For anti-bot sources (Indeed,
Glassdoor) we use a persistent, headed, system-Chrome profile so a human can
solve CAPTCHAs once and the session (cookies) is reused on every later run.

Human-in-the-loop CAPTCHA:
  - `await_captcha_solve()` keeps the page open and polls until the challenge
    disappears (the human solves it in the visible browser), then returns.
  - `has_captcha()` is a non-raising probe used by that loop.
  - Session persists in `.runtime/<source>-profile/`, so a solved lunch is a
    one-time cost per source.

Human-like behavior (to stay under Cloudflare's radar):
  - warm-up homepage visit before search pages
  - random scroll/mouse movement on the page
  - variable, human-sized delays (not fixed cadence)
"""
from __future__ import annotations

import asyncio
import random
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

import src.config as cfg
from src.log import get_logger

log = get_logger(__name__)


# ── Fingerprint rotation ─────────────────────────────────────────────────────

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
]

VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
    {"width": 1280, "height": 720},
]

STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
    "--no-sandbox",
    "--disable-infobars",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
]


# ── Exceptions ───────────────────────────────────────────────────────────────

class CaptchaDetected(Exception):
    """Raised when a page presents a CAPTCHA and we choose not to auto-wait."""
    def __init__(self, source: str, url: str):
        self.source = source
        self.url = url
        super().__init__(f"CAPTCHA detected on {source}: {url}")


class CaptchaTimeout(Exception):
    """Raised when a CAPTCHA is not solved within the human-in-the-loop window.

    Not swallowed: the source loop records it as a circuit-breaker failure so a
    blocked source escalates instead of silently returning nothing every day."""
    def __init__(self, source: str, url: str, timeout: float):
        self.source = source
        self.url = url
        super().__init__(f"CAPTCHA not solved within {timeout:.0f}s on {source}: {url}")


class SourceUnavailable(Exception):
    """Raised when a pre-flight check shows the source is down."""
    def __init__(self, source: str, reason: str):
        self.source = source
        super().__init__(f"source {source} unavailable: {reason}")


# ── Browser launcher ─────────────────────────────────────────────────────────

def _fingerprint() -> dict:
    return {
        "user_agent": random.choice(USER_AGENTS),
        "viewport": random.choice(VIEWPORTS),
    }


def _profile_dir(source: str) -> str:
    return str(cfg.RUNTIME_DIR / f"{source}-profile")


@asynccontextmanager
async def launch_browser(
    source: str,
    *,
    headless: bool | None = None,
    persistent: bool = False,
) -> AsyncIterator:
    """Launch a Playwright browser with stealth fingerprinting.

    Args:
        source: source name (used for profile dir when persistent=True)
        headless: override from env
        persistent: True for login-gated / anti-bot sources (Indeed, Glassdoor).
            With persistent=True the session lives in `.runtime/<source>-profile`
            so a solved CAPTCHA / login is reused on every later run.
    """
    from playwright.async_api import async_playwright

    headless = headless if headless is not None else cfg.scrape_headless()
    fp = _fingerprint()
    channel = cfg.chrome_binary() and "chrome"

    async with async_playwright() as pw:
        launch_args = list(STEALTH_ARGS)
        if persistent:
            user_data_dir = _profile_dir(source)
            cfg.RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
            try:
                browser = await pw.chromium.launch_persistent_context(
                    user_data_dir,
                    headless=headless,
                    args=launch_args,
                    channel=None if headless else channel,
                    user_agent=fp["user_agent"],
                    viewport=fp["viewport"],
                    locale="en-US",
                    timezone_id="UTC",
                )
            except Exception as e:
                log.info("[%s] persistent launch fallback: %s", source, e)
                browser = await pw.chromium.launch_persistent_context(
                    user_data_dir,
                    headless=headless,
                    args=launch_args,
                    user_agent=fp["user_agent"],
                    viewport=fp["viewport"],
                    locale="en-US",
                    timezone_id="UTC",
                )
            try:
                yield browser
            finally:
                await browser.close()
        else:
            browser = await pw.chromium.launch(
                headless=headless,
                args=launch_args,
                channel=channel,
            )
            context = await browser.new_context(
                user_agent=fp["user_agent"],
                viewport=fp["viewport"],
                locale="en-US",
                timezone_id="UTC",
            )
            try:
                yield context
            finally:
                await context.close()
                await browser.close()


# ── CAPTCHA detection ────────────────────────────────────────────────────────

# Precise markers only. `challenge-platform` (Cloudflare's JS loader) appears on
# EVERY Cloudflare page, even fully-loaded ones — matching it alone is a false
# positive. A real challenge has a <form>/iframe/JS glob we can pin down:
_CAPTCHA_CHALLENGE_PATTERNS = [
    # Cloudflare managed challenge (blocking) — form/verification UI present
    "challenge-form",
    "cf-chl-",
    "id=\"challenge-running\"",
    # hCaptcha / reCAPTCHA widgets actively rendered
    "h-captcha",
    "g-recaptcha",
    "recaptcha/api",
    # Human-verification prompts
    "verify you are human",
    "switch to required browser to continue",
    "enable javascript and cookies to continue",
]


async def has_captcha(page) -> str | None:
    """Return the matching challenge pattern, or None if the page is clean."""
    try:
        return await page.evaluate(
            """() => {
                const patterns = %s;
                const html = document.documentElement ? document.documentElement.outerHTML : "";
                const hay = html.length > 500000 ? html.slice(0, 500000) : html;
                const low = hay.toLowerCase();
                for (const p of patterns) {
                    if (low.includes(p)) return p;
                }
                return null;
            }"""
            % (repr(_CAPTCHA_CHALLENGE_PATTERNS)),
        )
    except Exception:
        # evaluate() failing (nav in progress) is not necessarily a captcha
        return None


async def check_captcha(page, source: str) -> None:
    """Raise CaptchaDetected only when a REAL challenge widget is present.

    Uses an in-page script instead of a substring scan of the whole body: the
    page may be huge and Cloudflare's loader always ships with the string
    'challenge-platform', which would otherwise fire a false positive on every
    healthy scrape.
    """
    result = await has_captcha(page)
    if result:
        raise CaptchaDetected(source, page.url)


async def await_captcha_solve(page, source: str, url: str, timeout: float = 300.0) -> bool:
    """Human-in-the-loop CAPTCHA solve.

    The browser stays OPEN and HEADED. Prints a prompt so the human solves the
    challenge in the visible window; returns True once the challenge marker is
    gone, False if the timeout expires first.

    The solved session (cookies) persists in the source's profile dir, so this
    is a one-time cost per source per IP/cleared state.
    """
    deadline = time.monotonic() + timeout
    waited = 0.0
    log.warning("CAPTCHA detected on %s — solve it in the open browser window (%s)", source, url)
    log.warning("  waiting up to %ds for manual solve...", int(timeout))
    while time.monotonic() < deadline:
        await asyncio.sleep(3)
        waited += 3
        if not await has_captcha(page):
            log.info("CAPTCHA solved on %s after %ds — continuing with live session", source, int(waited))
            await asyncio.sleep(1.5)
            return True
        if int(waited) % 15 == 0:
            log.info("  still waiting (%ds)...", int(waited))
    log.warning("CAPTCHA not solved on %s within %ds — escalating", source, int(timeout))
    return False


# ── Human-like interaction helpers ───────────────────────────────────────────

async def human_scroll(page, max_scrolls: int = 3) -> None:
    """Natural, variable-speed page scrolling a person would do."""
    try:
        for _ in range(random.randint(1, max_scrolls)):
            await page.mouse.move(random.randint(200, 1400), random.randint(150, 600))
            await page.mouse.wheel(0, random.randint(150, 500))
            await asyncio.sleep(random.uniform(0.4, 1.2))
    except Exception:
        pass


async def human_delay(lo: float = 1.5, hi: float = 4.0) -> None:
    """Variable human-size pause between actions."""
    await asyncio.sleep(random.uniform(lo, hi))


async def warm_up(page, home_url: str, source: str) -> None:
    """Visit the homepage first and linger like a real user — going straight
    to a search URL is a common automation fingerprint."""
    try:
        await page.goto(home_url, timeout=30_000, wait_until="domcontentloaded")
        await check_captcha(page, source)
        await human_scroll(page)
        await human_delay()
    except CaptchaDetected:
        raise
    except Exception:
        pass


async def polite_delay() -> None:
    delay = cfg.delay_ms_between_requests()
    await asyncio.sleep(delay)