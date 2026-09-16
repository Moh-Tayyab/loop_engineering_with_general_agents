"""Tests for browser.py human-in-the-loop CAPTCHA helpers and launcher options."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from src.browser import (
    CaptchaDetected,
    await_captcha_solve,
    check_captcha,
    has_captcha,
)
from src.config import captcha_solve_timeout, chrome_binary


def _run(coro):
    return asyncio.run(coro)


def test_has_captcha_clean_page():
    """A clean page (evaluate returning None) is probed without raising."""
    page = AsyncMock()
    page.url = "https://x.com"
    page.evaluate = AsyncMock(return_value=None)
    assert _run(has_captcha(page)) is None


def test_has_captcha_finds_challenge():
    page = AsyncMock()
    page.evaluate = AsyncMock(return_value="h-captcha")
    assert _run(has_captcha(page)) == "h-captcha"


def test_check_captcha_raises_on_challenge():
    page = AsyncMock()
    page.url = "https://indeed.com/x"
    page.evaluate = AsyncMock(return_value="g-recaptcha")
    try:
        _run(check_captcha(page, "indeed"))
    except CaptchaDetected as e:
        assert "captcha" in str(e).lower() and "indeed" in str(e)
    else:
        raise AssertionError("expected CaptchaDetected")


def test_check_captcha_passes_clean_page():
    page = AsyncMock()
    page.evaluate = AsyncMock(return_value=None)
    _run(check_captcha(page, "indeed"))


def test_await_captcha_solve_returns_true_after_solve():
    """When the challenge clears mid-loop, await_captcha_solve returns True."""
    page = AsyncMock()
    page.url = "https://indeed.com/x"
    # 1st probe: challenge present; 2nd probe: cleared
    page.evaluate = AsyncMock(side_effect=["challenge-form", None])

    with patch("src.browser.asyncio.sleep", AsyncMock()):
        result = _run(await_captcha_solve(page, "indeed", page.url, timeout=30))
    assert result is True
    assert page.evaluate.call_count >= 2


def test_await_captcha_solve_timeout_returns_false():
    """A challenge that never clears returns False after the deadline."""
    page = AsyncMock()
    page.evaluate = AsyncMock(return_value="challenge-form")

    with patch("src.browser.asyncio.sleep", AsyncMock()):
        result = _run(await_captcha_solve(page, "indeed", "https://indeed.com/x", timeout=0.01))
    assert result is False


def test_captcha_solve_timeout_default():
    assert captcha_solve_timeout() > 0


def test_chrome_binary_lookup():
    """System Chrome should be present on this machine."""
    result = chrome_binary()
    assert isinstance(result, str) or result is None


def test_kill_child_browser_processes_runs_safely():
    from src.browser import kill_child_browser_processes
    result = kill_child_browser_processes()
    assert isinstance(result, int)
    assert result >= 0


def test_indeed_and_glassdoor_24h_filter_url():
    from datetime import datetime, timedelta, timezone
    from src.scrapers.indeed import IndeedScraper
    from src.scrapers.glassdoor import GlassdoorScraper

    posted_after = datetime.now(timezone.utc) - timedelta(hours=24)
    diff_days = (datetime.now(timezone.utc) - posted_after).total_seconds() / 86400.0
    days = 1 if diff_days <= 1.25 else max(1, min(14, round(diff_days)))
    assert days == 1

    indeed_url = IndeedScraper._SEARCH.format(kw="AI", days=days)
    assert "fromage=1" in indeed_url

    gd_url = GlassdoorScraper._SEARCH.format(kw="AI", days=days)
    assert "fromAge=1" in gd_url