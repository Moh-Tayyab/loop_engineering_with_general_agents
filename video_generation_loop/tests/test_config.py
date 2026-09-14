"""Tests for planner selection and account-gate helpers."""
from __future__ import annotations

import src.config as cfg


def test_planner_source_defaults_to_template():
    assert cfg.planner_source() == "template"


def test_use_gemini_false_by_default(monkeypatch):
    monkeypatch.delenv("FLOW_PLANNER", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert cfg.use_gemini() is False


def test_use_gemini_requires_opt_in_and_key(monkeypatch):
    monkeypatch.setenv("FLOW_PLANNER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    # opt-in but no key -> still template (never demand a key implicitly)
    assert cfg.use_gemini() is False

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    assert cfg.use_gemini() is True
    monkeypatch.setenv("FLOW_PLANNER", "template")
    # key present but planner not opted in -> template wins
    assert cfg.use_gemini() is False


def test_youtube_publish_at_future_schedules_today(monkeypatch):
    import datetime as _dt
    from zoneinfo import ZoneInfo

    monkeypatch.setenv("YOUTUBE_PUBLISH_TIME", "18:00")
    monkeypatch.setenv("YOUTUBE_PUBLISH_TZ", "Asia/Karachi")

    tz = ZoneInfo("Asia/Karachi")
    mock_now = _dt.datetime(2026, 8, 31, 10, 0, 0, tzinfo=tz)
    pub = cfg.youtube_publish_at(now_override=mock_now)

    assert pub.year == 2026
    assert pub.month == 8
    assert pub.day == 31
    assert pub.hour == 18
    assert pub.minute == 0
    assert pub > mock_now


def test_youtube_publish_at_past_rolls_over_to_tomorrow(monkeypatch):
    import datetime as _dt
    from zoneinfo import ZoneInfo

    monkeypatch.setenv("YOUTUBE_PUBLISH_TIME", "18:00")
    monkeypatch.setenv("YOUTUBE_PUBLISH_TZ", "Asia/Karachi")

    tz = ZoneInfo("Asia/Karachi")
    mock_now = _dt.datetime(2026, 8, 31, 20, 30, 0, tzinfo=tz)
    pub = cfg.youtube_publish_at(now_override=mock_now)

    assert pub.year == 2026
    assert pub.month == 9
    assert pub.day == 1
    assert pub.hour == 18
    assert pub.minute == 0
    assert pub > mock_now


def test_youtube_publish_at_invalid_time_raises(monkeypatch):
    import pytest

    monkeypatch.setenv("YOUTUBE_PUBLISH_TIME", "25:00")
    with pytest.raises(SystemExit) as exc:
        cfg.youtube_publish_at()
    assert "YOUTUBE_PUBLISH_TIME must be HH:MM" in str(exc.value)


def test_youtube_publish_at_invalid_tz_raises(monkeypatch):
    import pytest

    monkeypatch.setenv("YOUTUBE_PUBLISH_TIME", "18:00")
    monkeypatch.setenv("YOUTUBE_PUBLISH_TZ", "Invalid/Timezone")
    with pytest.raises(SystemExit) as exc:
        cfg.youtube_publish_at()
    assert "bad YOUTUBE_PUBLISH_TZ" in str(exc.value)


# --- Beat 3 fail-fast decision (unattended runs must not block a hallway) ---

def test_decide_fail_fast_explicit_auto_always_wins():
    assert cfg.decide_fail_fast(auto_env="1", headless=False, tty=True) is True


def test_decide_fail_fast_headless_implies_unattended():
    assert cfg.decide_fail_fast(auto_env=None, headless=True, tty=True) is True


def test_decide_fail_fast_non_tty_is_unattended():
    assert cfg.decide_fail_fast(auto_env=None, headless=False, tty=False) is True


def test_decide_fail_fast_interactive_stays_blocking():
    assert cfg.decide_fail_fast(auto_env=None, headless=False, tty=True) is False


def test_manual_todo_path_is_project_root_file():
    assert cfg.manual_todo_path().name == "manual_todo.txt"
    assert cfg.manual_todo_path().parent == cfg.ROOT