"""Tests for the LinkedIn weekly-digest notifier (UGC Posts API, weekly-only)."""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from io import BytesIO

import pytest

import src.config as cfg
import src.notifier as nt
from src.models import NormalizedJob
from src.notifier import LinkedInNotifier, build_notifiers


def _job(i: int) -> NormalizedJob:
    return NormalizedJob(
        id=f"id-{i}",
        title=f"ML Engineer {i}",
        title_normalized=f"ml engineer {i}",
        company="OpenAI",
        company_normalized="openai",
        url=f"https://x.com/{i}",
        source="linkedin",
        location="Remote",
        location_type="remote",
        salary_min=None,
        salary_max=None,
        salary_currency=None,
        job_type="full-time",
        posted_date=None,
        fetched_at=datetime.now(timezone.utc),
        tags=["ML"],
        description_snippet="",
    )


def _stats() -> dict:
    return {
        "week_key": "2026-W38",
        "total": 12,
        "by_source": {"linkedin": 5, "indeed": 4, "glassdoor": 3},
        "by_type": {"full-time": 10, "contract": 2},
    }


def test_linkedin_format_weekly_plain_text():
    n = LinkedInNotifier("t", "urn:li:person:abc")
    text = n._format_weekly(_stats(), [_job(1), _job(2)])
    assert "2026-W38" in text
    assert "12" in text
    assert "linkedin" in text
    assert "ML Engineer 1" in text
    assert "https://x.com/1" in text
    assert len(text) < 2900


def test_linkedin_daily_is_skipped():
    n = LinkedInNotifier("t", "urn:li:person:abc")
    assert n.send_daily([_job(1)], {}) is False


def test_linkedin_post_fails_missing_credentials():
    assert LinkedInNotifier("", "urn:li:person:abc")._post_share("text") is False
    assert LinkedInNotifier("tok", "not-a-urn")._post_share("text") is False


def test_linkedin_post_success_sends_proper_payload(monkeypatch):
    captured = {}

    class FakeResp:
        status = 201

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'{"id":"urn:li:share:123"}'

    class FakeOpener:
        def open(self, req, timeout=15):
            captured["timeout"] = timeout
            captured["url"] = req.full_url
            captured["method"] = req.method
            captured["headers"] = dict(req.headers.items())
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResp()

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: FakeOpener())
    n = LinkedInNotifier("sekrit-token", "urn:li:person:abc")
    ok = n._post_share("hello digest")

    assert ok is True
    assert captured["url"] == "https://api.linkedin.com/v2/ugcPosts"
    assert captured["method"] == "POST"
    assert captured["headers"]["Authorization"] == "Bearer sekrit-token"
    assert captured["body"]["author"] == "urn:li:person:abc"
    assert captured["body"]["lifecycleState"] == "PUBLISHED"
    assert captured["body"]["visibility"]["com.linkedin.ugc.MemberNetworkVisibility"] == "PUBLIC"
    assert captured["body"]["specificContent"]["com.linkedin.ugc.ShareContent"]["shareCommentary"]["text"] == "hello digest"


def test_linkedin_post_accepts_202_accepted(monkeypatch):
    class FakeResp:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b""

    monkeypatch.setattr(urllib.request, "build_opener",
                        lambda *_: type("Op", (), {"open": lambda self, req, timeout=15: FakeResp()})())
    n = LinkedInNotifier("t", "urn:li:person:abc")
    assert n._post_share("hello") is True


def test_linkedin_post_redirect_refused_single_request(monkeypatch):
    """A 302 must NOT be followed: urllib would downgrade the POST to a GET and
    forward the Authorization header to the redirect target (token leak). Our
    _RefuseRedirects policy makes it fail closed with exactly one request."""
    calls = []

    class FakeResp:
        status = 302

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"redirect"

    class FakeOpener:
        def open(self, req, timeout=15):
            calls.append(req.full_url)
            return FakeResp()

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: FakeOpener())
    n = LinkedInNotifier("t", "urn:li:person:abc")
    assert n._post_share("hello") is False
    assert len(calls) == 1


def test_linkedin_post_does_not_log_token(monkeypatch):
    logged = []

    class FakeResp:
        status = 400

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'{"serviceErrorCode":100,"message":"bad request"}'

    def fake_opener(*_):
        return type("Op", (), {"open": lambda self, req, timeout=15: FakeResp()})()

    class FakeLog:
        def warning(self, *args, **kwargs):
            logged.append(" ".join(str(a) for a in args))

        def info(self, *args, **kwargs):
            pass

    monkeypatch.setattr(urllib.request, "build_opener", fake_opener)
    monkeypatch.setattr(nt, "log", FakeLog())
    n = LinkedInNotifier("sekrit-token", "urn:li:person:abc")
    ok = n._post_share("hello")
    assert ok is False
    assert "sekrit-token" not in " ".join(logged)


def test_linkedin_post_exception_returns_false(monkeypatch):
    def boom(req, timeout=15):
        raise ConnectionError("network down")

    monkeypatch.setattr(urllib.request, "build_opener",
                        lambda *_: type("Op", (), {"open": boom})())
    n = LinkedInNotifier("t", "urn:li:person:abc")
    assert n._post_share("hello") is False


def test_build_notifiers_includes_linkedin_when_configured(monkeypatch):
    monkeypatch.setenv("NOTIFY_LINKEDIN", "1")
    monkeypatch.setenv("LINKEDIN_POST_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("LINKEDIN_POST_URN", "urn:li:person:abc")
    monkeypatch.setattr(cfg, "notify_telegram", lambda: False)
    monkeypatch.setattr(cfg, "notify_whatsapp", lambda: False)
    ns = build_notifiers()
    assert len(ns) == 1
    assert isinstance(ns[0], LinkedInNotifier)


def test_build_notifiers_skips_linkedin_without_token(monkeypatch):
    monkeypatch.setenv("NOTIFY_LINKEDIN", "1")
    monkeypatch.delenv("LINKEDIN_POST_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(cfg, "notify_telegram", lambda: False)
    monkeypatch.setattr(cfg, "notify_whatsapp", lambda: False)
    assert build_notifiers() == []


def test_telegram_format_weekly_cold_start_empty():
    from src.notifier import TelegramNotifier
    n = TelegramNotifier("tok", "chat")
    text = n._format_weekly({"week_key": "2026-W38", "total": 0}, [])
    assert "2026-W38" in text
    assert "Total jobs found: 0" in text
    assert "Cold-start or quiet week" in text


def test_linkedin_format_weekly_cold_start_empty():
    n = LinkedInNotifier("t", "urn:li:person:abc")
    text = n._format_weekly({"week_key": "2026-W38", "total": 0}, [])
    assert "2026-W38" in text
    assert "Total remote AI/ML jobs found this week: 0" in text
    assert "cold-start or quiet week" in text