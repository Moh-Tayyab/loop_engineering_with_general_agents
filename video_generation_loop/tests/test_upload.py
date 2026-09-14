"""Tests for the upload marker tombstone (idempotent, crash-safe uploads)

The marker `.runtime/uploaded.json` is a three-state tombstone
(pending -> done | failed), each state durably written before the next action.
These tests exercise the pure/disk logic in src.main without any YouTube call.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import src.main as main
from src.planner import Scene, Storyboard, Topic

TOPIC_TITLE = "Match the model to the task"


def _sb_json(topic: str = TOPIC_TITLE) -> dict:
    scenes = []
    for n in range(1, 4):
        scenes.append(
            {
                "scene_number": n,
                "duration_sec": 20,
                "voiceover": f"narration {n}",
                "flow_video_prompt": f"visual {n}",
                "needs_presenter": n == 1,
            }
        )
    return {"day": 9, "topic": topic, "hook": "hook", "scenes": scenes, "captions": {}}


def _make_day(tmp_path: Path, name: str = "day_09") -> Path:
    day_dir = tmp_path / name
    day_dir.mkdir(parents=True, exist_ok=True)
    (day_dir / "final.mp4").write_bytes(b"x")
    (day_dir / "storyboard.json").write_text(json.dumps(_sb_json()))
    return day_dir


def _fake_youtube(monkeypatch, video_id: str = "vid123") -> list[tuple[str, object]]:
    calls: list[tuple[str, object]] = []

    def build_youtube_client():
        return object()

    def schedule_upload(youtube, final_path, body, thumbnail_path=None):
        calls.append(("schedule", final_path.name))
        return video_id

    def describe_upload(video_id, body):
        calls.append(("describe", video_id))

    def seo_document(topic, hook, publish_at=None):
        return {"status": {"publishAt": "2026-09-14T00:00:00Z"}, "snippet": {}}

    monkeypatch.setattr("src.youtube_upload.build_youtube_client", build_youtube_client)
    monkeypatch.setattr("src.youtube_upload.schedule_upload", schedule_upload)
    monkeypatch.setattr("src.youtube_upload.describe_upload", describe_upload)
    monkeypatch.setattr("src.youtube_upload.seo_document", seo_document)
    return calls


# --- marker loader ------------------------------------------------------------
def test_load_marker_missing(tmp_path):
    assert main._load_marker(tmp_path / "nope.json") == {}


def test_load_marker_legacy_and_rows(tmp_path):
    p = tmp_path / "uploaded.json"
    p.write_text(
        json.dumps(
            {
                "day_08": "abc123",
                "day_09": {"status": "pending", "video_id": None, "ts": "t", "error": None},
            }
        )
    )
    out = main._load_marker(p)
    assert out["day_08"] == {"status": "done", "video_id": "abc123", "ts": None, "error": None}
    assert out["day_09"]["status"] == "pending"


# --- tombstone transitions ----------------------------------------------------
def test_upload_success_writes_done_tombstone(tmp_path, monkeypatch):
    day_dir = _make_day(tmp_path)
    marker = tmp_path / "uploaded.json"
    calls = _fake_youtube(monkeypatch)
    assert main._upload_one(day_dir / "final.mp4", day_dir, marker) == 0
    row = main._load_marker(marker)["day_09"]
    assert row["status"] == "done" and row["video_id"] == "vid123"
    assert calls == [("schedule", "final.mp4"), ("describe", "vid123")]


def test_upload_failure_marks_failed_tombstone(tmp_path, monkeypatch):
    day_dir = _make_day(tmp_path)
    marker = tmp_path / "uploaded.json"

    def boom(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr("src.youtube_upload.build_youtube_client", lambda: object())
    monkeypatch.setattr("src.youtube_upload.schedule_upload", boom)
    monkeypatch.setattr(
        "src.youtube_upload.seo_document",
        lambda topic, hook, publish_at=None: {"status": {"publishAt": "2026-09-14T00:00:00Z"}, "snippet": {}},
    )
    with pytest.raises(SystemExit):
        main._upload_one(day_dir / "final.mp4", day_dir, marker)
    row = main._load_marker(marker)["day_09"]
    assert row["status"] == "failed" and "network down" in (row["error"] or "")


def test_upload_pending_blocks_never_double_uploads(tmp_path, monkeypatch):
    day_dir = _make_day(tmp_path)
    marker = tmp_path / "uploaded.json"
    marker.write_text(
        json.dumps(
            {"day_09": {"status": "pending", "video_id": None, "ts": "t", "error": None}}
        )
    )
    calls = _fake_youtube(monkeypatch)
    with pytest.raises(SystemExit):
        main._upload_one(day_dir / "final.mp4", day_dir, marker)
    assert calls == []  # schedule_upload never ran -> no double post


def test_upload_done_skips(tmp_path, monkeypatch):
    day_dir = _make_day(tmp_path)
    marker = tmp_path / "uploaded.json"
    marker.write_text(json.dumps({"day_09": {"status": "done", "video_id": "old", "ts": "t", "error": None}}))
    calls = _fake_youtube(monkeypatch)
    assert main._upload_one(day_dir / "final.mp4", day_dir, marker) == 0
    assert calls == []  # already uploaded -> skip


def test_upload_failed_retries_and_promotes_to_done(tmp_path, monkeypatch):
    day_dir = _make_day(tmp_path)
    marker = tmp_path / "uploaded.json"
    marker.write_text(json.dumps({"day_09": {"status": "failed", "video_id": None, "ts": "t", "error": "tm"}}))
    calls = _fake_youtube(monkeypatch)
    assert main._upload_one(day_dir / "final.mp4", day_dir, marker) == 0
    assert calls == [("schedule", "final.mp4"), ("describe", "vid123")]
    assert main._load_marker(marker)["day_09"]["status"] == "done"


def test_upload_legacy_marker_skips(tmp_path, monkeypatch):
    day_dir = _make_day(tmp_path)
    marker = tmp_path / "uploaded.json"
    marker.write_text(json.dumps({"day_09": "legacy-video-id"}))
    calls = _fake_youtube(monkeypatch)
    assert main._upload_one(day_dir / "final.mp4", day_dir, marker) == 0
    assert calls == []


def test_load_marker_drops_garbage_rows(tmp_path):
    p = tmp_path / "uploaded.json"
    p.write_text(json.dumps({"day_09": 42, "day_10": None, "day_11": "good"}))
    out = main._load_marker(p)
    assert out == {"day_11": {"status": "done", "video_id": "good", "ts": None, "error": None}}


def _seo_doc(topic, hook, publish_at=None):
    return {"status": {"publishAt": "2026-09-14T00:00:00Z"}, "snippet": {}}


def test_upload_post_commit_error_parks_pending_never_retries(tmp_path, monkeypatch):
    """Checker finding B1: a thumbnail failure happens AFTER the video insert
    committed (video_id known) — the tombstone must be `pending`, so the next
    cron run NEVER auto-retries (double post)."""
    from src.youtube_upload import PostCommitError

    day_dir = _make_day(tmp_path)
    marker = tmp_path / "uploaded.json"

    def schedule_upload(youtube, final_path, body, thumbnail_path=None):
        raise PostCommitError("thumbnail set failed: <HttpError 400>", video_id="vid-committed")

    monkeypatch.setattr("src.youtube_upload.build_youtube_client", lambda: object())
    monkeypatch.setattr("src.youtube_upload.schedule_upload", schedule_upload)
    monkeypatch.setattr("src.youtube_upload.seo_document", _seo_doc)
    with pytest.raises(SystemExit):
        main._upload_one(day_dir / "final.mp4", day_dir, marker)
    row = main._load_marker(marker)["day_09"]
    assert row["status"] == "pending" and row["video_id"] == "vid-committed"

    # next cron run: pending blocks it → schedule_upload NOT called again
    calls = _fake_youtube(monkeypatch)
    with pytest.raises(SystemExit):
        main._upload_one(day_dir / "final.mp4", day_dir, marker)
    assert calls == []


def test_upload_resumable_error_parks_pending(tmp_path, monkeypatch):
    """Indeterminate resumable window: video MIGHT be committed, video_id
    unknown → still `pending` (conservative: never auto-retry)."""
    from src.youtube_upload import PostCommitError

    day_dir = _make_day(tmp_path)
    marker = tmp_path / "uploaded.json"

    def schedule_upload(youtube, final_path, body, thumbnail_path=None):
        raise PostCommitError("YouTube upload did not complete within 3600s")

    monkeypatch.setattr("src.youtube_upload.build_youtube_client", lambda: object())
    monkeypatch.setattr("src.youtube_upload.schedule_upload", schedule_upload)
    monkeypatch.setattr("src.youtube_upload.seo_document", _seo_doc)
    with pytest.raises(SystemExit):
        main._upload_one(day_dir / "final.mp4", day_dir, marker)
    row = main._load_marker(marker)["day_09"]
    assert row["status"] == "pending" and row["video_id"] is None


def test_upload_real_schedule_resumable_deadline_parks_pending(tmp_path, monkeypatch):
    """F1 through the REAL schedule_upload boundary (second-round finding): a
    plain YouTubeError deadline fired out of `_resume_upload` must become
    `pending`, never `failed` (retryable) — and the second run must not resume."""
    from src.youtube_upload import YouTubeError

    day_dir = _make_day(tmp_path)
    marker = tmp_path / "uploaded.json"
    calls = {"resume": 0}

    class _FakeVideos:
        def insert(self, **kw):
            return "request"

    class _FakeYoutube:
        def videos(self):
            return _FakeVideos()

    def resume(request, *, timeout_s=3600):
        calls["resume"] += 1
        raise YouTubeError("YouTube upload did not complete within 3600s")

    monkeypatch.setattr("src.youtube_upload._resume_upload", resume)
    monkeypatch.setattr("src.youtube_upload.build_youtube_client", lambda: _FakeYoutube())
    monkeypatch.setattr("src.youtube_upload.seo_document", _seo_doc)

    with pytest.raises(SystemExit):
        main._upload_one(day_dir / "final.mp4", day_dir, marker)
    row = main._load_marker(marker)["day_09"]
    assert row["status"] == "pending" and row["video_id"] is None

    # next run: pending gate dies before schedule_upload → no re-resume
    with pytest.raises(SystemExit):
        main._upload_one(day_dir / "final.mp4", day_dir, marker)
    assert calls["resume"] == 1


def test_upload_response_without_id_parks_pending(tmp_path, monkeypatch):
    """Third-round finding: _resume_upload returns a response WITHOUT an 'id'
    (post-commit, video may exist) → `pending`, never `failed`; no re-resume."""
    day_dir = _make_day(tmp_path)
    marker = tmp_path / "uploaded.json"
    calls = {"resume": 0}

    class _FakeVideos:
        def insert(self, **kw):
            return "request"

    class _FakeYoutube:
        def videos(self):
            return _FakeVideos()

    def resume(request, *, timeout_s=3600):
        calls["resume"] += 1
        return {"kind": "youtube#video"}  # no "id" key

    monkeypatch.setattr("src.youtube_upload._resume_upload", resume)
    monkeypatch.setattr("src.youtube_upload.build_youtube_client", lambda: _FakeYoutube())
    monkeypatch.setattr("src.youtube_upload.seo_document", _seo_doc)

    with pytest.raises(SystemExit):
        main._upload_one(day_dir / "final.mp4", day_dir, marker)
    row = main._load_marker(marker)["day_09"]
    assert row["status"] == "pending" and row["video_id"] is None

    with pytest.raises(SystemExit):
        main._upload_one(day_dir / "final.mp4", day_dir, marker)
    assert calls["resume"] == 1


def test_upload_real_schedule_thumbnail_transport_failure_parks_pending(tmp_path, monkeypatch):
    """F2 through the REAL boundary: insert commits (video_id known), thumbnail
    set raises a NON-HttpError transport error (socket.timeout) → `pending`,
    never `failed`; second run does not re-upload."""
    import socket

    day_dir = _make_day(tmp_path)
    (day_dir / "thumbnail.png").write_bytes(b"thumb")
    marker = tmp_path / "uploaded.json"
    calls = {"resume": 0}

    class _FakeThumbs:
        def set(self, **kwargs):
            return self

        def execute(self):
            raise socket.timeout("timed out")

    class _FakeVideos:
        def insert(self, **kw):
            return "request"

    class _FakeYoutube:
        def videos(self):
            return _FakeVideos()

        def thumbnails(self):
            return _FakeThumbs()

    def resume(request, *, timeout_s=3600):
        calls["resume"] += 1
        return {"id": "committed-vid"}

    monkeypatch.setattr("src.youtube_upload._resume_upload", resume)
    monkeypatch.setattr("src.youtube_upload.build_youtube_client", lambda: _FakeYoutube())
    monkeypatch.setattr("src.youtube_upload.seo_document", _seo_doc)

    with pytest.raises(SystemExit):
        main._upload_one(day_dir / "final.mp4", day_dir, marker)
    row = main._load_marker(marker)["day_09"]
    assert row["status"] == "pending" and row["video_id"] == "committed-vid"

    with pytest.raises(SystemExit):
        main._upload_one(day_dir / "final.mp4", day_dir, marker)
    assert calls["resume"] == 1


# --- reference-image day preflight --------------------------------------------
def _sb(*scenes) -> Storyboard:
    return Storyboard(day=9, topic=Topic("t1", TOPIC_TITLE, "h"), hook="h", scenes=list(scenes))


def test_preflight_missing_ref_dies(tmp_path):
    sb = _sb(
        Scene(1, 20, "", "", needs_presenter=True, reference_image=str(tmp_path / "missing.png")),
        Scene(2, 20, "", ""),
    )
    with pytest.raises(SystemExit):
        main._preflight_references(sb)


def test_preflight_missing_raw_dies(tmp_path):
    sb = _sb(Scene(1, 20, "", "", needs_presenter=True, reference_image=None))
    with pytest.raises(SystemExit):
        main._preflight_references(sb)


def test_preflight_ok_with_existing_ref(tmp_path):
    ref = tmp_path / "person.png"
    ref.write_bytes(b"png")
    sb = _sb(
        Scene(1, 20, "", "", needs_presenter=True, reference_image=str(ref)),
        Scene(2, 20, "", ""),
    )
    main._preflight_references(sb)  # no raise