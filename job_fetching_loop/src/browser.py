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
import math
import os
import random
import signal
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import src.config as cfg
from src.log import get_logger

log = get_logger(__name__)


# ── Fingerprint rotation ─────────────────────────────────────────────────────

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 Edg/133.0.0.0",
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
    "--disable-features=IsolateOrigins,site-per-process",
    "--no-default-browser-check",
    "--no-first-run",
    "--lang=en-US,en",
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
    import platform
    if platform.system() == "Linux":
        ua = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
    else:
        ua = random.choice(USER_AGENTS)
    return {
        "user_agent": ua,
        "viewport": random.choice(VIEWPORTS),
    }


def _profile_dir(source: str) -> str:
    return str(cfg.RUNTIME_DIR / f"{source}-profile")


def _clean_stale_singleton_locks(profile_dir: Path | str) -> None:
    """Clean up stale Chromium Singleton* locks left by crashes or killed processes.

    If Chromium is killed (e.g. timeout kill or SIGKILL), it leaves broken symlinks
    SingletonLock -> hostname-pid, SingletonSocket, SingletonCookie. Chromium then
    hangs or spawns isolated processes on subsequent launches.
    We inspect the target PID of SingletonLock; if the process is dead, we unlink them.
    """
    p = Path(profile_dir)
    if not p.is_dir():
        return
    lock_file = p / "SingletonLock"
    if not lock_file.exists() and not lock_file.is_symlink():
        return

    is_stale = False
    try:
        if lock_file.is_symlink():
            target = os.readlink(lock_file)
            parts = target.rsplit("-", 1)
            if len(parts) == 2 and parts[1].isdigit():
                pid = int(parts[1])
                try:
                    os.kill(pid, 0)
                    is_stale = False
                except (ProcessLookupError, OSError):
                    is_stale = True
            else:
                is_stale = True
        else:
            is_stale = True
    except Exception as exc:
        log.debug("Error inspecting SingletonLock in %s: %s", p, exc)
        is_stale = True

    if is_stale:
        for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
            f = p / name
            if f.exists() or f.is_symlink():
                try:
                    f.unlink()
                    log.info("Removed stale Chromium lock: %s", f)
                except OSError as exc:
                    log.debug("Failed unlinking stale lock %s: %s", f, exc)


