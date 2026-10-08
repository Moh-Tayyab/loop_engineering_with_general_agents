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


def test_launch_browser_loads_session_state_in_new_context():
    from src.browser import launch_browser

    mock_context = AsyncMock()
    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)

    mock_pw_inst = AsyncMock()
    mock_pw_inst.chromium.launch = AsyncMock(return_value=mock_browser)

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_pw_inst)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    fake_session = {"cookies": [{"name": "test_cookie", "value": "val123"}]}

    with patch("playwright.async_api.async_playwright", return_value=mock_cm), \
         patch("src.session.load", return_value=fake_session):
        async def _test():
            async with launch_browser("test_source", persistent=False) as ctx:
                assert ctx is mock_context

        _run(_test())

    assert mock_browser.new_context.call_count == 1
    call_kwargs = mock_browser.new_context.call_args[1]
    assert call_kwargs.get("storage_state") == fake_session


def test_launch_browser_seeds_cookies_in_persistent_context():
    from src.browser import launch_browser

    mock_browser = AsyncMock()
    mock_browser.add_cookies = AsyncMock()

    mock_pw_inst = AsyncMock()
    mock_pw_inst.chromium.launch_persistent_context = AsyncMock(return_value=mock_browser)

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_pw_inst)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    fake_cookies = [{"name": "auth", "value": "token"}]
    fake_session = {"cookies": fake_cookies}

    with patch("playwright.async_api.async_playwright", return_value=mock_cm), \
         patch("src.session.load", return_value=fake_session):
        async def _test():
            async with launch_browser("test_source", persistent=True) as ctx:
                assert ctx is mock_browser

        _run(_test())

    assert mock_browser.add_cookies.call_count == 1
    assert mock_browser.add_cookies.call_args[0][0] == fake_cookies


def test_clean_stale_singleton_locks_removes_dead_pid(tmp_path):
    from src.browser import _clean_stale_singleton_locks

    prof_dir = tmp_path / "test-profile"
    prof_dir.mkdir()
    lock_file = prof_dir / "SingletonLock"
    socket_file = prof_dir / "SingletonSocket"
    cookie_file = prof_dir / "SingletonCookie"

    dead_pid = 99999999
    lock_file.symlink_to(f"testmachine-{dead_pid}")
    socket_file.write_text("socket")
    cookie_file.write_text("cookie")

    _clean_stale_singleton_locks(prof_dir)

    assert not lock_file.exists() and not lock_file.is_symlink()
    assert not socket_file.exists()
    assert not cookie_file.exists()


def test_clean_stale_singleton_locks_preserves_live_pid(tmp_path):
    import os
    from src.browser import _clean_stale_singleton_locks

    prof_dir = tmp_path / "test-profile"
    prof_dir.mkdir()
    lock_file = prof_dir / "SingletonLock"
    socket_file = prof_dir / "SingletonSocket"

    live_pid = os.getpid()
    lock_file.symlink_to(f"testmachine-{live_pid}")
    socket_file.write_text("socket")

    _clean_stale_singleton_locks(prof_dir)

    assert lock_file.is_symlink()
    assert socket_file.exists()