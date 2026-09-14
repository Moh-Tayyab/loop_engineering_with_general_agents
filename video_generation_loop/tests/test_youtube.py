"""Tests for the YouTube Data API uploader + SEO metadata builder."""
from __future__ import annotations

import datetime as _dt
import zoneinfo
from types import SimpleNamespace

import pytest

import src.config as cfg
import src.youtube_upload as yt
from src.state import Topic

UTC = _dt.timezone.utc


def _topic():
    return Topic("c07", "Plan Mode", "Break big problems into small tasks an AI can run.")


def _future(time: str = "18:00") -> _dt.datetime:
    tz = zoneinfo.ZoneInfo("Asia/Karachi")
    now = _dt.datetime.now(tz).replace(hour=18, minute=0, second=0, microsecond=0)
    return now + _dt.timedelta(days=1)


# --------------------------------------------------------------------------- SEO
def test_seo_title_is_bounded_and_keyword_first():
    body = yt.seo_document(_topic(), "Kya hota hai?", publish_at=_future())
    title = body["snippet"]["title"]
    assert len(title) <= yt.MAX_TITLE_LEN
    assert "Plan Mode" in title  # topic keyword first
    assert "#Shorts" in title


def test_seo_status_schedules_private_upload():
    when = _future()
    body = yt.seo_document(_topic(), "hook", publish_at=when)
    status = body["status"]
    assert status["privacyStatus"] == "private"
    assert status["publishAt"] == when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert status["selfDeclaredMadeForKids"] is False


def test_seo_description_has_cta_and_hashtags():
    body = yt.seo_document(_topic(), "hook", publish_at=_future())
    desc = body["snippet"]["description"]
    assert "SUBSCRIBE" in desc
    assert "#Shorts" in desc
    assert "Plan Mode" in desc


def test_seo_tags_are_deduplicated_and_default_present():
    body = yt.seo_document(_topic(), "hook", publish_at=_future())
    tags = body["snippet"]["tags"]
    assert len(tags) == len(set(tags))
    assert "shorts" in tags
    assert "plan" in tags  # derived from topic title


def test_seo_uses_education_category_and_language():
    body = yt.seo_document(_topic(), "hook", publish_at=_future())
    assert body["snippet"]["categoryId"] == "27"
    assert body["snippet"]["defaultLanguage"] == "hi"


# --------------------------------------------------------------------------- upload
class _FakeRequest:
    def next_chunk(self):
        return None, {"id": "yt-abc123"}


class _FakeUploadYT:
    """Minimal stand-in for googleapiclient's youtube service."""

    def __init__(self):
        self.thumb_called = False
        self.fake = self

    def videos(self):
        return type("_V", (), {"insert": lambda self, **kw: _FakeRequest()})()

    def thumbnails(self):
        fake = self.fake

        class _T:
            def set(self, **kw):
                fake.thumb_called = True
                return type("_E", (), {"execute": lambda self: True})()

        return _T()


def test_schedule_upload_returns_video_id(tmp_path):
    vid = tmp_path / "final.mp4"
    vid.write_bytes(b"x" * 1024)
    body = yt.seo_document(_topic(), "hook", publish_at=_future())
    fake = _FakeUploadYT()
    assert yt.schedule_upload(fake, vid, body) == "yt-abc123"


def test_thumbnail_is_attached_when_provided(tmp_path):
    vid = tmp_path / "final.mp4"
    vid.write_bytes(b"x" * 1024)
    thumb = tmp_path / "thumb.png"
    thumb.write_bytes(b"png")
    fake = _FakeUploadYT()
    body = yt.seo_document(_topic(), "hook", publish_at=_future())
    yt.schedule_upload(fake, vid, body, thumbnail_path=thumb)
    assert fake.thumb_called is True


def test_schedule_upload_missing_video_raises(tmp_path):
    body = yt.seo_document(_topic(), "hook", publish_at=_future())
    with pytest.raises(yt.YouTubeError):
        yt.schedule_upload(_FakeUploadYT(), tmp_path / "nope.mp4", body)


def test_schedule_upload_empty_video_raises(tmp_path):
    vid = tmp_path / "empty.mp4"
    vid.write_bytes(b"")
    body = yt.seo_document(_topic(), "hook", publish_at=_future())
    with pytest.raises(yt.YouTubeError):
        yt.schedule_upload(_FakeUploadYT(), vid, body)


def test_load_credentials_missing_token_raises_actionable(tmp_path, monkeypatch):
    monkeypatch.setenv("YOUTUBE_TOKEN_FILE", str(tmp_path / "missing.json"))
    with pytest.raises(yt.YouTubeAuthError) as ei:
        yt.load_credentials()
    assert "--youtube-auth" in str(ei.value)


def test_seo_json_roundtrip():
    body = yt.seo_document(_topic(), "hook", publish_at=_future())
    assert yt.seo_document_to_json(body).startswith("{\n  \"snippet\"")