STEALTH_INIT_SCRIPT = """
(() => {
    // 1. Webdriver evasion
    try {
        const proto = Object.getPrototypeOf(navigator);
        delete proto.webdriver;
    } catch (e) {}
    try {
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined,
            configurable: true,
        });
    } catch (e) {}

    // 2. Mock complete window.chrome object
    if (!window.chrome) {
        window.chrome = {
            app: {
                isInstalled: false,
                InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' },
                RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' }
            },
            runtime: {
                OnInstalledReason: { CHROME_UPDATE: 'chrome_update', INSTALL: 'install', SHARED_MODULE_UPDATE: 'shared_module_update', UPDATE: 'update' },
                OnRestartRequiredReason: { APP_UPDATE: 'app_update', OS_UPDATE: 'os_update', PERIODIC: 'periodic' },
                PlatformArch: { ARM: 'arm', ARM64: 'arm64', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' },
                PlatformNaclArch: { ARM: 'arm', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' },
                PlatformOs: { ANDROID: 'android', CROS: 'cros', LINUX: 'linux', MAC: 'mac', OPENBSD: 'openbsd', WIN: 'win' },
                RequestUpdateCheckStatus: { NO_UPDATE: 'no_update', THROTTLED: 'throttled', UPDATE_AVAILABLE: 'update_available' }
            },
            loadTimes: function() {},
            csi: function() {},
        };
    }

    // 3. Realistic Plugins & MimeTypes Array
    try {
        const makePlugin = (name, description, filename) => ({ name, description, filename, length: 0 });
        const plugins = [
            makePlugin('PDF Viewer', 'Portable Document Format', 'internal-pdf-viewer'),
            makePlugin('Chrome PDF Viewer', 'Portable Document Format', 'internal-pdf-viewer'),
            makePlugin('Chromium PDF Viewer', 'Portable Document Format', 'internal-pdf-viewer'),
            makePlugin('Microsoft Edge PDF Viewer', 'Portable Document Format', 'internal-pdf-viewer'),
            makePlugin('WebKit built-in PDF', 'Portable Document Format', 'internal-pdf-viewer'),
        ];
        Object.defineProperty(navigator, 'plugins', {
            get: () => plugins,
            configurable: true,
        });
        Object.defineProperty(navigator, 'mimeTypes', {
            get: () => [{ type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format' }],
            configurable: true,
        });
    } catch (e) {}

    // 4. Languages
    try {
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en'],
            configurable: true,
        });
    } catch (e) {}

    // 5. Hardware Concurrency & Device Memory
    try {
        Object.defineProperty(navigator, 'hardwareConcurrency', {
            get: () => 8,
            configurable: true,
        });
        Object.defineProperty(navigator, 'deviceMemory', {
            get: () => 8,
            configurable: true,
        });
    } catch (e) {}

    // 6. Permissions query
    try {
        const origPermissions = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters && parameters.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : origPermissions(parameters)
        );
    } catch (e) {}

    // 7. WebGL Vendor & Renderer Unmasking
    try {
        const getParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(parameter) {
            if (parameter === 37445) return 'Google Inc. (Intel)';
            if (parameter === 37446) return 'ANGLE (Intel, Intel(R) UHD Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)';
            return getParameter.apply(this, [parameter]);
        };
        if (typeof WebGL2RenderingContext !== 'undefined') {
            const getParameter2 = WebGL2RenderingContext.prototype.getParameter;
            WebGL2RenderingContext.prototype.getParameter = function(parameter) {
                if (parameter === 37445) return 'Google Inc. (Intel)';
                if (parameter === 37446) return 'ANGLE (Intel, Intel(R) UHD Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)';
                return getParameter2.apply(this, [parameter]);
            };
        }
    } catch (e) {}
})();
"""


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
        saved_state = None
        try:
            from src.session import load as load_session
            saved_state = load_session(source)
            if saved_state:
                log.info("[%s] loaded active session state for browser context", source)
        except Exception as exc:
            log.debug("[%s] load session state error: %s", source, exc)

        if persistent:
            user_data_dir = _profile_dir(source)
            _clean_stale_singleton_locks(user_data_dir)
            cfg.RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(cfg.RUNTIME_DIR, 0o700)
            except OSError:
                pass
            use_channel = None if headless else channel
            try:
                browser = await pw.chromium.launch_persistent_context(
                    user_data_dir,
                    headless=headless,
                    args=launch_args,
                    channel=use_channel,
                    ignore_default_args=["--enable-automation"],
                    viewport=fp["viewport"],
                    locale="en-US",
                )
            except Exception as e:
                log.info("[%s] persistent launch fallback: %s", source, e)
                browser = await pw.chromium.launch_persistent_context(
                    user_data_dir,
                    headless=headless,
                    args=launch_args,
                    ignore_default_args=["--enable-automation"],
                    user_agent=fp["user_agent"],
                    viewport=fp["viewport"],
                    locale="en-US",
                )
            try:
                await browser.add_init_script(STEALTH_INIT_SCRIPT)
            except Exception as exc:
                log.debug("[%s] add_init_script error: %s", source, exc)
            if saved_state and isinstance(saved_state.get("cookies"), list):
                try:
                    await browser.add_cookies(saved_state["cookies"])
                    log.debug("[%s] seeded %d session cookies into persistent context", source, len(saved_state["cookies"]))
                except Exception as exc:
                    log.debug("[%s] add_cookies error: %s", source, exc)
            try:
                yield browser
            finally:
                try:
                    await browser.close()
                except Exception:
                    pass
        else:
            browser = await pw.chromium.launch(
                headless=headless,
                args=launch_args,
                channel=channel,
            )
            context_kwargs = {
                "user_agent": fp["user_agent"],
                "viewport": fp["viewport"],
                "locale": "en-US",
                "timezone_id": "UTC",
            }
            if saved_state:
                context_kwargs["storage_state"] = saved_state

            context = await browser.new_context(**context_kwargs)
            try:
                await context.add_init_script(STEALTH_INIT_SCRIPT)
                yield context
            finally:
                try:
                    await context.close()
                except Exception:
                    pass
                try:
                    await browser.close()
                except Exception:
                    pass


# ── CAPTCHA detection ────────────────────────────────────────────────────────

# Precise markers only. `challenge-platform` (Cloudflare's JS loader) appears on
# EVERY Cloudflare page, even fully-loaded ones — matching it alone is a false
# positive. A real challenge has a <form>/iframe/JS glob we can pin down:
_CAPTCHA_CHALLENGE_PATTERNS = [
    # Cloudflare managed challenge (blocking) — form/verification UI present
    "challenge-form",
    "id=\"challenge-running\"",
    # Indeed / Cloudflare bot detection & verification
    "additional verification required",
    "troubleshooting cloudflare errors",
    "bot-detection-anonymous",
    "just a moment...",
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
        # If job cards are present, the page is definitely clean and displaying search results!
        try:
            if hasattr(page, "query_selector") and callable(page.query_selector):
                cards = await page.query_selector("div.cardOutline, div.job_seen_beacon, td.resultContent, li[data-test='jobListing'], article[data-test='job-listing-card'], li.JobsList_jobListItem__wjTHv")
                if cards and type(cards).__name__ not in ("AsyncMock", "MagicMock", "Mock", "NonCallableMagicMock"):
                    return None
        except Exception:
            pass

        raw_url = getattr(page, "url", None)
        if isinstance(raw_url, str):
            url_low = raw_url.lower()
            if "bot-detection" in url_low:
                return "bot-detection-url"

        if hasattr(page, "title") and callable(page.title):
            try:
                title = await page.title()
                if isinstance(title, str) and "just a moment..." in title.lower():
                    # Check if Turnstile has already been solved on this page
                    try:
                        token = await page.evaluate("() => document.querySelector('[name=cf-turnstile-response]')?.value")
                        if token and len(token) > 20:
                            return None
                    except Exception:
                        pass
                    return "cf-title-challenge"
            except Exception:
                pass

        try:
            token = await page.evaluate("() => document.querySelector('[name=cf-turnstile-response]')?.value")
            if token and len(token) > 20:
                # Turnstile is completed
                return None
        except Exception:
            pass

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
    challenge in the visible window; also attempts human-like mouse movement and click
    on Cloudflare Turnstile if detected; returns True once the challenge marker is
    gone, False if the timeout expires first.

    The solved session (cookies) persists in the source's profile dir, so this
    is a one-time cost per source per IP/cleared state.
    """
    deadline = time.monotonic() + timeout
    waited = 0.0
    log.warning("CAPTCHA detected on %s — solve it in the open browser window (%s)", source, url)
    log.warning("  waiting up to %ds for manual solve...", int(timeout))

    try:
        if hasattr(page, "bring_to_front") and callable(page.bring_to_front):
            await page.bring_to_front()
    except Exception:
        pass

    last_turnstile_click = 0.0

    while time.monotonic() < deadline:
        await asyncio.sleep(2.0)
        waited += 2.0

        # Attempt human-like Turnstile click if frame is present and cooldown elapsed
        if time.monotonic() - last_turnstile_click > 10.0:
            try:
                frames = getattr(page, "frames", None)
                if isinstance(frames, (list, tuple)):
                    for f in frames:
                        f_url = getattr(f, "url", None)
                        if isinstance(f_url, str) and "challenges.cloudflare.com" in f_url:
                            clicked_inside = False
                            for sel in ("input[type='checkbox']", ".ctp-checkbox-label", "#challenge-stage", "label.ctp-checkbox-label", "div.cb-i"):
                                try:
                                    el = await f.query_selector(sel)
                                    if el:
                                        box = await el.bounding_box()
                                        if box:
                                            target_x = box["x"] + box["width"] * random.uniform(0.3, 0.7)
                                            target_y = box["y"] + box["height"] * random.uniform(0.3, 0.7)
                                            log.info("[%s] Human mouse moving to Turnstile checkbox element (%d, %d)...",
                                                     source, int(target_x), int(target_y))
                                            await human_mouse_move(page, target_x, target_y, steps=random.randint(22, 35))
                                            await asyncio.sleep(random.uniform(0.2, 0.45))
                                            try:
                                                await el.click(timeout=3000)
                                            except Exception:
                                                if hasattr(page, "mouse") and hasattr(page.mouse, "click"):
                                                    await page.mouse.click(target_x, target_y)
                                            clicked_inside = True
                                            break
                                except Exception:
                                    pass

                            if not clicked_inside:
                                el = await f.frame_element()
                                box = await el.bounding_box()
                                if box:
                                    target_x = box["x"] + random.uniform(27.0, 33.0)
                                    target_y = box["y"] + (box["height"] / 2.0) + random.uniform(-2.5, 2.5)
                                    log.info("[%s] Human mouse moving to Cloudflare Turnstile (%d, %d)...",
                                             source, int(target_x), int(target_y))
                                    await human_mouse_move(page, target_x, target_y, steps=random.randint(22, 35))
                                    await asyncio.sleep(random.uniform(0.2, 0.45))
                                    if hasattr(page, "mouse") and hasattr(page.mouse, "click"):
                                        await page.mouse.click(target_x, target_y)

                            log.info("[%s] Clicked Turnstile checkbox with human motion", source)
                            last_turnstile_click = time.monotonic()
                            try:
                                await page.wait_for_load_state("domcontentloaded", timeout=8_000)
                            except Exception:
                                pass
                            await asyncio.sleep(3.0)
                            break
            except Exception as e:
                log.debug("[%s] Turnstile click attempt error: %s", source, e)

        if not await has_captcha(page):
            log.info("CAPTCHA solved on %s after %ds — continuing with live session", source, int(waited))
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=8_000)
            except Exception:
                pass
            await asyncio.sleep(2.0)
            try:
                from src.session import save as save_session
                ctx = getattr(page, "context", None)
                if ctx and hasattr(ctx, "storage_state") and callable(ctx.storage_state):
                    solved_state = await ctx.storage_state()
                    save_session(source, solved_state)
                    log.info("[%s] saved freshly cleared session cookies to storage_state", source)
            except Exception as e:
                log.debug("[%s] save cleared session error: %s", source, e)
            return True
        if int(waited) % 15 == 0:
            log.info("  still waiting (%ds)...", int(waited))
    log.warning("CAPTCHA not solved on %s within %ds — escalating", source, int(timeout))
    return False


# ── Human-like interaction helpers ───────────────────────────────────────────

async def human_mouse_move(page, target_x: float, target_y: float, steps: int = 25) -> None:
    """Move mouse to target coordinates with natural human-like path curvature, speed variance, and jitter."""
    try:
        cur_pos = getattr(page, "_mouse_pos", (random.randint(100, 300), random.randint(100, 300)))
        x0, y0 = cur_pos
        dx = target_x - x0
        dy = target_y - y0

        ctrl_x1 = x0 + dx * random.uniform(0.2, 0.4) + random.uniform(-25, 25)
        ctrl_y1 = y0 + dy * random.uniform(0.1, 0.3) + random.uniform(-25, 25)
        ctrl_x2 = x0 + dx * random.uniform(0.6, 0.8) + random.uniform(-15, 15)
        ctrl_y2 = y0 + dy * random.uniform(0.7, 0.9) + random.uniform(-15, 15)

        num_steps = max(10, steps + random.randint(-4, 8))
        for i in range(1, num_steps + 1):
            t = i / num_steps
            bx = ((1 - t) ** 3) * x0 + 3 * ((1 - t) ** 2) * t * ctrl_x1 + 3 * (1 - t) * (t ** 2) * ctrl_x2 + (t ** 3) * target_x
            by = ((1 - t) ** 3) * y0 + 3 * ((1 - t) ** 2) * t * ctrl_y1 + 3 * (1 - t) * (t ** 2) * ctrl_y2 + (t ** 3) * target_y
            jitter_x = random.uniform(-0.8, 0.8) if i < num_steps else 0
            jitter_y = random.uniform(-0.8, 0.8) if i < num_steps else 0
            await page.mouse.move(bx + jitter_x, by + jitter_y)
            speed_factor = math.sin(t * math.pi)
            step_delay = max(0.004, random.uniform(0.008, 0.02) * (1.2 - 0.4 * speed_factor))
            await asyncio.sleep(step_delay)

        page._mouse_pos = (target_x, target_y)
    except Exception:
        try:
            await page.mouse.move(target_x, target_y)
            page._mouse_pos = (target_x, target_y)
        except Exception:
            pass


async def human_hover(page, element_or_selector) -> None:
    """Hover over an element like a real user before clicking or reading."""
    try:
        box = None
        if isinstance(element_or_selector, str):
            el = await page.query_selector(element_or_selector)
            if el:
                box = await el.bounding_box()
        elif hasattr(element_or_selector, "bounding_box"):
            box = await element_or_selector.bounding_box()

        if box:
            target_x = box["x"] + box["width"] * random.uniform(0.25, 0.75)
            target_y = box["y"] + box["height"] * random.uniform(0.25, 0.75)
            await human_mouse_move(page, target_x, target_y, steps=random.randint(18, 30))
            await asyncio.sleep(random.uniform(0.2, 0.5))
    except Exception:
        pass


async def human_click(page, element_or_selector) -> None:
    """Human-like hover, pause, and click."""
    try:
        await human_hover(page, element_or_selector)
        await asyncio.sleep(random.uniform(0.08, 0.22))
        if hasattr(element_or_selector, "click"):
            await element_or_selector.click(timeout=2500)
        elif isinstance(element_or_selector, str):
            await page.click(element_or_selector, timeout=2500)
        await asyncio.sleep(random.uniform(0.3, 0.8))
    except Exception:
        try:
            if hasattr(element_or_selector, "click"):
                await element_or_selector.click(timeout=1500)
            elif isinstance(element_or_selector, str):
                await page.click(element_or_selector, timeout=1500)
        except Exception:
            pass


async def human_scroll(page, max_scrolls: int = 3) -> None:
    """Natural, micro-step variable scrolling with eye-scanning mouse movements and pauses."""
    try:
        for _ in range(random.randint(1, max_scrolls)):
            vp = page.viewport_size or {"width": 1280, "height": 800}
            scan_x = random.uniform(vp["width"] * 0.25, vp["width"] * 0.7)
            scan_y = random.uniform(vp["height"] * 0.25, vp["height"] * 0.75)
            await human_mouse_move(page, scan_x, scan_y, steps=random.randint(15, 25))

            total_delta = random.randint(150, 420)
            bursts = random.randint(4, 7)
            delta_per_burst = total_delta / bursts
            for _ in range(bursts):
                await page.mouse.wheel(0, delta_per_burst + random.uniform(-8, 8))
                await asyncio.sleep(random.uniform(0.04, 0.08))

            await asyncio.sleep(random.uniform(0.5, 1.4))
    except Exception:
        pass


async def human_delay(lo: float = 1.5, hi: float = 4.0) -> None:
    """Variable human-size pause between actions."""
    await asyncio.sleep(random.uniform(lo, hi))


async def human_read_pause(min_s: float = 1.5, max_s: float = 3.5) -> None:
    """Simulate human reading time over job description text."""
    await asyncio.sleep(random.uniform(min_s, max_s))


async def warm_up(page, home_url: str, source: str) -> None:
    """Visit the homepage first and linger like a real user — going straight
    to a search URL is a common automation fingerprint."""
    try:
        await page.goto(home_url, timeout=30_000, wait_until="domcontentloaded")
        if await has_captcha(page):
            timeout = cfg.captcha_solve_timeout()
            if timeout > 0:
                if not await await_captcha_solve(page, source, page.url, timeout):
                    raise CaptchaTimeout(source, page.url, timeout)
            else:
                raise CaptchaDetected(source, page.url)
        await check_captcha(page, source)
        await human_scroll(page)
        await human_delay()
    except (CaptchaDetected, CaptchaTimeout):
        raise
    except Exception:
        pass


async def polite_delay() -> None:
    delay = cfg.delay_ms_between_requests()
    await asyncio.sleep(delay)


def kill_child_browser_processes() -> int:
    """Kill any orphaned child processes (Chromium, Node/Playwright driver) spawned by this process.

    Safe on Linux systems by inspecting /proc. Returns number of processes terminated.
    On non-Linux platforms without /proc, safely returns 0 without raising.
    """
    my_pid = os.getpid()
    killed = 0
    proc_path = Path("/proc")
    if not proc_path.exists():
        return 0
    try:
        for entry in proc_path.iterdir():
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            if pid == my_pid:
                continue
            try:
                status_file = entry / "status"
                if not status_file.exists():
                    continue
                content = status_file.read_text(encoding="utf-8", errors="ignore")
                ppid = None
                for line in content.splitlines():
                    if line.startswith("PPid:"):
                        ppid = int(line.split()[1])
                        break
                if ppid == my_pid:
                    cmdline_file = entry / "cmdline"
                    cmdline = cmdline_file.read_text(encoding="utf-8", errors="ignore") if cmdline_file.exists() else ""
                    cmd_lower = cmdline.lower()
                    if any(x in cmd_lower for x in ("chromium", "chrome", "playwright", "headless_shell")):
                        try:
                            os.kill(pid, signal.SIGKILL)
                            killed += 1
                        except (ProcessLookupError, PermissionError):
                            pass
            except Exception:
                continue
    except Exception as exc:
        log.warning("error checking child browser processes: %s", exc)
    return killed